#!/usr/bin/env python3
"""
Пул соединений с серверами X-UI/3X-UI.
Управляет соединениями, проверяет здоровье серверов и автоматически выбирает доступные.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

from xui.xui_api_wrapper import XUIAPIWrapper
from xui.xui_api_client import XUIAPIAuthError, XUIAPIConnectionError

# Для обратной совместимости
XUIClient = XUIAPIWrapper
XUIAuthError = XUIAPIAuthError
XUIConnectionError = XUIAPIConnectionError

logger = logging.getLogger(__name__)


@dataclass
class ServerConnection:
    """Соединение с сервером X-UI"""
    host: str
    client: XUIClient
    config: Dict
    online: bool = True
    last_check: Optional[datetime] = None
    check_interval: int = 300  # 5 минут
    error_count: int = 0
    max_errors: int = 3


class XUIServerPool:
    """
    Пул соединений с серверами X-UI.
    
    Управляет соединениями, проверяет здоровье серверов,
    автоматически выбирает доступные серверы.
    """
    
    def __init__(self, servers_config: List[Dict]):
        """
        Инициализация пула серверов.
        
        Args:
            servers_config: Список конфигураций серверов
        """
        self.servers: Dict[str, ServerConnection] = {}
        self._initialize_servers(servers_config)
        logger.info(f"X-UI Server Pool initialized with {len(self.servers)} servers")
    
    def _initialize_servers(self, servers_config: List[Dict]):
        """Инициализирует соединения с серверами"""
        for server_config in servers_config:
            if not server_config.get('enabled', True):
                continue
            
            host = server_config.get('host')
            if not host:
                continue
            
            auth_type = server_config.get('auth_type', 'username')
            username = server_config.get('username')
            password = server_config.get('password')
            
            if auth_type == 'token':
                if not password:
                    logger.warning(f"Server {host} skipped: token is required when auth_type=token")
                    continue
                username = 'admin'  # Заглушка для py3xui
            else:
                if not username or not password:
                    logger.warning(f"Server {host} skipped: username and password are required")
                    continue
            
            try:
                client = XUIClient(
                    host=host,
                    username=username,
                    password=password,
                    base_path=server_config.get('base_path', '/'),
                    timeout=server_config.get('timeout', 10),
                    max_retries=server_config.get('max_retries', 3),
                    verify_ssl=server_config.get('verify_ssl', True),
                    force_https=server_config.get('force_https', True)
                )
                
                # Пытаемся подключиться
                if client.login():
                    connection = ServerConnection(
                        host=host,
                        client=client,
                        config=server_config,
                        online=True,
                        last_check=datetime.now()
                    )
                    self.servers[host] = connection
                    logger.info(f"Server {host} added to pool successfully")
                else:
                    logger.warning(f"Server {host} failed to login, adding as offline")
                    connection = ServerConnection(
                        host=host,
                        client=client,
                        config=server_config,
                        online=False,
                        last_check=datetime.now()
                    )
                    self.servers[host] = connection
            except Exception as e:
                logger.error(f"Failed to initialize server {host}: {e}")
                # Добавляем как оффлайн для возможного восстановления
                try:
                    client = XUIClient(
                        host=host,
                        username=username or 'admin',
                        password=password or '',
                        base_path=server_config.get('base_path', '/'),
                        timeout=server_config.get('timeout', 10),
                        max_retries=server_config.get('max_retries', 3),
                        verify_ssl=server_config.get('verify_ssl', True),
                        force_https=server_config.get('force_https', True)
                    )
                    connection = ServerConnection(
                        host=host,
                        client=client,
                        config=server_config,
                        online=False,
                        last_check=datetime.now()
                    )
                    self.servers[host] = connection
                except Exception:
                    pass
    
    def get_available_server(self, user_plan: str = "standard") -> Optional[ServerConnection]:
        """
        Получает доступный сервер для указанного плана.
        
        Args:
            user_plan: План пользователя ("standard" или "premium")
        
        Returns:
            ServerConnection или None если нет доступных серверов
        """
        user_plan = str(user_plan).lower().strip()
        if user_plan not in ('standard', 'premium'):
            user_plan = 'standard'
        
        # Фильтруем серверы по плану и доступности
        available_servers = []
        for host, connection in self.servers.items():
            # Проверяем план
            server_plans = connection.config.get('plans', ['standard', 'premium'])
            if user_plan not in server_plans:
                continue
            
            # Проверяем доступность
            if not connection.online:
                # Пытаемся восстановить соединение
                if self._check_server_health(connection):
                    connection.online = True
                    connection.error_count = 0
                else:
                    continue
            
            available_servers.append(connection)
        
        if not available_servers:
            logger.warning(f"No available servers found for plan '{user_plan}'")
            return None
        
        # Возвращаем первый доступный (можно добавить логику выбора по нагрузке)
        return available_servers[0]
    
    def get_servers_for_plan(self, user_plan: str = "standard") -> List[ServerConnection]:
        """
        Получает все серверы для указанного плана.
        
        Args:
            user_plan: План пользователя
        
        Returns:
            Список ServerConnection
        """
        user_plan = str(user_plan).lower().strip()
        if user_plan not in ('standard', 'premium'):
            user_plan = 'standard'
        
        result = []
        for connection in self.servers.values():
            server_plans = connection.config.get('plans', ['standard', 'premium'])
            if user_plan in server_plans:
                result.append(connection)
        
        return result
    
    def get_connection(self, host: str) -> Optional[ServerConnection]:
        """
        Получает соединение по хосту.
        
        Args:
            host: Хост сервера
        
        Returns:
            ServerConnection или None
        """
        connection = self.servers.get(host)
        if connection and not connection.online:
            # Пытаемся восстановить
            if self._check_server_health(connection):
                connection.online = True
                connection.error_count = 0
        return connection
    
    def _check_server_health(self, connection: ServerConnection) -> bool:
        """
        Проверяет здоровье сервера.
        
        Args:
            connection: Соединение с сервером
        
        Returns:
            True если сервер доступен
        """
        try:
            # Проверяем, нужно ли обновлять проверку
            if connection.last_check:
                elapsed = (datetime.now() - connection.last_check).total_seconds()
                if elapsed < connection.check_interval:
                    return connection.online
            
            # Проверяем здоровье через проверку inbounds
            is_healthy, message = connection.client.check_health()
            connection.last_check = datetime.now()
            
            if is_healthy:
                connection.error_count = 0
                return True
            else:
                connection.error_count += 1
                if connection.error_count >= connection.max_errors:
                    connection.online = False
                    logger.warning(f"Server {connection.host} marked as offline: {message}")
                return False
        except Exception as e:
            connection.error_count += 1
            connection.last_check = datetime.now()
            logger.warning(f"Health check failed for {connection.host}: {e}")
            
            if connection.error_count >= connection.max_errors:
                connection.online = False
                logger.warning(f"Server {connection.host} marked as offline after {connection.error_count} errors")
            
            return False
    
    def refresh_server(self, host: str) -> bool:
        """
        Обновляет соединение с сервером.
        
        Args:
            host: Хост сервера
        
        Returns:
            True если успешно
        """
        connection = self.servers.get(host)
        if not connection:
            return False
        
        try:
            # Пытаемся переподключиться
            if connection.client.login():
                connection.online = True
                connection.error_count = 0
                connection.last_check = datetime.now()
                logger.info(f"Server {host} reconnected successfully")
                return True
            else:
                connection.online = False
                return False
        except Exception as e:
            logger.error(f"Failed to refresh server {host}: {e}")
            connection.online = False
            return False
    
    def sync_servers(self, servers_config: List[Dict]):
        """
        Синхронизирует пул с новой конфигурацией серверов.
        
        Args:
            servers_config: Новая конфигурация серверов
        """
        # Удаляем серверы, которых нет в новой конфигурации
        new_hosts = {s.get('host') for s in servers_config if s.get('host')}
        for host in list(self.servers.keys()):
            if host not in new_hosts:
                logger.info(f"Removing server {host} from pool")
                del self.servers[host]
        
        # Добавляем/обновляем серверы
        for server_config in servers_config:
            if not server_config.get('enabled', True):
                continue
            
            host = server_config.get('host')
            if not host:
                continue
            
            if host in self.servers:
                # Обновляем конфигурацию существующего сервера
                self.servers[host].config = server_config
                # Проверяем здоровье
                self._check_server_health(self.servers[host])
            else:
                # Добавляем новый сервер
                self._initialize_servers([server_config])
        
        logger.info(f"Server pool synced. Active servers: {len([s for s in self.servers.values() if s.online])}")
    
    def close(self):
        """Закрывает все соединения"""
        for connection in self.servers.values():
            try:
                connection.client.close()
            except Exception as e:
                logger.warning(f"Error closing connection to {connection.host}: {e}")
        
        self.servers.clear()
        logger.info("Server pool closed")
