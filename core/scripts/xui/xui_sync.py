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

# Импортируем настройку логирования
from xui.logging_config import setup_xui_logging
setup_xui_logging()

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
        
        logger.info(f"Initializing XUISyncManager (enabled: {config.enabled}, mode: {config.mode}, servers: {len(config.xui_servers)})")
        
        # Инициализируем клиенты для каждого сервера
        if config.enabled:
            for server in config.xui_servers:
                host = server.get('host')
                if not host:
                    logger.warning("Server skipped: host is required")
                    continue
                
                # Проверяем наличие username и password (обязательны)
                username = server.get('username')
                password = server.get('password')
                
                if not username or not password:
                    logger.warning(f"Server {host} skipped: username and password are required")
                    continue
                
                base_path = server.get('base_path', '/')
                logger.info(f"Initializing X-UI client for {host} with base_path={base_path}")
                
                client = XUIClient(
                    host=host,
                    username=username,
                    password=password,
                    base_path=base_path,
                    timeout=server.get('timeout', 10),
                    max_retries=server.get('max_retries', 3)
                )
                
                # Используем host как ключ
                self.clients[host] = client
                logger.info(f"X-UI client initialized for {host}")
        else:
            logger.info("X-UI sync is disabled")
    
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
            
            # Используем фильтр сервера или глобальный фильтр
            inbound_filter = server_config.get('inbound_filter', {}) if server_config else {}
            if not inbound_filter:
                inbound_filter = self.config.inbound_filter
            
            # Применяем фильтр
            filter_protocol = inbound_filter.get('protocol')
            filter_tag = inbound_filter.get('tag')
            filter_remark = inbound_filter.get('remark')
            
            filtered = client.filter_inbounds(
                protocol=filter_protocol,
                tag=filter_tag,
                remark=filter_remark
            )
            
            # Если фильтр не задан, используем все VLESS inbounds
            if not any([filter_protocol, filter_tag, filter_remark]):
                filtered = [i for i in inbounds if i.get('protocol', '').lower() == 'vless']
            
            return [i.get('id') for i in filtered if i.get('id')]
        
        except Exception as e:
            logger.error(f"Failed to get inbound IDs: {e}")
            return []
    
    def _get_servers_for_plan(self, user_plan: str) -> List[Tuple[str, XUIClient, Dict]]:
        """
        Получает список серверов X-UI для указанного плана пользователя.
        
        Args:
            user_plan: План пользователя ("standard" или "premium")
        
        Returns:
            Список кортежей (host, client, server_config)
        """
        logger.debug(f"Getting servers for plan '{user_plan}'")
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
        uuid = str(uuid_lib.uuid5(namespace, hysteria_username.lower()))
        logger.debug(f"Generated UUID {uuid} for user {hysteria_username}")
        return uuid
    
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
            # Пользователь уже синхронизирован
            logger.info(f"User {hysteria_username} already has X-UI mapping")
            return True, None
        
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
                # Получаем список inbounds для этого сервера
                inbound_ids = self._get_inbound_ids(client, server_config)
                
                if not inbound_ids:
                    logger.warning(f"No inbounds found for server {host}")
                    errors.append(f"No inbounds found on {host}")
                    continue
                
                # Добавляем клиента в каждый inbound
                for inbound_id in inbound_ids:
                    try:
                        client.add_client(
                            inbound_id=inbound_id,
                            uuid=client_uuid,
                            expiry_time=expiry_timestamp,
                            traffic_limit=traffic_bytes,
                            enable=enable
                        )
                        all_inbound_ids.append(inbound_id)
                        logger.info(
                            f"Added client {client_uuid} to inbound {inbound_id} "
                            f"on server {host}"
                        )
                    except XUIClientError as e:
                        error_msg = f"Failed to add client to inbound {inbound_id} on {host}: {e}"
                        logger.error(error_msg)
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
        logger.info(f"Updating user {hysteria_username} in X-UI (expiry: {expiry_days}, traffic: {traffic_limit_gb}, enable: {enable}, plan: {user_plan})")
        
        if not self.config.enabled:
            logger.debug(f"X-UI sync is disabled, skipping update for {hysteria_username}")
            return True, None
        
        if not db:
            logger.error("Database not available for user update")
            return False, "Database not available"
        
        # Получаем маппинг
        mapping = db.get_xui_mapping(hysteria_username)
        if not mapping:
            # Маппинга нет - создаем
            logger.info(f"No mapping found for {hysteria_username}, creating new mapping...")
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
        for host, client, server_config in servers_for_plan:
            # Получаем актуальные inbounds если список пуст
            if not inbound_ids:
                inbound_ids = self._get_inbound_ids(client, server_config)
            
            for inbound_id in inbound_ids:
                try:
                    client.update_client(
                        inbound_id=inbound_id,
                        client_uuid=client_uuid,
                        expiry_time=expiry_timestamp,
                        traffic_limit=traffic_bytes,
                        enable=enable
                    )
                    logger.info(
                        f"Updated client {client_uuid} in inbound {inbound_id} "
                        f"on server {host}"
                    )
                except XUIClientError as e:
                    error_msg = f"Failed to update client in inbound {inbound_id} on {host}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                except (XUIAuthError, XUIConnectionError) as e:
                    error_msg = f"Failed to connect to X-UI server {host}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
        
        # Обновляем маппинг
        sync_status = "success" if not errors else "failed"
        error_message = "; ".join(errors) if errors else None
        
        db.save_xui_mapping(
            hysteria_username=hysteria_username,
            xui_client_uuid=client_uuid,
            inbound_ids=inbound_ids,
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
        
        logger.info(f"Deleting user {hysteria_username} from X-UI (UUID: {client_uuid}, host: {xui_host}, inbounds: {inbound_ids})")
        
        if not client_uuid:
            # Удаляем маппинг даже если UUID нет
            logger.warning(f"No client UUID found for user {hysteria_username}, removing mapping only")
            db.delete_xui_mapping(hysteria_username)
            return True, None
        
        errors = []
        
        # Удаляем с каждого сервера
        servers_to_update = [xui_host] if xui_host and self.config.mode == 'single-xui' else list(self.clients.keys())
        logger.debug(f"Deleting from servers: {servers_to_update}")
        
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
                        client_uuid=client_uuid
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
        logger.debug(f"Getting VLESS URIs for user {hysteria_username}")
        
        if not self.config.enabled:
            logger.debug(f"X-UI sync is disabled, returning empty URIs for {hysteria_username}")
            return []
        
        if not db:
            logger.warning("Database not available for getting URIs")
            return []
        
        # Получаем данные пользователя для определения плана
        user_data = db.get_user(hysteria_username)
        if not user_data:
            logger.warning(f"User {hysteria_username} not found in database")
            return []
        
        user_plan = str(user_data.get('plan', 'standard')).lower().strip()
        if user_plan not in ('standard', 'premium'):
            user_plan = 'standard'
        
        logger.debug(f"User {hysteria_username} plan: {user_plan}")
        
        # Получаем маппинг
        mapping = db.get_xui_mapping(hysteria_username)
        if not mapping:
            logger.debug(f"No X-UI mapping found for user {hysteria_username}")
            return []
        
        client_uuid = mapping.get('xui_client_uuid')
        if not client_uuid:
            logger.warning(f"No client UUID in mapping for user {hysteria_username}")
            return []
        
        uris = []
        
        # Получаем серверы для плана пользователя
        servers_for_plan = self._get_servers_for_plan(user_plan)
        logger.debug(f"Found {len(servers_for_plan)} servers for plan {user_plan}")
        
        # Получаем URIs с каждого сервера для плана
        for host, client, server_config in servers_for_plan:
            try:
                # Получаем список inbounds
                inbound_ids = self._get_inbound_ids(client, server_config)
                
                for inbound_id in inbound_ids:
                    try:
                        inbound = client.get_inbound(inbound_id)
                        if not inbound:
                            continue
                        
                        # Пытаемся получить share link
                        share_link = client.get_client_share_link(
                            inbound_id=inbound_id,
                            client_uuid=client_uuid
                        )
                        
                        if share_link:
                            uri = share_link
                        else:
                            # Собираем URI вручную
                            uri = client.build_vless_uri(
                                inbound=inbound,
                                client_uuid=client_uuid
                            )
                        
                        if uri:
                            # Используем remark как имя, или host:inbound_id
                            name = inbound.get('remark', f"{host}:{inbound_id}")
                            uris.append({
                                "name": name,
                                "uri": uri
                            })
                    
                    except Exception as e:
                        logger.warning(f"Failed to get URI for inbound {inbound_id} on {host}: {e}")
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
