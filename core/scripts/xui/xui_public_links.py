#!/usr/bin/env python3
"""
Модуль генерации персональных публичных VLESS-ссылок для пользователей Hysteria 2.

Генерирует индивидуальные VLESS-ссылки на основе синхронизации Hysteria 2 ↔ 3X-UI
с использованием публичных доменов через Caddy reverse-proxy (TLS 443).

Каждый пользователь получает уникальные ссылки для каждого сервера 3X-UI,
к которому у него есть доступ согласно плану (standard/premium).
"""

import logging
import json
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import quote, unquote
from dataclasses import dataclass

# Импорты из xui_client (могут быть приватными функциями)
try:
    from xui.xui_client import (
        XUIClient, 
        XUIClientError,
        _normalize_stream_settings,
        _extract_xhttp_path,
        _extract_grpc_service_name
    )
except ImportError:
    # Fallback если импорт не удался
    logger.error("Failed to import from xui.xui_client")
    raise

logger = logging.getLogger(__name__)


@dataclass
class XUIServerPublicConfig:
    """Конфигурация публичного доступа к серверу X-UI"""
    server_id: str  # Идентификатор сервера (name из конфига)
    public_host: str  # Публичный домен (gatewayX.example.com)
    public_port: int = 443  # Публичный порт (обычно 443)
    sni: Optional[str] = None  # SNI для TLS (по умолчанию = public_host)
    display_name: Optional[str] = None  # Отображаемое имя сервера
    emoji: Optional[str] = None  # Эмодзи для отображения
    country: Optional[str] = None  # Страна/регион
    
    def __post_init__(self):
        """Устанавливает SNI = public_host если не указан"""
        if not self.sni:
            self.sni = self.public_host


# UserXUIMapping не используется в текущей реализации,
# так как данные берутся напрямую из БД через db.get_xui_mapping()
# Оставлено для возможного будущего использования
# @dataclass
# class UserXUIMapping:
#     """Маппинг пользователя Hysteria 2 → 3X-UI"""
#     hysteria_username: str
#     client_uuid: str  # Индивидуальный UUID клиента в 3X-UI
#     inbound_ids: List[int]  # Список ID inbounds, где добавлен клиент
#     xui_host: Optional[str] = None  # Хост сервера (для multi-xui режима)


def parse_stream_settings(stream_settings: Any, inbound_id: int | str) -> Dict[str, Any]:
    """
    Парсит streamSettings из различных форматов в dict.
    
    Поддерживает:
    - dict → возвращает как есть
    - JSON-строка → json.loads()
    - объект Pydantic → .dict() / .model_dump()
    - объект с __dict__ → рекурсивное преобразование
    
    Args:
        stream_settings: streamSettings в любом формате
        inbound_id: ID inbound для логирования
        
    Returns:
        Нормализованный dict
        
    Raises:
        ValueError: Если парсинг не удался
    """
    if stream_settings is None:
        logger.warning(f"Inbound {inbound_id}: stream_settings is None")
        return {}
    
    # Используем существующую функцию нормализации
    normalized = _normalize_stream_settings(stream_settings)
    
    if not isinstance(normalized, dict):
        logger.error(
            f"Inbound {inbound_id}: Failed to normalize stream_settings. "
            f"Type: {type(normalized)}, value: {normalized}"
        )
        return {}
    
    return normalized


def build_public_vless_link(
    client_uuid: str,
    inbound: Dict[str, Any],
    server_config: XUIServerPublicConfig,
    remark: Optional[str] = None
) -> Optional[str]:
    """
    Генерирует публичную VLESS-ссылку для клиента.
    
    Правила:
    - Использует публичный домен и порт из server_config
    - Парсит streamSettings из inbound
    - Генерирует корректные параметры для xHTTP и gRPC
    - Добавляет TLS параметры (security=tls, sni)
    - НИКОГДА не использует 127.0.0.1
    
    Args:
        client_uuid: UUID клиента (VLESS id) - ИНДИВИДУАЛЬНЫЙ
        inbound: Словарь с данными inbound из 3X-UI API
        server_config: Конфигурация публичного доступа к серверу
        remark: Опциональное имя для fragment (#name)
        
    Returns:
        VLESS ссылка или None если генерация не удалась
        
    Raises:
        XUIClientError: При критических ошибках (отсутствие обязательных параметров)
    """
    try:
        # Извлекаем базовые параметры
        inbound_id = inbound.get('id')
        if not inbound_id:
            logger.error("build_public_vless_link: inbound.id is missing")
            return None
        
        protocol = inbound.get('protocol', '').lower()
        if protocol != 'vless':
            logger.warning(f"Inbound {inbound_id}: Protocol '{protocol}' is not VLESS, skipping")
            return None
        
        # Парсим streamSettings
        stream_settings_raw = inbound.get('streamSettings') or inbound.get('stream_settings')
        if not stream_settings_raw:
            logger.warning(f"Inbound {inbound_id}: stream_settings is missing")
            return None
        
        stream_settings = parse_stream_settings(stream_settings_raw, inbound_id)
        if not stream_settings:
            logger.warning(f"Inbound {inbound_id}: Failed to parse stream_settings")
            return None
        
        # Определяем network
        network = stream_settings.get('network', '').lower()
        if not network:
            logger.warning(f"Inbound {inbound_id}: network is missing in stream_settings")
            return None
        
        # Формируем базовую часть ссылки
        # ВАЖНО: Используем ТОЛЬКО публичный домен и порт
        host = server_config.public_host
        port = server_config.public_port
        
        # Собираем query параметры
        query_params = []
        
        # Обязательные параметры
        query_params.append(f"type={network}")
        query_params.append("encryption=none")
        
        # Параметры в зависимости от типа сети
        if network == 'xhttp':
            # Извлекаем path
            try:
                path = _extract_xhttp_path(stream_settings, inbound_id)
                query_params.append(f"path={quote(path, safe='')}")
            except ValueError as e:
                logger.error(f"Inbound {inbound_id}: Failed to extract xhttp path: {e}")
                return None
            
            # Извлекаем mode (по умолчанию 'auto')
            xhttp_settings = stream_settings.get('xhttpSettings') or stream_settings.get('xhttp_settings')
            mode = 'auto'
            if xhttp_settings:
                if not isinstance(xhttp_settings, dict):
                    xhttp_settings = _normalize_stream_settings(xhttp_settings)
                if isinstance(xhttp_settings, dict):
                    mode_val = xhttp_settings.get('mode')
                    if mode_val and isinstance(mode_val, str):
                        mode = mode_val.strip() if mode_val.strip() else 'auto'
            
            query_params.append(f"mode={mode}")
            
            # Опциональные параметры для xHTTP
            if xhttp_settings and isinstance(xhttp_settings, dict):
                xhttp_host = xhttp_settings.get('host')
                if xhttp_host and isinstance(xhttp_host, str) and xhttp_host.strip():
                    query_params.append(f"host={quote(xhttp_host, safe='')}")
            
            # TLS параметры для xHTTP
            query_params.append("security=tls")
            query_params.append("alpn=h2")
            query_params.append("fp=chrome")
            if server_config.sni:
                query_params.append(f"sni={quote(server_config.sni, safe='')}")
        
        elif network == 'grpc':
            # Извлекаем serviceName - ОБЯЗАТЕЛЬНЫЙ параметр
            try:
                service_name = _extract_grpc_service_name(stream_settings, inbound_id)
                if not service_name or not service_name.strip():
                    logger.error(f"Inbound {inbound_id}: serviceName is empty after extraction")
                    return None
                query_params.append(f"serviceName={quote(service_name, safe='')}")
            except ValueError as e:
                logger.error(f"Inbound {inbound_id}: Failed to extract grpc serviceName: {e}")
                return None
            except Exception as e:
                logger.error(f"Inbound {inbound_id}: Unexpected error extracting grpc serviceName: {e}")
                return None
            
            # Извлекаем mode (multi/gun) если есть
            grpc_settings = stream_settings.get('grpcSettings') or stream_settings.get('grpc_settings')
            if grpc_settings:
                if not isinstance(grpc_settings, dict):
                    grpc_settings = _normalize_stream_settings(grpc_settings)
                if isinstance(grpc_settings, dict):
                    grpc_mode = grpc_settings.get('multiMode') or grpc_settings.get('multi_mode')
                    if grpc_mode is not None:
                        mode_value = 'multi' if grpc_mode else 'gun'
                        query_params.append(f"mode={mode_value}")
                    
                    # Опциональный authority
                    authority = grpc_settings.get('authority')
                    if authority and isinstance(authority, str) and authority.strip():
                        query_params.append(f"authority={quote(authority, safe='')}")
            
            # TLS параметры для gRPC
            query_params.append("security=tls")
            if server_config.sni:
                query_params.append(f"sni={quote(server_config.sni, safe='')}")
        
        else:
            # Другие типы транспорта (ws, tcp, etc.) - базовая генерация
            logger.debug(f"Inbound {inbound_id}: Network '{network}' - using basic link generation")
            query_params.append("security=tls")
            if server_config.sni:
                query_params.append(f"sni={quote(server_config.sni, safe='')}")
        
        # Собираем ссылку
        query_string = '&'.join(query_params)
        uri = f"vless://{client_uuid}@{host}:{port}?{query_string}"
        
        # Добавляем fragment (#name)
        if remark:
            uri += f"#{quote(remark, safe='')}"
        
        # Финальная валидация
        if network == 'xhttp':
            # Проверяем что path присутствует и не пустой
            if 'path=' not in query_string:
                logger.error(f"Inbound {inbound_id}: Generated xhttp URI missing path parameter")
                return None
            # Проверяем что path не равен "/"
            path_match = None
            import re
            path_match = re.search(r'path=([^&#]*)', uri)
            if path_match:
                decoded_path = unquote(path_match.group(1))
                if decoded_path == '/' or not decoded_path:
                    logger.error(f"Inbound {inbound_id}: Generated xhttp URI has invalid path: '{decoded_path}'")
                    return None
        
        elif network == 'grpc':
            # Проверяем что serviceName присутствует и не пустой
            import re
            if 'serviceName=' not in query_string:
                logger.error(f"Inbound {inbound_id}: Generated grpc URI missing serviceName parameter")
                return None
            service_name_match = re.search(r'serviceName=([^&#]*)', uri)
            if service_name_match:
                service_name_value = unquote(service_name_match.group(1))
                if not service_name_value or not service_name_value.strip():
                    logger.error(f"Inbound {inbound_id}: Generated grpc URI has EMPTY serviceName")
                    return None
            else:
                logger.error(f"Inbound {inbound_id}: Generated grpc URI missing serviceName parameter (regex check failed)")
                return None
        
        logger.debug(f"Inbound {inbound_id}: Generated public VLESS link for network={network}")
        return uri
        
    except Exception as e:
        logger.error(f"build_public_vless_link failed: {e}", exc_info=True)
        return None


def build_user_public_links(
    hysteria_username: str,
    xui_sync_manager,
    server_configs: Dict[str, XUIServerPublicConfig]
) -> List[Dict[str, Any]]:
    """
    Генерирует все публичные VLESS-ссылки для пользователя.
    
    Логика:
    1. Получает маппинг пользователя из БД
    2. Определяет план пользователя (standard/premium)
    3. Для каждого доступного сервера:
       - Получает список inbounds
       - Для каждого inbound генерирует публичную ссылку
       - Использует индивидуальный UUID из маппинга
    4. Возвращает список ссылок с метаданными
    
    Args:
        hysteria_username: Имя пользователя в Hysteria 2
        xui_sync_manager: Экземпляр XUISyncManager
        server_configs: Словарь {server_id: XUIServerPublicConfig}
        
    Returns:
        Список словарей:
        [
            {
                "name": "🇹🇷 Турция (Резерв)",
                "uri": "vless://...",
                "server_id": "server1",
                "inbound_id": 1,
                "network": "xhttp"
            },
            ...
        ]
    """
    from db.database import db
    
    if not db:
        logger.error("Database not available")
        return []
    
    # Получаем данные пользователя для определения плана
    user_data = db.get_user(hysteria_username)
    if not user_data:
        logger.warning(f"User {hysteria_username} not found in Hysteria 2")
        return []
    
    user_plan = str(user_data.get('plan', 'standard')).lower().strip()
    if user_plan not in ('standard', 'premium'):
        user_plan = 'standard'
    
    # Получаем маппинг
    mapping = db.get_xui_mapping(hysteria_username)
    if not mapping:
        logger.warning(f"No X-UI mapping found for user {hysteria_username}")
        return []
    
    client_uuid = mapping.get('xui_client_uuid')
    if not client_uuid:
        logger.warning(f"No client UUID in mapping for user {hysteria_username}")
        return []
    
    inbound_ids = mapping.get('inbound_ids', [])
    xui_host = mapping.get('xui_host')
    
    # Получаем серверы для плана пользователя
    servers_for_plan = xui_sync_manager._get_servers_for_plan(user_plan)
    
    links = []
    
    # Для каждого сервера
    for host, client, server_config_dict in servers_for_plan:
        server_id = server_config_dict.get('name', host)
        
        # Получаем публичную конфигурацию сервера
        public_config = server_configs.get(server_id)
        if not public_config:
            logger.warning(
                f"Server {server_id} (host={host}) not found in server_configs. "
                f"Available: {list(server_configs.keys())}"
            )
            continue
        
        # Получаем список inbounds для этого сервера
        try:
            inbound_ids_for_server = xui_sync_manager._get_inbound_ids(client, server_config_dict)
            
            for inbound_id in inbound_ids_for_server:
                try:
                    # Получаем inbound
                    inbound = client.get_inbound(inbound_id)
                    if not inbound:
                        logger.debug(f"Inbound {inbound_id} not found on server {server_id}, skipping")
                        continue
                    
                    # Формируем имя для ссылки
                    inbound_remark = inbound.get('remark', '')
                    
                    # Используем display_name/emoji из публичной конфигурации сервера
                    display_parts = []
                    if public_config.emoji:
                        display_parts.append(public_config.emoji)
                    if public_config.display_name:
                        display_parts.append(public_config.display_name)
                    elif public_config.country:
                        display_parts.append(public_config.country)
                    
                    # Добавляем remark из inbound если есть
                    if inbound_remark:
                        # Проверяем, не дублируется ли remark
                        remark_lower = inbound_remark.lower()
                        if not any(remark_lower in part.lower() for part in display_parts):
                            display_parts.append(f"({inbound_remark})")
                    
                    name = ' '.join(display_parts) if display_parts else inbound_remark or f"Inbound {inbound_id}"
                    
                    # Генерируем публичную ссылку
                    uri = build_public_vless_link(
                        client_uuid=client_uuid,
                        inbound=inbound,
                        server_config=public_config,
                        remark=name
                    )
                    
                    if uri:
                        network = inbound.get('stream_settings', {}).get('network', 'unknown')
                        links.append({
                            "name": name,
                            "uri": uri,
                            "server_id": server_id,
                            "inbound_id": inbound_id,
                            "network": network,
                            "public_host": public_config.public_host,
                            "public_port": public_config.public_port
                        })
                        logger.info(
                            f"Generated public link for user {hysteria_username}: "
                            f"server={server_id}, inbound={inbound_id}, network={network}"
                        )
                    else:
                        logger.warning(
                            f"Failed to generate public link for user {hysteria_username}: "
                            f"server={server_id}, inbound={inbound_id}"
                        )
                
                except Exception as e:
                    logger.warning(
                        f"Error generating link for inbound {inbound_id} on server {server_id}: {e}",
                        exc_info=True
                    )
                    continue
        
        except Exception as e:
            logger.warning(
                f"Error getting inbounds from server {server_id} (host={host}): {e}",
                exc_info=True
            )
            continue
    
    return links


def load_server_public_configs(xui_config: Dict[str, Any]) -> Dict[str, XUIServerPublicConfig]:
    """
    Загружает публичные конфигурации серверов из конфигурации X-UI.
    
    Args:
        xui_config: Конфигурация X-UI (из load_xui_config())
        
    Returns:
        Словарь {server_id: XUIServerPublicConfig}
    """
    from urllib.parse import urlparse
    
    configs = {}
    
    for server in xui_config.get('xui_servers', []):
        if not server.get('enabled', True):
            continue
        
        server_id = server.get('name')
        if not server_id:
            # Используем host как fallback для server_id
            host_url = server.get('host', '')
            try:
                parsed = urlparse(host_url)
                server_id = parsed.hostname or host_url
            except:
                server_id = host_url or f"server_{len(configs)}"
        
        public_host = server.get('public_host')
        if not public_host:
            # Извлекаем из host если не указан
            host_url = server.get('host', '')
            try:
                parsed = urlparse(host_url)
                public_host = parsed.hostname
            except:
                public_host = None
        
        if not public_host:
            logger.warning(f"Server {server_id}: public_host is missing, skipping")
            continue
        
        # SNI по умолчанию = public_host, но можно переопределить
        sni = server.get('sni')
        if not sni:
            sni = public_host
        
        public_config = XUIServerPublicConfig(
            server_id=server_id,
            public_host=public_host,
            public_port=server.get('public_port', 443),
            sni=sni,
            display_name=server.get('display_name'),
            emoji=server.get('emoji'),
            country=server.get('country')
        )
        
        configs[server_id] = public_config
        logger.debug(
            f"Loaded public config for server {server_id}: "
            f"{public_config.public_host}:{public_config.public_port}, "
            f"sni={public_config.sni}"
        )
    
    return configs
