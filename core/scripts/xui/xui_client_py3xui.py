#!/usr/bin/env python3
"""
X-UI/3X-UI API Client на основе py3xui
Использует AsyncApi из библиотеки py3xui для авторизации через login()
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

try:
    from py3xui import AsyncApi
except ImportError:
    AsyncApi = None
    logging.warning("py3xui library not found. Install it with: pip install py3xui")

logger = logging.getLogger(__name__)


class XUIClientError(Exception):
    """Базовое исключение для X-UI клиента"""
    pass


class XUIAuthError(XUIClientError):
    """Ошибка аутентификации"""
    pass


class XUIConnectionError(XUIClientError):
    """Ошибка подключения к X-UI"""
    pass


@dataclass
class XUIConfig:
    """Конфигурация для подключения к X-UI"""
    USERNAME: str
    PASSWORD: str
    TOKEN: Optional[str] = None


@dataclass
class Connection:
    """Авторизованное соединение с сервером X-UI"""
    host: str
    api: Any  # AsyncApi из py3xui
    config: XUIConfig


class XUIClient:
    """
    Клиент для работы с X-UI/3X-UI API на основе py3xui.
    
    Использует AsyncApi из py3xui для авторизации через метод login().
    Предоставляет синхронный интерфейс для совместимости с существующим кодом.
    """
    
    def __init__(
        self,
        host: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        base_path: str = "/",
        timeout: int = 10,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        api_token: Optional[str] = None,
        auth_type: str = "auto"
    ):
        """
        Инициализация клиента.
        
        Args:
            host: Хост X-UI (например, "http://localhost:54321" или "https://xui.example.com")
            username: Имя пользователя X-UI
            password: Пароль X-UI
            base_path: Базовый путь панели (игнорируется для py3xui, используется host)
            timeout: Таймаут запросов в секундах
            max_retries: Максимальное количество попыток при ошибках
            retry_delay: Задержка между попытками в секундах
            api_token: API токен (если используется токен вместо username/password)
            auth_type: Тип авторизации - "login" (через login endpoint), "token" (через API токен)
        """
        if AsyncApi is None:
            raise ImportError(
                "py3xui library is required. Install it with: pip install py3xui"
            )
        
        # Нормализуем host
        if not host.startswith(('http://', 'https://')):
            host = f"http://{host}"
        
        self.host = host.rstrip('/')
        self.base_path = base_path.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Создаем конфигурацию
        if api_token and auth_type in ("token", "auto"):
            # Используем токен
            self.config = XUIConfig(
                USERNAME="",  # Не используется при токене
                PASSWORD="",  # Не используется при токене
                TOKEN=api_token
            )
            self.use_token = True
        elif username and password:
            # Используем username/password
            self.config = XUIConfig(
                USERNAME=username,
                PASSWORD=password,
                TOKEN=None
            )
            self.use_token = False
        else:
            raise ValueError("Either username/password or api_token must be provided")
        
        # Создаем объект API (но еще не авторизуемся)
        self.api: Optional[AsyncApi] = None
        self.connection: Optional[Connection] = None
        self._logged_in = False
        
        # Создаем event loop для синхронных вызовов
        self._loop = None
    
    def _get_event_loop(self):
        """Получает или создает event loop для синхронных вызовов"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Event loop is closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop
    
    async def _login_async(self) -> bool:
        """
        Асинхронная авторизация через py3xui.
        
        Returns:
            True если авторизация успешна, False в противном случае
        """
        try:
            # Создаем экземпляр AsyncApi
            if self.use_token and self.config.TOKEN:
                # Если используется токен, создаем API с токеном
                # py3xui может поддерживать токен через параметры
                self.api = AsyncApi(
                    host=self.host,
                    username=self.config.USERNAME or "admin",  # Заглушка
                    password=self.config.PASSWORD or "",  # Заглушка
                    logger=logger
                )
                # Устанавливаем токен если поддерживается
                if hasattr(self.api, 'set_token'):
                    self.api.set_token(self.config.TOKEN)
            else:
                # Используем username/password
                self.api = AsyncApi(
                    host=self.host,
                    username=self.config.USERNAME,
                    password=self.config.PASSWORD,
                    logger=logger
                )
            
            # Выполняем вход
            await self.api.login()
            
            # Создаем объект Connection
            self.connection = Connection(
                host=self.host,
                api=self.api,
                config=self.config
            )
            
            self._logged_in = True
            logger.info(f"Successfully authorized on {self.host}")
            return True
            
        except Exception as e:
            logger.error(f"Authorization error on {self.host}: {e}")
            self._logged_in = False
            self.api = None
            self.connection = None
            raise XUIAuthError(f"Failed to login: {str(e)}")
    
    def login(self) -> bool:
        """
        Синхронная авторизация через py3xui.
        
        Returns:
            True если авторизация успешна
        """
        if self._logged_in and self.api:
            return True
        
        loop = self._get_event_loop()
        try:
            return loop.run_until_complete(self._login_async())
        except Exception as e:
            if isinstance(e, XUIAuthError):
                raise
            raise XUIAuthError(f"Login failed: {str(e)}")
    
    async def _ensure_logged_in_async(self):
        """Убеждается, что клиент авторизован (асинхронно)"""
        if not self._logged_in or not self.api:
            await self._login_async()
    
    def ensure_logged_in(self):
        """Убеждается, что клиент авторизован (синхронно)"""
        if not self._logged_in or not self.api:
            self.login()
    
    async def _list_inbounds_async(self) -> List[Dict[str, Any]]:
        """Получает список inbounds (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            # Используем метод из py3xui для получения inbounds
            if hasattr(self.api, 'list_inbounds'):
                inbounds = await self.api.list_inbounds()
            elif hasattr(self.api, 'get_inbounds'):
                inbounds = await self.api.get_inbounds()
            else:
                # Если метод не найден, используем прямой вызов API
                # Это зависит от реализации py3xui
                raise NotImplementedError("py3xui API method not found")
            
            # Преобразуем в нужный формат
            result = []
            for inbound in inbounds:
                if isinstance(inbound, dict):
                    result.append(inbound)
                else:
                    # Если это объект, преобразуем в dict
                    result.append({
                        'id': getattr(inbound, 'id', None),
                        'remark': getattr(inbound, 'remark', ''),
                        'protocol': getattr(inbound, 'protocol', ''),
                        'settings': getattr(inbound, 'settings', {})
                    })
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to list inbounds: {e}")
            raise XUIClientError(f"Failed to list inbounds: {str(e)}")
    
    def list_inbounds(self) -> List[Dict[str, Any]]:
        """Получает список inbounds (синхронно)"""
        loop = self._get_event_loop()
        return loop.run_until_complete(self._list_inbounds_async())
    
    async def _add_client_async(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: bool = True
    ) -> bool:
        """Добавляет клиента в inbound (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            # Используем метод из py3xui для добавления клиента
            if hasattr(self.api, 'add_client'):
                await self.api.add_client(
                    inbound_id=inbound_id,
                    uuid=uuid,
                    expiry_time=expiry_time,
                    traffic_limit=traffic_limit,
                    enable=enable
                )
            elif hasattr(self.api, 'add_inbound_client'):
                await self.api.add_inbound_client(
                    inbound_id=inbound_id,
                    client_uuid=uuid,
                    expiry_time=expiry_time,
                    traffic_limit=traffic_limit,
                    enable=enable
                )
            else:
                raise NotImplementedError("py3xui API method for adding client not found")
            
            logger.info(f"Added client {uuid} to inbound {inbound_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add client: {e}")
            raise XUIClientError(f"Failed to add client: {str(e)}")
    
    def add_client(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: bool = True
    ) -> bool:
        """Добавляет клиента в inbound (синхронно)"""
        loop = self._get_event_loop()
        return loop.run_until_complete(
            self._add_client_async(inbound_id, uuid, expiry_time, traffic_limit, enable)
        )
    
    async def _update_client_async(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: Optional[bool] = None
    ) -> bool:
        """Обновляет клиента в inbound (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            if hasattr(self.api, 'update_client'):
                await self.api.update_client(
                    inbound_id=inbound_id,
                    uuid=uuid,
                    expiry_time=expiry_time,
                    traffic_limit=traffic_limit,
                    enable=enable
                )
            elif hasattr(self.api, 'update_inbound_client'):
                await self.api.update_inbound_client(
                    inbound_id=inbound_id,
                    client_uuid=uuid,
                    expiry_time=expiry_time,
                    traffic_limit=traffic_limit,
                    enable=enable
                )
            else:
                raise NotImplementedError("py3xui API method for updating client not found")
            
            logger.info(f"Updated client {uuid} in inbound {inbound_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update client: {e}")
            raise XUIClientError(f"Failed to update client: {str(e)}")
    
    def update_client(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: Optional[bool] = None
    ) -> bool:
        """Обновляет клиента в inbound (синхронно)"""
        loop = self._get_event_loop()
        return loop.run_until_complete(
            self._update_client_async(inbound_id, uuid, expiry_time, traffic_limit, enable)
        )
    
    async def _delete_client_async(
        self,
        inbound_id: int,
        uuid: str
    ) -> bool:
        """Удаляет клиента из inbound (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            if hasattr(self.api, 'delete_client'):
                await self.api.delete_client(inbound_id=inbound_id, uuid=uuid)
            elif hasattr(self.api, 'remove_inbound_client'):
                await self.api.remove_inbound_client(inbound_id=inbound_id, client_uuid=uuid)
            else:
                raise NotImplementedError("py3xui API method for deleting client not found")
            
            logger.info(f"Deleted client {uuid} from inbound {inbound_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete client: {e}")
            raise XUIClientError(f"Failed to delete client: {str(e)}")
    
    def delete_client(
        self,
        inbound_id: int,
        uuid: str
    ) -> bool:
        """Удаляет клиента из inbound (синхронно)"""
        loop = self._get_event_loop()
        return loop.run_until_complete(self._delete_client_async(inbound_id, uuid))
    
    async def _get_client_share_link_async(
        self,
        inbound_id: int,
        uuid: str
    ) -> Optional[str]:
        """Получает share link для клиента (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            if hasattr(self.api, 'get_client_share_link'):
                link = await self.api.get_client_share_link(inbound_id=inbound_id, uuid=uuid)
            elif hasattr(self.api, 'get_share_link'):
                link = await self.api.get_share_link(inbound_id=inbound_id, client_uuid=uuid)
            else:
                # Если метод не найден, пытаемся построить ссылку вручную
                logger.warning("Share link method not found in py3xui, constructing manually")
                return None
            
            return link if isinstance(link, str) else str(link)
            
        except Exception as e:
            logger.error(f"Failed to get share link: {e}")
            return None
    
    def get_client_share_link(
        self,
        inbound_id: int,
        uuid: str
    ) -> Optional[str]:
        """Получает share link для клиента (синхронно)"""
        loop = self._get_event_loop()
        return loop.run_until_complete(self._get_client_share_link_async(inbound_id, uuid))
    
    def close(self):
        """Закрывает соединение"""
        if self.api and hasattr(self.api, 'close'):
            loop = self._get_event_loop()
            try:
                loop.run_until_complete(self.api.close())
            except Exception as e:
                logger.warning(f"Error closing API connection: {e}")
        
        self._logged_in = False
        self.api = None
        self.connection = None
