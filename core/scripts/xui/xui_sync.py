#!/usr/bin/env python3
"""
Модуль синхронизации пользователей Hysteria2 с X-UI/3X-UI.
"""

import logging
import uuid as uuid_lib
import sys
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta

# Добавляем путь к модулям для импорта
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import db
from xui.xui_api_wrapper import XUIAPIWrapper
from xui.xui_api_client import XUIAPIError, XUIAPIAuthError, XUIAPIConnectionError
from xui.xui_public_links import (
    build_user_public_links,
    load_server_public_configs,
    XUIServerPublicConfig
)

# Для обратной совместимости
XUIClient = XUIAPIWrapper
XUIClientError = XUIAPIError

logger = logging.getLogger(__name__)


class XUISyncError(Exception):
    """Ошибка синхронизации с X-UI"""
    pass


class XUISyncConfig:
    """Конфигурация синхронизации X-UI"""
    
    def __init__(self, config_dict: Dict[str, Any]):
        """
        Инициализация конфигурации.
        
        Args:
            config_dict: Словарь с настройками:
                - enabled: bool - включена ли синхронизация
                - mode: str - "single-xui" или "multi-xui"
                - xui_servers: List[Dict] - список серверов X-UI
                  Каждый сервер: {host, username, password, base_path, plans, inbound_filter}
                  - plans: List[str] - список планов для этого сервера (["standard"], ["premium"], ["standard", "premium"])
                - inbound_filter: Dict - фильтр inbounds (protocol, tag, remark)
        """
        self.enabled = config_dict.get('enabled', False)
        self.mode = config_dict.get('mode', 'single-xui')
        self.xui_servers = config_dict.get('xui_servers', [])
        self.inbound_filter = config_dict.get('inbound_filter', {})
        
        # Валидация и нормализация планов для серверов
        for server in self.xui_servers:
            plans = server.get('plans', [])
            if not plans:
                # Если планы не указаны, сервер доступен для всех планов
                server['plans'] = ['standard', 'premium']
            else:
                # Нормализуем планы
                normalized_plans = []
                for plan in plans:
                    plan_lower = str(plan).lower().strip()
                    if plan_lower in ('standard', 'premium'):
                        normalized_plans.append(plan_lower)
                server['plans'] = normalized_plans if normalized_plans else ['standard', 'premium']
        
        # Валидация
        if self.enabled:
            if not self.xui_servers:
                raise ValueError("X-UI servers must be configured when sync is enabled")
            if self.mode not in ('single-xui', 'multi-xui'):
                raise ValueError(f"Invalid mode: {self.mode}")


class XUISyncManager:
    """Менеджер синхронизации пользователей с X-UI"""
    
    def __init__(self, config: XUISyncConfig):
        """
        Инициализация менеджера синхронизации.
        
        Args:
            config: Конфигурация синхронизации
        """
        self.config = config
        self.clients: Dict[str, XUIClient] = {}
        
        # Инициализируем клиенты для каждого сервера
        if config.enabled:
            for server in config.xui_servers:
                host = server.get('host')
                if not host:
                    continue
                
                # Проверяем авторизацию в зависимости от auth_type
                auth_type = server.get('auth_type', 'username')
                username = server.get('username')
                password = server.get('password')
                
                if auth_type == 'token':
                    if not password:
                        logger.warning(f"Server {host} skipped: token is required when auth_type=token")
                        continue
                    username = 'admin'  # Заглушка для py3xui
                else:
                    if not username or not password:
                        logger.warning(f"Server {host} skipped: username and password are required when auth_type=username")
                        continue
                
                client = XUIClient(
                    host=host,
                    username=username,
                    password=password,
                    base_path=server.get('base_path', '/'),
                    timeout=server.get('timeout', 10),
                    max_retries=server.get('max_retries', 3),
                    verify_ssl=server.get('verify_ssl', True),
                    force_https=server.get('force_https', True)
                )
                
                # Используем host как ключ
                self.clients[host] = client
    
    def _get_inbound_ids(self, client: XUIAPIWrapper, server_config: Optional[Dict] = None) -> List[int]:
        """
        Получает список ID inbounds согласно фильтру.
        
        Args:
            client: Клиент X-UI
            server_config: Конфигурация сервера (для получения фильтра inbounds сервера)
        
        Returns:
            Список ID inbounds
        """
        try:
            inbounds = client.list_inbounds()
            logger.debug(f"_get_inbound_ids: Found {len(inbounds)} total inbounds")
            
            # Используем фильтр сервера или глобальный фильтр
            inbound_filter = server_config.get('inbound_filter', {}) if server_config else {}
            if not inbound_filter:
                inbound_filter = self.config.inbound_filter
            
            # Применяем фильтр
            filter_protocol = inbound_filter.get('protocol')
            filter_tag = inbound_filter.get('tag')
            filter_remark = inbound_filter.get('remark')
            
            logger.debug(f"_get_inbound_ids: Filter - protocol={filter_protocol}, tag={filter_tag}, remark={filter_remark}")
            
            filtered = client.filter_inbounds(
                protocol=filter_protocol,
                tag=filter_tag,
                remark=filter_remark
            )
            
            # Если фильтр не задан, используем все VLESS inbounds
            if not any([filter_protocol, filter_tag, filter_remark]):
                filtered = [i for i in inbounds if i.get('protocol', '').lower() == 'vless']
                logger.debug(f"_get_inbound_ids: No filter specified, using all VLESS inbounds: {len(filtered)} found")
            
            # Логируем информацию о каждом отфильтрованном inbound
            inbound_ids = []
            for inbound in filtered:
                inbound_id = inbound.get('id')
                if inbound_id:
                    inbound_ids.append(inbound_id)
                    inbound_protocol = inbound.get('protocol', 'unknown')
                    inbound_remark = inbound.get('remark', 'no remark')
                    inbound_stream_settings = inbound.get('stream_settings', {})
                    inbound_network = inbound_stream_settings.get('network', 'unknown') if isinstance(inbound_stream_settings, dict) else 'unknown'
                    logger.info(
                        f"_get_inbound_ids: Selected inbound {inbound_id}: "
                        f"protocol={inbound_protocol}, network={inbound_network}, remark={inbound_remark}"
                    )
            
            logger.info(f"_get_inbound_ids: Returning {len(inbound_ids)} inbound IDs: {inbound_ids}")
            return inbound_ids
        
        except Exception as e:
            logger.error(f"Failed to get inbound IDs: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return []
    
    def _get_servers_for_plan(self, user_plan: str) -> List[Tuple[str, XUIAPIWrapper, Dict]]:
        """
        Получает список серверов X-UI для указанного плана пользователя.
        
        Args:
            user_plan: План пользователя ("standard" или "premium")
        
        Returns:
            Список кортежей (host, client, server_config)
        """
        user_plan = str(user_plan).lower().strip()
        if user_plan not in ('standard', 'premium'):
            user_plan = 'standard'
        
        result = []
        for server_config in self.config.xui_servers:
            server_plans = server_config.get('plans', ['standard', 'premium'])
            if user_plan in server_plans:
                host = server_config.get('host')
                if host and host in self.clients:
                    result.append((host, self.clients[host], server_config))
        
        return result

    def _build_link_rewriter_config(
        self,
        server_config: Dict[str, Any],
        server_id: str,
        host: Optional[str] = None
    ):
        """Создает конфиг LinkRewriter для указанного X-UI сервера."""
        if not server_config:
            return None
        public_host = server_config.get('public_host')
        if not public_host:
            host_url = server_config.get('host') or host
            if host_url:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(host_url)
                    public_host = parsed.hostname or host_url
                except Exception:
                    public_host = host_url
        if not public_host:
            return None
        
        sni = server_config.get('sni') or public_host
        
        from link_rewriter import XuiServerConfig as LinkRewriterServerConfig
        return LinkRewriterServerConfig(
            server_id=server_id,
            public_host=public_host,
            public_port=server_config.get('public_port', 443),
            link_host_rewrite_from=server_config.get('link_host_rewrite_from', '127.0.0.1'),
            sni=sni,
            xhttp_alpn=server_config.get('xhttp_alpn'),
            xhttp_fp=server_config.get('xhttp_fp'),
            xhttp_mode=server_config.get('xhttp_mode'),
            grpc_authority=server_config.get('grpc_authority')
        )

    def _normalize_xui_links(self, links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Нормализует VLESS ссылки через LinkRewriter с учетом контекста сервера."""
        if not links:
            return links
        try:
            from link_rewriter import rewrite_proxy_links
        except Exception as e:
            logger.warning(f"LinkRewriter import failed: {e}")
            return links
        
        for item in links:
            uri = item.get('uri')
            if not uri:
                logger.debug(f"Skipping item with empty URI: {item.get('name', 'unknown')}")
                continue
            server_config = item.get('server_config', {}) or {}
            server_id = (
                item.get('server_id')
                or server_config.get('name')
                or server_config.get('host')
                or 'unknown'
            )
            server_cfg = self._build_link_rewriter_config(server_config, server_id, server_config.get('host'))
            if not server_cfg:
                # Если нет конфигурации для нормализации, оставляем ссылку как есть (без нормализации)
                logger.debug(f"No server config for {server_id}, keeping link as-is: {uri[:80]}...")
                # НЕ используем continue - ссылка должна остаться в списке даже без нормализации
            try:
                normalized = rewrite_proxy_links(uri, server_cfg)
                if normalized:
                    item['uri'] = normalized
                    logger.debug(f"Normalized link for server {server_id}")
                else:
                    logger.warning(f"rewrite_proxy_links returned None for server {server_id}, keeping original")
            except Exception as e:
                logger.warning(f"Failed to normalize link for server {server_id}: {e}", exc_info=True)
                # При ошибке оставляем оригинальную ссылку
        
        return links
    
    def _save_links_to_normalsub_cache(
        self, 
        hysteria_username: str, 
        user_plan: str, 
        links: List[Dict[str, Any]]
    ) -> bool:
        """
        Сохраняет ссылки напрямую в файл кэша normalsub.
        
        Это позволяет мгновенно выдавать подписку при первом запросе,
        так как ссылки уже будут в кэше.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
            user_plan: План пользователя (standard/premium)
            links: Список ссылок для сохранения
            
        Returns:
            True если сохранение успешно, False иначе
        """
        import os
        import json
        import time
        
        cache_path = os.environ.get('XUI_LINKS_CACHE_PATH', '/etc/hysteria/xui_links_cache.json')
        cache_key = f"{hysteria_username}:{user_plan}"
        
        try:
            # Читаем существующий кэш
            cache_data = {}
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Failed to read existing cache: {e}")
                    cache_data = {}
            
            # Добавляем/обновляем запись
            cache_data[cache_key] = {
                "timestamp": time.time(),
                "links": links
            }
            
            # Сохраняем кэш атомарно
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            tmp_path = f"{cache_path}.tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False)
            os.replace(tmp_path, cache_path)
            
            logger.debug(f"Saved {len(links)} links to normalsub cache for {cache_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save links to normalsub cache: {e}", exc_info=True)
            return False
    
    def _generate_client_uuid(self, hysteria_username: str) -> str:
        """
        Генерирует UUID для клиента X-UI на основе имени пользователя Hysteria2.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
        
        Returns:
            UUID строка
        """
        # Используем детерминированный UUID на основе имени пользователя
        # Это позволяет восстанавливать маппинг при перезапуске
        namespace = uuid_lib.UUID('6ba7b810-9dad-11d1-80b4-00c04fd430c8')
        return str(uuid_lib.uuid5(namespace, hysteria_username.lower()))
    
    def _convert_expiry_days_to_timestamp(self, expiry_days: int) -> Optional[int]:
        """
        Конвертирует дни до истечения в timestamp в миллисекундах.
        
        Args:
            expiry_days: Количество дней до истечения
        
        Returns:
            Timestamp в миллисекундах или None если неограниченно
        """
        if expiry_days <= 0:
            return None
        
        expiry_date = datetime.utcnow() + timedelta(days=expiry_days)
        return int(expiry_date.timestamp() * 1000)
    
    def _convert_traffic_gb_to_bytes(self, traffic_gb: float) -> Optional[int]:
        """
        Конвертирует лимит трафика из GB в байты.
        
        Args:
            traffic_gb: Лимит трафика в GB (может быть float или int)
        
        Returns:
            Лимит в байтах или None если неограниченно (traffic_gb <= 0)
        """
        # Нормализуем входное значение
        try:
            traffic_gb_float = float(traffic_gb)
        except (ValueError, TypeError):
            logger.warning(f"Invalid traffic_gb value: {traffic_gb}, treating as unlimited")
            return None
        
        if traffic_gb_float <= 0:
            return None
        
        # Конвертируем в байты
        bytes_value = int(traffic_gb_float * (1024 ** 3))
        logger.debug(f"Converted {traffic_gb_float} GB to {bytes_value} bytes")
        return bytes_value
    
    def sync_user_create(
        self,
        hysteria_username: str,
        expiry_days: int,
        traffic_limit_gb: float,
        enable: bool = True,
        user_plan: str = "standard"
    ) -> Tuple[bool, Optional[str]]:
        """
        Синхронизирует создание пользователя с X-UI.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
            expiry_days: Дни до истечения
            traffic_limit_gb: Лимит трафика в GB
            enable: Включен ли пользователь
        
        Returns:
            Tuple (success: bool, error_message: Optional[str])
        """
        if not self.config.enabled:
            return True, None
        
        if not db:
            return False, "Database not available"
        
        # Проверяем, есть ли уже маппинг
        existing_mapping = db.get_xui_mapping(hysteria_username)
        if existing_mapping:
            # Пользователь уже синхронизирован - используем upsert для безопасного обновления
            logger.info(f"User {hysteria_username} already has X-UI mapping, using upsert...")
            # Используем sync_user_update, который внутри использует upsert_client
            return self.sync_user_update(
                hysteria_username=hysteria_username,
                expiry_days=expiry_days,
                traffic_limit_gb=traffic_limit_gb,
                enable=enable,
                user_plan=user_plan
            )
        
        # Генерируем UUID
        client_uuid = self._generate_client_uuid(hysteria_username)
        
        # Конвертируем параметры
        expiry_timestamp = self._convert_expiry_days_to_timestamp(expiry_days)
        traffic_bytes = self._convert_traffic_gb_to_bytes(traffic_limit_gb)
        
        # Логируем для отладки конвертации трафика
        logger.info(
            f"Creating user {hysteria_username}: "
            f"traffic_limit_gb={traffic_limit_gb} (type: {type(traffic_limit_gb).__name__}), "
            f"traffic_bytes={traffic_bytes}, "
            f"traffic_gb_calculated={traffic_bytes / (1024 ** 3) if traffic_bytes else 0:.3f}"
        )
        
        all_inbound_ids = []
        errors = []
        
        # Нормализуем план пользователя
        user_plan = str(user_plan).lower().strip()
        if user_plan not in ('standard', 'premium'):
            user_plan = 'standard'
        
        # Получаем серверы для плана пользователя
        servers_for_plan = self._get_servers_for_plan(user_plan)
        
        if not servers_for_plan:
            logger.warning(f"No X-UI servers configured for plan '{user_plan}'")
            errors.append(f"No X-UI servers available for plan '{user_plan}'")
        
        # Оптимизация: параллельное создание клиентов на всех серверах и inbounds
        
        async def upsert_client_async(host, client, server_config, inbound_id):
            """Асинхронная функция для создания клиента в одном inbound"""
            try:
                logger.debug(f"Upserting client {client_uuid} to inbound {inbound_id} on {host} with email {hysteria_username}_{inbound_id}")
                
                # ВАЖНО: Проверяем что traffic_bytes действительно в байтах
                if traffic_bytes is not None and traffic_bytes < (1024 ** 3):
                    logger.error(
                        f"ERROR: traffic_bytes={traffic_bytes} seems too small! "
                        f"Expected bytes (e.g., 32212254720 for 30 GB), got {traffic_bytes}. "
                        f"traffic_limit_gb was {traffic_limit_gb}"
                    )
                
                # Используем async версию upsert_client для параллельного выполнения
                is_updated, action = await client._upsert_client_async(
                    inbound_id=inbound_id,
                    uuid=client_uuid,
                    expiry_time=expiry_timestamp,
                    traffic_limit=traffic_bytes,  # Должно быть в БАЙТАХ!
                    enable=enable,
                    email=f"{hysteria_username}_{inbound_id}",
                    username=hysteria_username
                )
                logger.info(
                    f"Successfully {action} client {client_uuid} (email: {hysteria_username}_{inbound_id}) in inbound {inbound_id} "
                    f"on server {host}"
                )
                return (True, inbound_id, host, None)
            except XUIClientError as e:
                error_msg = f"Failed to upsert client to inbound {inbound_id} on {host}: {e}"
                logger.error(error_msg, exc_info=True)
                return (False, inbound_id, host, error_msg)
            except Exception as e:
                error_msg = f"Unexpected error upserting client to inbound {inbound_id} on {host}: {e}"
                logger.error(error_msg, exc_info=True)
                return (False, inbound_id, host, error_msg)
        
        async def sync_server_async(host, client, server_config):
            """Асинхронная функция для синхронизации с одним сервером"""
            try:
                logger.info(f"Syncing user {hysteria_username} with server {host}")
                # Получаем список inbounds для этого сервера
                inbound_ids = self._get_inbound_ids(client, server_config)
                
                if not inbound_ids:
                    logger.warning(f"No inbounds found for server {host}")
                    return (False, host, f"No inbounds found on {host}")
                
                logger.info(f"Found {len(inbound_ids)} inbounds on server {host}: {inbound_ids}")
                
                # Параллельное создание клиентов во всех inbounds на этом сервере
                tasks = [
                    upsert_client_async(host, client, server_config, inbound_id)
                    for inbound_id in inbound_ids
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Обрабатываем результаты
                for result in results:
                    if isinstance(result, Exception):
                        error_msg = f"Unexpected error on {host}: {result}"
                        logger.error(error_msg, exc_info=True)
                        errors.append(error_msg)
                    else:
                        success, inbound_id, result_host, error = result
                        if success:
                            all_inbound_ids.append(inbound_id)
                        elif error:
                            errors.append(error)
                
                return (True, host, None)
            except (XUIAuthError, XUIConnectionError) as e:
                error_msg = f"Failed to connect to X-UI server {host}: {e}"
                logger.error(error_msg)
                return (False, host, error_msg)
            except Exception as e:
                error_msg = f"Unexpected error syncing with {host}: {e}"
                logger.error(error_msg)
                return (False, host, error_msg)
        
        # Параллельное создание клиентов на всех серверах
        async def sync_all_servers():
            tasks = [
                sync_server_async(host, client, server_config)
                for host, client, server_config in servers_for_plan
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    error_msg = f"Unexpected error: {result}"
                    logger.error(error_msg, exc_info=True)
                    errors.append(error_msg)
                else:
                    success, host, error = result
                    if error:
                        errors.append(error)
        
        # Запускаем параллельное выполнение
        # Используем nest_asyncio если уже есть event loop
        try:
            # Пробуем получить существующий event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Если loop уже запущен, используем nest_asyncio
                    try:
                        import nest_asyncio
                        nest_asyncio.apply()
                        loop.run_until_complete(sync_all_servers())
                    except ImportError:
                        logger.warning("nest_asyncio not available, falling back to sequential execution")
                        raise RuntimeError("No event loop available")
                else:
                    # Loop существует, но не запущен
                    loop.run_until_complete(sync_all_servers())
            except RuntimeError:
                # Нет event loop, создаем новый
                asyncio.run(sync_all_servers())
        except Exception as e:
            logger.error(f"Error in parallel sync: {e}, falling back to sequential execution", exc_info=True)
            # Fallback к последовательному выполнению
            for host, client, server_config in servers_for_plan:
                try:
                    logger.info(f"Syncing user {hysteria_username} with server {host}")
                    inbound_ids = self._get_inbound_ids(client, server_config)
                    if not inbound_ids:
                        logger.warning(f"No inbounds found for server {host}")
                        errors.append(f"No inbounds found on {host}")
                        continue
                    logger.info(f"Found {len(inbound_ids)} inbounds on server {host}: {inbound_ids}")
                    for inbound_id in inbound_ids:
                        try:
                            is_updated, action = client.upsert_client(
                                inbound_id=inbound_id,
                                uuid=client_uuid,
                                expiry_time=expiry_timestamp,
                                traffic_limit=traffic_bytes,
                                enable=enable,
                                username=hysteria_username
                            )
                            all_inbound_ids.append(inbound_id)
                            logger.info(f"Successfully {action} client {client_uuid} in inbound {inbound_id} on server {host}")
                        except Exception as e:
                            error_msg = f"Failed to upsert client to inbound {inbound_id} on {host}: {e}"
                            logger.error(error_msg, exc_info=True)
                            errors.append(error_msg)
                except Exception as e:
                    error_msg = f"Unexpected error syncing with {host}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
        
        # Сохраняем маппинг
        sync_status = "success" if not errors else "failed"
        error_message = "; ".join(errors) if errors else None
        
        # Для multi-xui режима сохраняем host первого сервера
        xui_host = list(self.clients.keys())[0] if self.clients else None
        
        db.save_xui_mapping(
            hysteria_username=hysteria_username,
            xui_client_uuid=client_uuid,
            inbound_ids=all_inbound_ids,
            xui_host=xui_host,
            sync_status=sync_status,
            error_message=error_message
        )
        
        # Предзагружаем ссылки в кэш normalsub для мгновенной выдачи подписки
        # Делаем СИНХРОННО, чтобы при первом запросе подписки ссылки уже были готовы
        if not errors:
            try:
                logger.info(f"Pre-loading links for user {hysteria_username} (plan: {user_plan}) into normalsub cache...")
                links = self.get_user_vless_uris(hysteria_username)
                logger.debug(f"Pre-loading: get_user_vless_uris returned {len(links) if links else 0} links")
                if links:
                    # Сохраняем в файл кэша normalsub
                    success = self._save_links_to_normalsub_cache(hysteria_username, user_plan, links)
                    if success:
                        logger.info(f"Pre-loaded {len(links)} links for user {hysteria_username} into normalsub cache")
                    else:
                        logger.warning(f"Failed to save links to cache for {hysteria_username}")
                else:
                    logger.warning(f"No links generated for user {hysteria_username} during pre-loading - check X-UI configuration")
            except Exception as e:
                logger.error(f"Pre-loading failed for {hysteria_username}: {e}", exc_info=True)
        
        if errors:
            return False, error_message
        
        return True, None
    
    def sync_user_update(
        self,
        hysteria_username: str,
        expiry_days: Optional[int] = None,
        traffic_limit_gb: Optional[int] = None,
        enable: Optional[bool] = None,
        user_plan: Optional[str] = None,
        replace_devices: bool = False,
        replace_duration: bool = False,
        devices: Optional[int] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Синхронизирует обновление пользователя с X-UI.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
            expiry_days: Новые дни до истечения (None = не менять)
            traffic_limit_gb: Новый лимит трафика в GB (None = не менять)
            enable: Новый статус включения (None = не менять)
            user_plan: План пользователя (None = не менять)
            replace_devices: Если True, заменяет лимит устройств вместо добавления
            replace_duration: Если True, заменяет срок действия вместо продления
            devices: Новый лимит устройств (используется только если replace_devices=True)
        
        Returns:
            Tuple (success: bool, error_message: Optional[str])
        """
        if not self.config.enabled:
            return True, None
        
        if not db:
            return False, "Database not available"
        
        # Получаем маппинг
        mapping = db.get_xui_mapping(hysteria_username)
        if not mapping:
            # Маппинга нет - создаем
            logger.info(f"No mapping found for {hysteria_username}, creating...")
            # Нужны базовые параметры пользователя
            user_data = db.get_user(hysteria_username)
            if not user_data:
                return False, "User not found in Hysteria2"
            
            expiry_days = expiry_days or user_data.get('expiration_days', 0)
            traffic_limit_gb = traffic_limit_gb or (user_data.get('max_download_bytes', 0) / (1024 ** 3))
            enable = enable if enable is not None else not user_data.get('blocked', False)
            plan_for_create = user_plan or user_data.get('plan', 'standard')
            
            return self.sync_user_create(hysteria_username, expiry_days, int(traffic_limit_gb), enable, plan_for_create)
        
        client_uuid = mapping.get('xui_client_uuid')
        inbound_ids = mapping.get('inbound_ids', [])
        xui_host = mapping.get('xui_host')
        
        if not client_uuid:
            return False, "No client UUID in mapping"
        
        # Конвертируем параметры
        expiry_timestamp = None
        if expiry_days is not None:
            if replace_duration:
                # Заменяем срок действия - используем текущее время + новые дни
                expiry_timestamp = self._convert_expiry_days_to_timestamp(expiry_days)
            else:
                # Продлеваем срок действия - получаем текущий срок и добавляем дни
                # Нужно получить текущий клиент для определения текущего expiry_time
                user_data = db.get_user(hysteria_username)
                if user_data:
                    # Пытаемся получить текущий expiry_time из X-UI
                    # Если не удалось, используем текущее время
                    current_time = datetime.utcnow()
                    expiry_timestamp = int((current_time + timedelta(days=expiry_days)).timestamp() * 1000)
                else:
                    expiry_timestamp = self._convert_expiry_days_to_timestamp(expiry_days)
        elif not replace_duration:
            # Если не указаны дни и не replace_duration, пытаемся получить текущий срок
            # и продлить его (но это требует получения данных из X-UI, что сложно)
            # Пока просто не меняем срок
            pass
        
        traffic_bytes = None
        if traffic_limit_gb is not None:
            traffic_bytes = self._convert_traffic_gb_to_bytes(traffic_limit_gb)
        
        errors = []
        
        # Определяем план пользователя
        if user_plan is None:
            user_data = db.get_user(hysteria_username)
            if user_data:
                user_plan = user_data.get('plan', 'standard')
            else:
                user_plan = 'standard'
        
        user_plan = str(user_plan).lower().strip()
        if user_plan not in ('standard', 'premium'):
            user_plan = 'standard'
        
        # Получаем серверы для плана пользователя
        servers_for_plan = self._get_servers_for_plan(user_plan)
        
        # Если есть старый маппинг с другим хостом, используем его для обратной совместимости
        if xui_host and xui_host in self.clients:
            # Проверяем, доступен ли старый сервер для текущего плана
            old_server_available = any(
                s[0] == xui_host for s in servers_for_plan
            )
            if not old_server_available and self.config.mode == 'single-xui':
                # В single-xui режиме обновляем на старом сервере для совместимости
                servers_for_plan = [(xui_host, self.clients[xui_host], {})]
        
        # Обновляем на каждом сервере для плана
        updated_inbound_ids = set(inbound_ids) if inbound_ids else set()
        
        for host, client, server_config in servers_for_plan:
            # Получаем актуальные inbounds для этого сервера
            server_inbound_ids = self._get_inbound_ids(client, server_config)
            
            for inbound_id in server_inbound_ids:
                try:
                    # Если нужно заменить лимит устройств, получаем текущий клиент
                    limit_ip = None
                    if devices is not None:
                        if replace_devices:
                            # Заменяем лимит устройств
                            limit_ip = devices
                        else:
                            # Добавляем к текущему лимиту (требует получения текущего клиента)
                            # Пока просто устанавливаем новый лимит
                            limit_ip = devices
                    
                    # Используем upsert_client для правильной обработки существующих клиентов
                    is_updated, action = client.upsert_client(
                        inbound_id=inbound_id,
                        uuid=client_uuid,
                        expiry_time=expiry_timestamp,
                        traffic_limit=traffic_bytes,
                        enable=enable,
                        username=hysteria_username  # Используется для генерации email: username_inbound_id
                    )
                    
                    # Обновляем лимит устройств если указан
                    if limit_ip is not None:
                        # Получаем клиента для обновления limit_ip
                        # Это требует дополнительной логики в XUIClient
                        # Пока пропускаем, так как upsert_client не поддерживает limit_ip напрямую
                        logger.debug(f"limit_ip update requested but not yet implemented in upsert_client")
                    updated_inbound_ids.add(inbound_id)  # Добавляем в список обновленных
                    logger.info(
                        f"{action.capitalize()} client {client_uuid} (email: {hysteria_username}_{inbound_id}) in inbound {inbound_id} "
                        f"on server {host}"
                    )
                except XUIClientError as e:
                    error_msg = f"Failed to upsert client in inbound {inbound_id} on {host}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                except (XUIAuthError, XUIConnectionError) as e:
                    error_msg = f"Failed to connect to X-UI server {host}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
        
        # Обновляем маппинг со всеми inbound_ids (включая новые)
        sync_status = "success" if not errors else "failed"
        error_message = "; ".join(errors) if errors else None
        
        db.save_xui_mapping(
            hysteria_username=hysteria_username,
            xui_client_uuid=client_uuid,
            inbound_ids=list(updated_inbound_ids),  # Сохраняем все обновленные inbound_ids
            xui_host=xui_host,
            sync_status=sync_status,
            error_message=error_message
        )
        
        if errors:
            return False, error_message
        
        return True, None
    
    def sync_user_delete(self, hysteria_username: str) -> Tuple[bool, Optional[str]]:
        """
        Синхронизирует удаление пользователя с X-UI.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
        
        Returns:
            Tuple (success: bool, error_message: Optional[str])
        """
        if not self.config.enabled:
            return True, None
        
        if not db:
            return False, "Database not available"
        
        # Получаем маппинг
        mapping = db.get_xui_mapping(hysteria_username)
        if not mapping:
            # Маппинга нет - ничего делать не нужно
            return True, None
        
        client_uuid = mapping.get('xui_client_uuid')
        inbound_ids = mapping.get('inbound_ids', [])
        xui_host = mapping.get('xui_host')
        
        if not client_uuid:
            # Удаляем маппинг даже если UUID нет
            db.delete_xui_mapping(hysteria_username)
            return True, None
        
        errors = []
        
        # Удаляем с каждого сервера
        servers_to_update = [xui_host] if xui_host and self.config.mode == 'single-xui' else list(self.clients.keys())
        
        for host in servers_to_update:
            if host not in self.clients:
                continue
            
            client = self.clients[host]
            
            # Получаем актуальные inbounds если список пуст
            if not inbound_ids:
                inbound_ids = self._get_inbound_ids(client)
            
            for inbound_id in inbound_ids:
                try:
                    # Формируем email клиента (такой же формат, как при создании)
                    client_email = f"{hysteria_username}_{inbound_id}"
                    
                    logger.info(f"Attempting to delete client {client_uuid} (email: {client_email}) from inbound {inbound_id} on server {host}")
                    
                    # Пробуем удалить по UUID
                    result = client.delete_client(
                        inbound_id=inbound_id,
                        uuid=client_uuid
                    )
                    
                    if not result:
                        # Если не удалось по UUID, пробуем по email
                        logger.debug(f"Client not found by UUID {client_uuid}, trying email {client_email}")
                        result = client.delete_client(
                            inbound_id=inbound_id,
                            uuid=client_email  # Пробуем по email
                        )
                    
                    if result:
                        logger.info(
                            f"Successfully deleted client {client_uuid} (email: {client_email}) from inbound {inbound_id} "
                            f"on server {host}"
                        )
                    else:
                        # Клиент не найден - это не критично, возможно уже удален
                        logger.warning(f"Client {client_uuid} (email: {client_email}) not found in inbound {inbound_id} on {host} (may already be deleted)")
                except XUIClientError as e:
                    # Клиент может быть уже удален - это не критично
                    error_msg = str(e).lower()
                    if "not found" in error_msg or "not exist" in error_msg:
                        logger.warning(f"Client {client_uuid} not found in inbound {inbound_id} on {host} (may already be deleted)")
                    else:
                        error_msg_full = f"Failed to delete client from inbound {inbound_id} on {host}: {e}"
                        logger.error(error_msg_full)
                        errors.append(error_msg_full)
                except (XUIAuthError, XUIConnectionError) as e:
                    error_msg = f"Failed to connect to X-UI server {host}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                except Exception as e:
                    error_msg = f"Unexpected error deleting client from inbound {inbound_id} on {host}: {e}"
                    logger.error(error_msg, exc_info=True)
                    errors.append(error_msg)
        
        # Удаляем маппинг
        db.delete_xui_mapping(hysteria_username)
        
        if errors:
            return False, "; ".join(errors)
        
        return True, None
    
    def get_user_vless_uris(self, hysteria_username: str) -> List[Dict[str, Any]]:
        """
        Получает список публичных VLESS URIs для пользователя с учетом плана.
        
        Использует новый модуль xui_public_links для генерации публичных ссылок
        и пропускает их через LinkRewriter для нормализации.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
        
        Returns:
            Список словарей: [
                {
                    "name": "🇹🇷 Турция (Резерв)",
                    "uri": "vless://...",
                    "server_id": "server1",
                    "inbound_id": 1,
                    "network": "xhttp",
                    "public_host": "gateway1.example.com",
                    "public_port": 443
                },
                ...
            ]
        """
        if not self.config.enabled:
            return []
        
        if not db:
            return []
        
        # Авто-синхронизация при отсутствии маппинга (упрощение для пользователя)
        try:
            mapping = db.get_xui_mapping(hysteria_username)
            if not mapping:
                user_data = db.get_user(hysteria_username)
                if user_data:
                    plan = user_data.get('plan', 'standard')
                    expiry_days = user_data.get('expiration_days', 0)
                    traffic_bytes = user_data.get('max_download_bytes', 0)
                    traffic_gb = int(traffic_bytes / (1024 ** 3)) if traffic_bytes > 0 else 0
                    enable = not user_data.get('blocked', False)
                    logger.info(f"No X-UI mapping for {hysteria_username}, auto-syncing before link generation")
                    success, error = self.sync_user_create(
                        hysteria_username=hysteria_username,
                        expiry_days=expiry_days,
                        traffic_limit_gb=traffic_gb,
                        enable=enable,
                        user_plan=plan
                    )
                    if not success:
                        logger.warning(f"Auto-sync failed for {hysteria_username}: {error}")
        except Exception as e:
            logger.warning(f"Auto-sync skipped for {hysteria_username}: {e}")
        
        try:
            # Загружаем конфигурацию X-UI для получения публичных параметров серверов
            from xui.config import load_xui_config
            xui_config = load_xui_config()
            
            logger.debug(f"Loaded X-UI config: enabled={xui_config.get('enabled')}, servers={len(xui_config.get('xui_servers', []))}")
            
            # Загружаем публичные конфигурации серверов
            server_public_configs = load_server_public_configs(xui_config)
            
            logger.debug(f"Loaded {len(server_public_configs)} server public configs: {list(server_public_configs.keys())}")
            
            if not server_public_configs:
                logger.warning("No public server configs found, falling back to legacy method")
                return self._normalize_xui_links(self._get_user_vless_uris_legacy(hysteria_username))
            
            # Генерируем публичные ссылки через новый модуль
            logger.info(f"Generating public VLESS links for user {hysteria_username}")
            links = build_user_public_links(
                hysteria_username=hysteria_username,
                xui_sync_manager=self,
                server_configs=server_public_configs
            )
            
            if not links:
                logger.warning(f"No public VLESS links generated for {hysteria_username}, trying legacy")
                legacy_links = self._get_user_vless_uris_legacy(hysteria_username)
                if legacy_links:
                    return self._normalize_xui_links(legacy_links)
            
            logger.info(f"Generated {len(links)} VLESS links for user {hysteria_username}")
            return self._normalize_xui_links(links)
        
        except Exception as e:
            logger.error(f"Failed to generate public links for user {hysteria_username}: {e}", exc_info=True)
            # Fallback к старому методу
            logger.info("Falling back to legacy link generation method")
            return self._normalize_xui_links(self._get_user_vless_uris_legacy(hysteria_username))
    
    def _get_user_vless_uris_legacy(self, hysteria_username: str) -> List[Dict[str, Any]]:
        """
        Legacy метод получения VLESS URIs (использует внутренние адреса + LinkRewriter).
        
        Используется как fallback если новый метод не работает.
        """
        if not db:
            return []
        
        # Получаем данные пользователя для определения плана
        user_data = db.get_user(hysteria_username)
        if not user_data:
            return []
        
        user_plan = str(user_data.get('plan', 'standard')).lower().strip()
        if user_plan not in ('standard', 'premium'):
            user_plan = 'standard'
        
        # Получаем маппинг
        mapping = db.get_xui_mapping(hysteria_username)
        if not mapping:
            return []
        
        client_uuid = mapping.get('xui_client_uuid')
        if not client_uuid:
            return []
        
        uris = []
        
        # Получаем серверы для плана пользователя
        servers_for_plan = self._get_servers_for_plan(user_plan)
        
        # Получаем URIs с каждого сервера для плана
        for host, client, server_config in servers_for_plan:
            try:
                # Получаем список inbounds
                inbound_ids = self._get_inbound_ids(client, server_config)
                
                for inbound_id in inbound_ids:
                    try:
                        inbound = client.get_inbound(inbound_id)
                        if not inbound:
                            logger.debug(f"Inbound {inbound_id} not found, skipping")
                            continue
                        
                        # Логируем информацию о inbound для диагностики
                        inbound_protocol = inbound.get('protocol', 'unknown')
                        inbound_remark = inbound.get('remark', 'no remark')
                        inbound_network = inbound.get('stream_settings', {}).get('network', 'unknown')
                        logger.info(
                            f"Processing inbound {inbound_id} on server {host}: "
                            f"protocol={inbound_protocol}, remark={inbound_remark}, network={inbound_network}"
                        )
                        
                        # Пытаемся получить share link
                        # НЕ передаём server_host — функция сама использует 127.0.0.1,
                        # который потом перепишется LinkRewriter на публичный адрес
                        uri = None
                        try:
                            share_link = client.get_client_share_link(
                                inbound_id=inbound_id,
                                uuid=client_uuid
                            )
                            
                            if share_link:
                                uri = share_link
                                logger.info(f"Successfully got share_link for inbound {inbound_id} (network={inbound_network})")
                            else:
                                logger.debug(f"share_link is None for inbound {inbound_id}, trying build_vless_uri")
                                # Собираем URI вручную
                                # НЕ передаём host — функция сама использует 127.0.0.1
                                uri = client.build_vless_uri(
                                    inbound=inbound,
                                    client_uuid=client_uuid
                                )
                                if uri:
                                    logger.info(f"Successfully built URI for inbound {inbound_id} (network={inbound_network})")
                                else:
                                    logger.warning(f"build_vless_uri returned None for inbound {inbound_id} (network={inbound_network})")
                        except (XUIClientError, ValueError) as e:
                            # Если не удалось получить ссылку из-за отсутствия path/serviceName
                            # логируем и пропускаем этот inbound
                            logger.warning(
                                f"Failed to generate share link for inbound {inbound_id} (network={inbound_network}, remark={inbound_remark}) on server {host}: {e}. "
                                f"Skipping this inbound."
                            )
                            import traceback
                            logger.debug(f"Traceback for inbound {inbound_id}: {traceback.format_exc()}")
                            continue
                        except Exception as e:
                            # Другие ошибки - логируем и пропускаем
                            logger.warning(
                                f"Unexpected error generating share link for inbound {inbound_id} (network={inbound_network}, remark={inbound_remark}) on server {host}: {e}. "
                                f"Skipping this inbound."
                            )
                            import traceback
                            logger.debug(f"Traceback for inbound {inbound_id}: {traceback.format_exc()}")
                            continue
                        
                        if uri:
                            # Используем remark как имя
                            name = inbound.get('remark', f"Inbound {inbound_id}")
                            logger.info(f"Adding URI for inbound {inbound_id} (network={inbound_network}, remark={name})")
                            uris.append({
                                "name": name,
                                "uri": uri,
                                "server_id": server_config.get('name', host),  # ID сервера для LinkRewriter
                                "server_config": server_config  # Полная конфигурация сервера
                            })
                        else:
                            logger.warning(f"URI is None for inbound {inbound_id} (network={inbound_network}), skipping")
                    
                    except Exception as e:
                        logger.warning(f"Failed to get URI for inbound {inbound_id} on {host}: {e}")
                        import traceback
                        logger.debug(f"Traceback: {traceback.format_exc()}")
                        continue
            
            except Exception as e:
                logger.warning(f"Failed to get URIs from server {host}: {e}")
                continue
        
        return uris
    
    def close(self):
        """Закрывает все соединения"""
        for client in self.clients.values():
            try:
                client.close()
            except Exception:
                pass
