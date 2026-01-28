#!/usr/bin/env python3
"""
Универсальный генератор персональных VLESS-ссылок для пользователей Hysteria 2.

АРХИТЕКТУРА:
- Поддержка ВСЕХ транспортов Xray/V2Ray через систему handler-ов
- Работа с сырыми данными из API 3X-UI (без pydantic/моделей)
- Персональные UUID для каждого пользователя из sync mapping
- Изоляция ошибок: проблема с одним inbound не ломает остальные

ПОДДЕРЖИВАЕМЫЕ ТРАНСПОРТЫ:
- gRPC, xHTTP, WebSocket, TCP, HTTP/2, SplitHTTP, HTTPUpgrade, KCP, QUIC

Каждый пользователь получает уникальные ссылки для каждого сервера 3X-UI,
к которому у него есть доступ согласно плану (standard/premium).
"""

import logging
import json
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import quote, unquote, urlparse, parse_qsl
from dataclasses import dataclass

# Настраиваем логгер ДО импортов, чтобы использовать его в exception handlers
logger = logging.getLogger(__name__)

# Импорты из xui_client (для утилит) и нового API клиента
try:
    from xui.xui_client import (
        parse_raw_stream_settings  # Утилита для парсинга, не зависит от py3xui
    )
    from xui.xui_api_wrapper import XUIAPIWrapper
    from xui.xui_api_client import XUIAPIError
    
    # Для обратной совместимости
    XUIClient = XUIAPIWrapper
    XUIClientError = XUIAPIError
except ImportError as e:
    logger.error(f"Failed to import from xui modules: {e}")
    raise

# Импорты handler-ов транспортов и безопасности
try:
    from xui.transport_handlers import get_transport_handler, is_transport_supported
    from xui.security_handlers import apply_security
except ImportError as e:
    logger.error(f"Failed to import from xui.transport_handlers or xui.security_handlers: {e}")
    raise


@dataclass
class XUIServerPublicConfig:
    """Конфигурация публичного доступа к серверу X-UI"""
    server_id: str  # Идентификатор сервера (name из конфига)
    public_host: str  # Публичный домен (gatewayX.example.com)
    public_port: int = 443  # Публичный порт (обычно 443)
    sni: Optional[str] = None  # SNI для TLS (по умолчанию = public_host)
    xhttp_alpn: Optional[str] = None  # ALPN для xHTTP (по умолчанию h2)
    xhttp_fp: Optional[str] = None  # Fingerprint для xHTTP (по умолчанию chrome)
    xhttp_mode: Optional[str] = None  # Mode для xHTTP (по умолчанию auto)
    grpc_authority: Optional[str] = None  # Authority для gRPC (опционально)
    
    def __post_init__(self):
        """Устанавливает SNI = public_host если не указан"""
        if not self.sni:
            self.sni = self.public_host
        if not self.xhttp_alpn:
            self.xhttp_alpn = 'h2'
        if not self.xhttp_fp:
            self.xhttp_fp = 'chrome'
        if not self.xhttp_mode:
            self.xhttp_mode = 'auto'


def build_public_vless_link(
    client_uuid: str,
    inbound: Dict[str, Any],
    server_config: XUIServerPublicConfig,
    remark: Optional[str] = None
) -> Optional[str]:
    """
    Универсальный генератор публичной VLESS-ссылки для клиента.
    
    АРХИТЕКТУРА:
    - Использует систему handler-ов для поддержки ВСЕХ транспортов
    - Парсит RAW streamSettings из API 3X-UI
    - Изоляция ошибок: проблема с параметрами не прерывает другие inbound'ы
    
    ПРОЦЕСС:
    1. Парсит streamSettings (RAW JSON → dict)
    2. Определяет network (транспорт)
    3. Вызывает соответствующий transport handler
    4. Применяет параметры безопасности (TLS/Reality)
    5. Собирает финальную ссылку
    
    Args:
        client_uuid: UUID клиента (VLESS id) - ИНДИВИДУАЛЬНЫЙ из sync mapping
        inbound: Словарь с RAW данными inbound из API 3X-UI
        server_config: Конфигурация публичного доступа к серверу
        remark: Опциональное имя для fragment (#name)
        
    Returns:
        VLESS ссылка или None если генерация не удалась
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
        
        # Парсим streamSettings из СЫРЫХ данных API БЕЗ преобразований ключей
        stream_settings_raw = inbound.get('streamSettings') or inbound.get('stream_settings')
        if not stream_settings_raw:
            logger.warning(f"Inbound {inbound_id}: stream_settings is missing in RAW inbound data")
            return None
        
        # Используем parse_raw_stream_settings для работы с СЫРЫМИ данными
        stream_settings = parse_raw_stream_settings(stream_settings_raw, inbound_id)
        if not stream_settings:
            logger.warning(f"Inbound {inbound_id}: Failed to parse RAW stream_settings")
            return None
        
        logger.debug(
            f"Inbound {inbound_id}: Parsed RAW stream_settings, "
            f"keys: {list(stream_settings.keys())}, "
            f"network: {stream_settings.get('network', 'unknown')}"
        )
        
        # СТРОГО определяем network перед обработкой
        network = (stream_settings.get('network') or '').lower().strip()
        if not network:
            logger.warning(f"Inbound {inbound_id}: network is missing in stream_settings, skipping")
            return None
        
        logger.debug(f"Inbound {inbound_id}: Processing inbound with network='{network}'")
        
        # Формируем базовую часть ссылки
        # ВАЖНО: Используем ТОЛЬКО публичный домен и порт
        host = server_config.public_host
        port = server_config.public_port
        
        # ====================================================================
        # УНИВЕРСАЛЬНАЯ ОБРАБОТКА ЧЕРЕЗ TRANSPORT HANDLERS
        # ====================================================================
        
        # Получаем handler для транспорта
        handler = get_transport_handler(network)
        
        if not handler:
            # Транспорт не поддерживается
            logger.warning(
                f"Inbound {inbound_id}: unsupported network='{network}', skipping link generation"
            )
            return None
        
        # Вызываем handler для извлечения параметров транспорта
        transport_query = handler(stream_settings, inbound_id)
        
        if not transport_query:
            # Handler вернул None (отсутствуют обязательные параметры)
            logger.warning(
                f"Inbound {inbound_id}: transport handler returned None for network='{network}', skipping"
            )
            return None
        
        # Добавляем общие параметры
        transport_query['encryption'] = 'none'
        
        # Применяем параметры безопасности (TLS/Reality/None)
        query = apply_security(transport_query, stream_settings, server_config, inbound_id)
        
        # ====================================================================
        # СБОРКА ФИНАЛЬНОЙ ССЫЛКИ
        # ====================================================================
        
        # Преобразуем dict query в query string
        query_params_list = []
        for key, value in query.items():
            if value and str(value).strip():
                # URL-encode значения если нужно
                if key in ('path', 'serviceName', 'host', 'sni', 'authority'):
                    query_params_list.append(f"{key}={quote(str(value), safe='')}")
                else:
                    query_params_list.append(f"{key}={value}")
        
        query_string = '&'.join(query_params_list)
        uri = f"vless://{client_uuid}@{host}:{port}?{query_string}"
        
        # Добавляем fragment (#name)
        if remark:
            uri += f"#{quote(remark, safe='')}"
        
        logger.debug(f"Inbound {inbound_id}: Generated universal VLESS link for network={network}")
        return uri
        
    except Exception as e:
        logger.error(f"build_public_vless_link failed: {e}", exc_info=True)
        return None


def build_user_public_links_from_cache(
    hysteria_username: str,
    servers_for_plan: List[Tuple[str, str, "XUIServerPublicConfig"]],
    inbounds_by_host: Dict[str, Dict[int, Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """
    Локальная генерация VLESS-ссылок без обращений к API 3X-UI.
    Использует только кэш inbounds (из фонового опроса) и build_public_vless_link.
    
    Args:
        hysteria_username: Имя пользователя в Hysteria 2
        servers_for_plan: Список (host, server_id, public_config) для плана пользователя
        inbounds_by_host: Кэш {host: {inbound_id: inbound_dict}} из xui_background_poller
        
    Returns:
        Список словарей с ключами name, uri, server_id, inbound_id, network, server_config, ...
    """
    try:
        from db.database import db
    except Exception:
        logger.debug("DB not available for build_user_public_links_from_cache")
        return []
    if not db:
        return []
    mapping = db.get_xui_mapping(hysteria_username)
    if not mapping:
        logger.debug(f"No X-UI mapping for {hysteria_username}")
        return []
    client_uuid = mapping.get("xui_client_uuid")
    if not client_uuid:
        return []
    links = []
    for host, server_id, public_config in servers_for_plan:
        inbounds = inbounds_by_host.get(host, {})
        for inbound_id, inbound in inbounds.items():
            if (inbound.get("protocol") or "").lower() != "vless":
                continue
            stream_settings = inbound.get("streamSettings") or inbound.get("stream_settings")
            network = (stream_settings.get("network") or "unknown") if isinstance(stream_settings, dict) else "unknown"
            remark = (inbound.get("remark") or "").strip() or f"Inbound {inbound_id}"
            uri = build_public_vless_link(
                client_uuid=client_uuid,
                inbound=inbound,
                server_config=public_config,
                remark=remark,
            )
            if uri:
                links.append({
                    "name": remark,
                    "uri": uri,
                    "server_id": server_id,
                    "inbound_id": inbound_id,
                    "network": network,
                    "public_host": public_config.public_host,
                    "public_port": public_config.public_port,
                    "server_config": {
                        "name": server_id,
                        "host": host,
                        "public_host": public_config.public_host,
                        "public_port": public_config.public_port,
                        "sni": public_config.sni,
                        "link_host_rewrite_from": "127.0.0.1",
                        "xhttp_alpn": public_config.xhttp_alpn,
                        "xhttp_fp": public_config.xhttp_fp,
                        "xhttp_mode": public_config.xhttp_mode,
                        "grpc_authority": public_config.grpc_authority,
                    },
                })
    return links


def build_user_public_links(
    hysteria_username: str,
    xui_sync_manager,
    server_configs: Dict[str, XUIServerPublicConfig]
) -> List[Dict[str, Any]]:
    """
    Генерирует все публичные VLESS-ссылки для пользователя.
    
    УНИВЕРСАЛЬНЫЙ ГЕНЕРАТОР:
    - Поддерживает ВСЕ транспорты через систему handler-ов
    - Изоляция ошибок: проблема с одним inbound не ломает остальные
    - Каждый inbound обрабатывается в своем try/except
    
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
    
    # Получаем серверы для плана пользователя
    servers_for_plan = xui_sync_manager._get_servers_for_plan(user_plan)
    
    links = []
    
    # ========================================================================
    # ОПТИМИЗАЦИЯ: ПАРАЛЛЕЛЬНАЯ ГЕНЕРАЦИЯ ССЫЛОК
    # ========================================================================
    
    async def generate_link_for_inbound(host, client, server_config_dict, server_id, public_config, inbound_id, client_uuid, hysteria_username):
        """Асинхронная функция для генерации ссылки для одного inbound"""
        try:
            # Получаем inbound (оборачиваем синхронный вызов для параллельного выполнения)
            inbound = await asyncio.to_thread(client.get_inbound, inbound_id)
            if not inbound:
                logger.debug(f"Inbound {inbound_id} not found on server {server_id}, skipping")
                return None
            
            # Извлекаем network для логирования
            stream_settings = inbound.get('stream_settings') or inbound.get('streamSettings')
            if stream_settings and isinstance(stream_settings, dict):
                network = stream_settings.get('network', 'unknown')
            else:
                network = 'unknown'
            
            logger.debug(
                f"Inbound {inbound_id}: protocol={inbound.get('protocol')}, "
                f"network={network}, remark={inbound.get('remark', 'N/A')}"
            )
            
            # Формируем имя для ссылки
            inbound_remark = inbound.get('remark', '')
            name = inbound_remark.strip() if inbound_remark else f"Inbound {inbound_id}"
            
            # Быстрый путь: пробуем собрать ссылку напрямую из streamSettings
            uri = None
            try:
                uri = build_public_vless_link(
                    client_uuid=client_uuid,
                    inbound=inbound,
                    server_config=public_config,
                    remark=name
                )
                if uri:
                    logger.debug(f"Inbound {inbound_id}: Using fast generator (network={network})")
            except Exception as e:
                logger.debug(f"Inbound {inbound_id}: Fast generator failed, will try share_link: {e}")
            
            # Если быстрый путь не сработал — пробуем share link из 3X-UI
            # Используем async версию напрямую для лучшей производительности
            try:
                if not uri:
                    # Используем async версию если доступна
                    if hasattr(client, '_get_client_share_link_async'):
                        share_link = await client._get_client_share_link_async(
                            inbound_id=inbound_id,
                            uuid=client_uuid
                        )
                    else:
                        # Fallback к синхронной версии через to_thread
                        share_link = await asyncio.to_thread(
                            client.get_client_share_link,
                            inbound_id,
                            client_uuid
                        )
                    if share_link:
                        # Обновляем fragment на наше имя для единообразия
                        if name:
                            base = share_link.split('#', 1)[0]
                            uri = f"{base}#{quote(name, safe='')}"
                        else:
                            uri = share_link
                        try:
                            parsed = urlparse(share_link)
                            share_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                            share_type = (share_params.get('type') or '').strip().lower()
                            if share_type:
                                network = share_type
                        except Exception:
                            pass
                        logger.debug(f"Inbound {inbound_id}: Using share_link from 3X-UI (network={network})")
            except Exception as e:
                logger.debug(f"Inbound {inbound_id}: get_client_share_link failed, fallback to generator: {e}")
            
            if uri:
                return {
                    "name": name,
                    "uri": uri,
                    "server_id": server_id,
                    "inbound_id": inbound_id,
                    "network": network,
                    "public_host": public_config.public_host,
                    "public_port": public_config.public_port,
                    "server_config": {
                        "name": server_id,
                        "host": host,
                        "public_host": public_config.public_host,
                        "public_port": public_config.public_port,
                        "sni": public_config.sni,
                        "link_host_rewrite_from": server_config_dict.get("link_host_rewrite_from", "127.0.0.1"),
                        "xhttp_alpn": public_config.xhttp_alpn,
                        "xhttp_fp": public_config.xhttp_fp,
                        "xhttp_mode": public_config.xhttp_mode,
                        "grpc_authority": public_config.grpc_authority
                    }
                }
            else:
                logger.warning(
                    f"⚠️  Failed to generate link for user {hysteria_username}: "
                    f"server={server_id}, inbound={inbound_id}, network={network}"
                )
                return None
        except Exception as e:
            logger.error(
                f"Error generating link for inbound {inbound_id} on server {server_id}: {e}",
                exc_info=True
            )
            return None
    
    async def process_server(host, client, server_config_dict):
        """Асинхронная функция для обработки одного сервера"""
        server_id = server_config_dict.get('name')
        if not server_id:
            try:
                parsed = urlparse(host)
                server_id = parsed.hostname or host
            except:
                server_id = host
        
        # Получаем публичную конфигурацию сервера
        public_config = server_configs.get(server_id)
        if not public_config:
            try:
                parsed = urlparse(host)
                hostname = parsed.hostname
                if hostname and hostname in server_configs:
                    public_config = server_configs[hostname]
                    logger.debug(f"Found server config by hostname fallback: {hostname}")
            except:
                pass
        
        if not public_config:
            logger.warning(
                f"Server {server_id} (host={host}) not found in server_configs. "
                f"Available: {list(server_configs.keys())}."
            )
            return []
        
        # Получаем список inbounds для этого сервера
        try:
            inbound_ids_for_server = xui_sync_manager._get_inbound_ids(client, server_config_dict)
            logger.info(
                f"Processing {len(inbound_ids_for_server)} inbounds for user {hysteria_username} "
                f"on server {server_id}"
            )
            
            # Параллельная генерация ссылок для всех inbounds на этом сервере
            tasks = [
                generate_link_for_inbound(
                    host, client, server_config_dict, server_id, public_config,
                    inbound_id, client_uuid, hysteria_username
                )
                for inbound_id in inbound_ids_for_server
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Собираем успешные результаты
            server_links = []
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Error in parallel link generation: {result}", exc_info=True)
                elif result:
                    server_links.append(result)
                    logger.info(
                        f"✅ Generated link for user {hysteria_username}: "
                        f"server={result['server_id']}, inbound={result['inbound_id']}, network={result['network']}"
                    )
            
            return server_links
        except Exception as e:
            logger.error(f"Error processing server {server_id}: {e}", exc_info=True)
            return []
    
    # Параллельная обработка всех серверов
    async def process_all_servers():
        tasks = [
            process_server(host, client, server_config_dict)
            for host, client, server_config_dict in servers_for_plan
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Собираем все ссылки
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error processing server: {result}", exc_info=True)
            elif isinstance(result, list):
                links.extend(result)
    
    # Запускаем параллельное выполнение
    try:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    loop.run_until_complete(process_all_servers())
                except ImportError:
                    logger.warning("nest_asyncio not available, falling back to sequential execution")
                    raise RuntimeError("No event loop available")
            else:
                loop.run_until_complete(process_all_servers())
        except RuntimeError:
            asyncio.run(process_all_servers())
    except Exception as e:
        logger.error(f"Error in parallel link generation: {e}, falling back to sequential", exc_info=True)
        # Fallback к последовательному выполнению
        for host, client, server_config_dict in servers_for_plan:
            server_id = server_config_dict.get('name')
            if not server_id:
                try:
                    parsed = urlparse(host)
                    server_id = parsed.hostname or host
                except:
                    server_id = host
            
            public_config = server_configs.get(server_id)
            if not public_config:
                continue
            
            try:
                inbound_ids_for_server = xui_sync_manager._get_inbound_ids(client, server_config_dict)
                for inbound_id in inbound_ids_for_server:
                    try:
                        inbound = client.get_inbound(inbound_id)
                        if not inbound:
                            continue
                        
                        stream_settings = inbound.get('stream_settings') or inbound.get('streamSettings')
                        network = stream_settings.get('network', 'unknown') if stream_settings and isinstance(stream_settings, dict) else 'unknown'
                        inbound_remark = inbound.get('remark', '')
                        name = inbound_remark.strip() if inbound_remark else f"Inbound {inbound_id}"
                        
                        uri = None
                        try:
                            uri = build_public_vless_link(client_uuid, inbound, public_config, name)
                        except:
                            pass
                        
                        if not uri:
                            try:
                                share_link = client.get_client_share_link(inbound_id, client_uuid)
                                if share_link:
                                    if name:
                                        base = share_link.split('#', 1)[0]
                                        uri = f"{base}#{quote(name, safe='')}"
                                    else:
                                        uri = share_link
                            except:
                                pass
                        
                        if uri:
                            links.append({
                                "name": name,
                                "uri": uri,
                                "server_id": server_id,
                                "inbound_id": inbound_id,
                                "network": network,
                                "public_host": public_config.public_host,
                                "public_port": public_config.public_port,
                                "server_config": {
                                    "name": server_id,
                                    "host": host,
                                    "public_host": public_config.public_host,
                                    "public_port": public_config.public_port,
                                    "sni": public_config.sni,
                                    "link_host_rewrite_from": server_config_dict.get("link_host_rewrite_from", "127.0.0.1"),
                                    "xhttp_alpn": public_config.xhttp_alpn,
                                    "xhttp_fp": public_config.xhttp_fp,
                                    "xhttp_mode": public_config.xhttp_mode,
                                    "grpc_authority": public_config.grpc_authority
                                }
                            })
                    except Exception as e:
                        logger.warning(f"Error generating link for inbound {inbound_id}: {e}")
            except Exception as e:
                logger.warning(f"Error processing server {server_id}: {e}")
    
    if links:
        logger.info(
            f"✅ Generated {len(links)} total VLESS links for user {hysteria_username} "
            f"across {len(servers_for_plan)} servers"
        )
    else:
        logger.warning(
            f"⚠️ No VLESS links generated for user {hysteria_username}. "
            f"Servers checked: {len(servers_for_plan)}, "
            f"Server configs available: {list(server_configs.keys())}"
        )
    
    return links


def load_server_public_configs(xui_config: Dict[str, Any]) -> Dict[str, XUIServerPublicConfig]:
    """
    Загружает публичные конфигурации серверов из конфигурации X-UI.
    
    Args:
        xui_config: Конфигурация X-UI (из load_xui_config())
        
    Returns:
        Словарь {server_id: XUIServerPublicConfig}
    """
    
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
            xhttp_alpn=server.get('xhttp_alpn'),
            xhttp_fp=server.get('xhttp_fp'),
            xhttp_mode=server.get('xhttp_mode'),
            grpc_authority=server.get('grpc_authority')
        )
        
        configs[server_id] = public_config
        logger.debug(
            f"Loaded public config for server {server_id}: "
            f"{public_config.public_host}:{public_config.public_port}, "
            f"sni={public_config.sni}"
        )
    
    return configs
