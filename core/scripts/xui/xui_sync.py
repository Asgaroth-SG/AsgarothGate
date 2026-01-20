#!/usr/bin/env python3
"""
Модуль синхронизации пользователей Hysteria2 с X-UI/3X-UI.
"""

import logging
import uuid as uuid_lib
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta

# Добавляем путь к модулям для импорта
sys.path.insert(0, str(Path(__file__).parent.parent))

from db.database import db
from xui.xui_client import XUIClient, XUIClientError, XUIAuthError, XUIConnectionError

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
                    max_retries=server.get('max_retries', 3)
                )
                
                # Используем host как ключ
                self.clients[host] = client
    
    def _get_inbound_ids(self, client: XUIClient, server_config: Optional[Dict] = None) -> List[int]:
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
    
    def _get_servers_for_plan(self, user_plan: str) -> List[Tuple[str, XUIClient, Dict]]:
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
    
    def _convert_traffic_gb_to_bytes(self, traffic_gb: int) -> Optional[int]:
        """
        Конвертирует лимит трафика из GB в байты.
        
        Args:
            traffic_gb: Лимит трафика в GB
        
        Returns:
            Лимит в байтах или None если неограниченно
        """
        if traffic_gb <= 0:
            return None
        
        return int(traffic_gb * (1024 ** 3))
    
    def sync_user_create(
        self,
        hysteria_username: str,
        expiry_days: int,
        traffic_limit_gb: int,
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
        
        # Синхронизируем с каждым сервером для плана пользователя
        for host, client, server_config in servers_for_plan:
            try:
                logger.info(f"Syncing user {hysteria_username} with server {host}")
                # Получаем список inbounds для этого сервера
                inbound_ids = self._get_inbound_ids(client, server_config)
                
                if not inbound_ids:
                    logger.warning(f"No inbounds found for server {host}")
                    errors.append(f"No inbounds found on {host}")
                    continue
                
                logger.info(f"Found {len(inbound_ids)} inbounds on server {host}: {inbound_ids}")
                
                # Добавляем клиента в каждый inbound используя upsert для безопасной обработки существующих клиентов
                # В 3X-UI email должен быть уникальным глобально, используем формат username_inbound_id
                for inbound_id in inbound_ids:
                    try:
                        logger.debug(f"Upserting client {client_uuid} to inbound {inbound_id} on {host} with email {hysteria_username}_{inbound_id}")
                        # Используем upsert_client вместо add_client для безопасной обработки существующих клиентов
                        is_updated, action = client.upsert_client(
                            inbound_id=inbound_id,
                            uuid=client_uuid,
                            expiry_time=expiry_timestamp,
                            traffic_limit=traffic_bytes,
                            enable=enable,
                            username=hysteria_username  # Используется для генерации email: username_inbound_id
                        )
                        all_inbound_ids.append(inbound_id)
                        logger.info(
                            f"Successfully {action} client {client_uuid} (email: {hysteria_username}_{inbound_id}) in inbound {inbound_id} "
                            f"on server {host}"
                        )
                    except XUIClientError as e:
                        error_msg = f"Failed to upsert client to inbound {inbound_id} on {host}: {e}"
                        logger.error(error_msg, exc_info=True)
                        errors.append(error_msg)
                    except Exception as e:
                        error_msg = f"Unexpected error upserting client to inbound {inbound_id} on {host}: {e}"
                        logger.error(error_msg, exc_info=True)
                        errors.append(error_msg)
                
            except (XUIAuthError, XUIConnectionError) as e:
                error_msg = f"Failed to connect to X-UI server {host}: {e}"
                logger.error(error_msg)
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
        
        if errors:
            return False, error_message
        
        return True, None
    
    def sync_user_update(
        self,
        hysteria_username: str,
        expiry_days: Optional[int] = None,
        traffic_limit_gb: Optional[int] = None,
        enable: Optional[bool] = None,
        user_plan: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Синхронизирует обновление пользователя с X-UI.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
            expiry_days: Новые дни до истечения (None = не менять)
            traffic_limit_gb: Новый лимит трафика в GB (None = не менять)
            enable: Новый статус включения (None = не менять)
        
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
            expiry_timestamp = self._convert_expiry_days_to_timestamp(expiry_days)
        
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
                    # Используем upsert_client для правильной обработки существующих клиентов
                    is_updated, action = client.upsert_client(
                        inbound_id=inbound_id,
                        uuid=client_uuid,
                        expiry_time=expiry_timestamp,
                        traffic_limit=traffic_bytes,
                        enable=enable,
                        username=hysteria_username  # Используется для генерации email: username_inbound_id
                    )
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
                    client.delete_client(
                        inbound_id=inbound_id,
                        uuid=client_uuid  # Исправлено: параметр должен быть uuid, а не client_uuid
                    )
                    logger.info(
                        f"Deleted client {client_uuid} from inbound {inbound_id} "
                        f"on server {host}"
                    )
                except XUIClientError as e:
                    # Клиент может быть уже удален - это не критично
                    if "not found" in str(e).lower():
                        logger.warning(f"Client {client_uuid} not found in inbound {inbound_id} on {host}")
                    else:
                        error_msg = f"Failed to delete client from inbound {inbound_id} on {host}: {e}"
                        logger.error(error_msg)
                        errors.append(error_msg)
                except (XUIAuthError, XUIConnectionError) as e:
                    error_msg = f"Failed to connect to X-UI server {host}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
        
        # Удаляем маппинг
        db.delete_xui_mapping(hysteria_username)
        
        if errors:
            return False, "; ".join(errors)
        
        return True, None
    
    def get_user_vless_uris(self, hysteria_username: str) -> List[Dict[str, Any]]:
        """
        Получает список VLESS URIs для пользователя с учетом плана.
        
        Args:
            hysteria_username: Имя пользователя в Hysteria2
        
        Returns:
            Список словарей: [{"name": "Server1", "uri": "vless://..."}, ...]
        """
        if not self.config.enabled:
            return []
        
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
