#!/usr/bin/env python3
"""
X-UI/3X-UI API Client
Использует py3xui библиотеку для авторизации через login().
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse
from datetime import datetime
from dataclasses import dataclass

# Импортируем nest_asyncio для работы в уже запущенном event loop
try:
    import nest_asyncio
    nest_asyncio.apply()
    NEST_ASYNCIO_AVAILABLE = True
except ImportError:
    NEST_ASYNCIO_AVAILABLE = False

# Обязательный импорт py3xui
try:
    from py3xui import AsyncApi
    PY3XUI_AVAILABLE = True
except ImportError:
    AsyncApi = None
    PY3XUI_AVAILABLE = False
    raise ImportError(
        "py3xui library is required. Install it with: pip install py3xui"
    )

logger = logging.getLogger(__name__)


@dataclass
class XUIConfig:
    """Конфигурация для подключения к X-UI"""
    USERNAME: str
    PASSWORD: str


@dataclass
class Connection:
    """Авторизованное соединение с сервером X-UI"""
    host: str
    api: AsyncApi  # AsyncApi из py3xui
    config: XUIConfig


class XUIClientError(Exception):
    """Базовое исключение для X-UI клиента"""
    pass


class XUIAuthError(XUIClientError):
    """Ошибка аутентификации"""
    pass


class XUIConnectionError(XUIClientError):
    """Ошибка подключения к X-UI"""
    pass


class XUIClient:
    """
    Клиент для работы с X-UI/3X-UI API.
    
    Использует py3xui библиотеку с AsyncApi для авторизации через метод login().
    Предоставляет синхронный интерфейс для совместимости с существующим кодом.
    """
    
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        base_path: str = "/",
        timeout: int = 10,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        """
        Инициализация клиента.
        
        Args:
            host: Хост X-UI (например, "http://localhost:54321" или "https://xui.example.com")
            username: Имя пользователя X-UI (обязательно)
            password: Пароль X-UI (обязательно)
            base_path: Базовый путь панели (по умолчанию "/", может быть "/panel" и т.д.)
            timeout: Таймаут запросов в секундах
            max_retries: Максимальное количество попыток при ошибках
            retry_delay: Задержка между попытками в секундах
        """
        if not PY3XUI_AVAILABLE:
            raise ImportError(
                "py3xui library is required. Install it with: pip install py3xui"
            )
        
        if not username or not password:
            raise ValueError("Username and password are required")
        
        # Нормализуем host (добавляем http:// если нет)
        parsed = urlparse(host)
        if not parsed.scheme:
            host = f"http://{host}"
        
        self.base_url = host.rstrip('/')
        self.base_path = base_path.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Создаем конфигурацию
        self.config = XUIConfig(
            USERNAME=username,
            PASSWORD=password
        )
        
        # Инициализация py3xui API (но еще не авторизуемся)
        self.py3xui_api: Optional[AsyncApi] = None
        self.connection: Optional[Connection] = None
        self._logged_in = False
        self._last_login_time = None
        self._login_cache_duration = 3600  # 1 час
    
    def _run_async_in_sync_context(self, coro):
        """
        Запускает корутину в синхронном или асинхронном контексте.
        Работает как в обычном синхронном коде, так и в уже запущенном event loop (FastAPI).
        """
        try:
            # Пытаемся получить запущенный loop
            loop = asyncio.get_running_loop()
            # Если loop уже запущен (например, в FastAPI), используем nest_asyncio
            if NEST_ASYNCIO_AVAILABLE:
                # nest_asyncio позволяет использовать run_until_complete в уже запущенном loop
                return loop.run_until_complete(coro)
            else:
                # Если nest_asyncio недоступен, запускаем в отдельном потоке
                import concurrent.futures
                import threading
                
                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(coro)
                    finally:
                        new_loop.close()
                
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    return future.result(timeout=30)  # Таймаут 30 секунд
        except RuntimeError:
            # Loop не запущен, можем использовать run_until_complete или asyncio.run
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    return asyncio.run(coro)
                return loop.run_until_complete(coro)
            except RuntimeError:
                return asyncio.run(coro)
    
    async def _login_async(self) -> bool:
        """
        Асинхронная авторизация через py3xui.
        
        Returns:
            True если авторизация успешна
        """
        try:
            # Формируем host с учетом base_path
            # py3xui будет использовать этот host для всех запросов, включая авторизацию
            # base_path указывается в настройках панели и используется как базовый путь без /login
            api_host = self.base_url
            if self.base_path and self.base_path != "/":
                # Убираем ведущий и завершающий слэши из base_path
                base = self.base_path.strip('/')
                if base:
                    # Если base_path указан, добавляем его к host
                    # py3xui будет использовать этот host для всех запросов
                    api_host = f"{self.base_url}/{base}"
            
            logger.debug(f"Connecting to X-UI at {api_host} with base_path={self.base_path}")
            
            # Создаем экземпляр AsyncApi
            # Передаем host с base_path, py3xui должен использовать его для авторизации
            api_kwargs = {
                'host': api_host,
                'username': self.config.USERNAME,
                'password': self.config.PASSWORD,
                'logger': logger
            }
            
            # Проверяем, поддерживает ли AsyncApi параметр base_path или path
            # Если поддерживает, передаем base_path отдельно
            try:
                import inspect
                sig = inspect.signature(AsyncApi.__init__)
                params = list(sig.parameters.keys())
                
                if 'base_path' in params:
                    api_kwargs['base_path'] = self.base_path
                    # Если base_path передается отдельно, используем оригинальный host
                    api_kwargs['host'] = self.base_url
                elif 'path' in params:
                    api_kwargs['path'] = self.base_path
                    api_kwargs['host'] = self.base_url
            except Exception:
                # Если не удалось проверить сигнатуру, используем host с base_path
                pass
            
            self.py3xui_api = AsyncApi(**api_kwargs)
            
            # Выполняем авторизацию через py3xui.login()
            # py3xui должен использовать base_path для авторизации без добавления /login
            logger.debug(f"Attempting py3xui.login() with host={api_host}")
            await self.py3xui_api.login()
            
            # Успешный логин
            self._logged_in = True
            self._last_login_time = datetime.now()
            
            # Создаем объект Connection
            self.connection = Connection(
                host=self.base_url,
                api=self.py3xui_api,
                config=self.config
            )
            
            logger.info(f"Successfully authorized via py3xui on {api_host}")
            return True
            
        except Exception as e:
            logger.error(f"py3xui authorization error on {self.base_url}: {e}")
            self.py3xui_api = None
            self.connection = None
            raise XUIAuthError(f"Failed to login via py3xui: {str(e)}")
    
    def login(self) -> bool:
        """
        Синхронная авторизация через py3xui.
        
        Returns:
            True если авторизация успешна
        
        Raises:
            XUIAuthError: При ошибке аутентификации
            XUIConnectionError: При ошибке подключения
        """
        # Проверяем кэш логина
        if self._logged_in and self._last_login_time:
            elapsed = (datetime.now() - self._last_login_time).total_seconds()
            if elapsed < self._login_cache_duration:
                return True
        
        # Выполняем авторизацию через py3xui
        try:
            return self._run_async_in_sync_context(self._login_async())
        except XUIAuthError:
            raise
        except Exception as e:
            raise XUIConnectionError(f"Failed to connect to X-UI: {e}")
    
    def ensure_logged_in(self):
        """Проверяет и при необходимости выполняет логин"""
        if not self._logged_in:
            self.login()
    
    async def _list_inbounds_async(self) -> List[Dict[str, Any]]:
        """Получает список inbounds (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            # Используем метод из py3xui для получения inbounds
            if hasattr(self.py3xui_api, 'list_inbounds'):
                inbounds = await self.py3xui_api.list_inbounds()
            elif hasattr(self.py3xui_api, 'get_inbounds'):
                inbounds = await self.py3xui_api.get_inbounds()
            else:
                # Если метод не найден, используем прямой вызов API через py3xui
                # Это зависит от реализации py3xui
                raise NotImplementedError("py3xui API method for listing inbounds not found")
            
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
    
    async def _ensure_logged_in_async(self):
        """Убеждается, что клиент авторизован (асинхронно)"""
        if not self._logged_in or not self.py3xui_api:
            await self._login_async()
    
    def list_inbounds(self) -> List[Dict[str, Any]]:
        """
        Получает список всех inbounds.
        
        Returns:
            Список inbounds с их параметрами
        
        Raises:
            XUIConnectionError: При ошибке подключения
            XUIAuthError: При ошибке аутентификации
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(self._list_inbounds_async())
    
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
            if hasattr(self.py3xui_api, 'add_client'):
                await self.py3xui_api.add_client(
                    inbound_id=inbound_id,
                    uuid=uuid,
                    expiry_time=expiry_time,
                    traffic_limit=traffic_limit,
                    enable=enable
                )
            elif hasattr(self.py3xui_api, 'add_inbound_client'):
                await self.py3xui_api.add_inbound_client(
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
        """
        Добавляет клиента в inbound.
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
            expiry_time: Время истечения (timestamp в секундах, опционально)
            traffic_limit: Лимит трафика в байтах (опционально)
            enable: Включен ли клиент
        
        Returns:
            True если успешно
        
        Raises:
            XUIClientError: При ошибке
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(
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
            if hasattr(self.py3xui_api, 'update_client'):
                await self.py3xui_api.update_client(
                    inbound_id=inbound_id,
                    uuid=uuid,
                    expiry_time=expiry_time,
                    traffic_limit=traffic_limit,
                    enable=enable
                )
            elif hasattr(self.py3xui_api, 'update_inbound_client'):
                await self.py3xui_api.update_inbound_client(
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
        """
        Обновляет клиента в inbound.
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
            expiry_time: Время истечения (timestamp в секундах, опционально)
            traffic_limit: Лимит трафика в байтах (опционально)
            enable: Включен ли клиент (опционально)
        
        Returns:
            True если успешно
        
        Raises:
            XUIClientError: При ошибке
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(
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
            if hasattr(self.py3xui_api, 'delete_client'):
                await self.py3xui_api.delete_client(inbound_id=inbound_id, uuid=uuid)
            elif hasattr(self.py3xui_api, 'remove_inbound_client'):
                await self.py3xui_api.remove_inbound_client(inbound_id=inbound_id, client_uuid=uuid)
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
        """
        Удаляет клиента из inbound.
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
        
        Returns:
            True если успешно
        
        Raises:
            XUIClientError: При ошибке
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(self._delete_client_async(inbound_id, uuid))
    
    async def _get_client_share_link_async(
        self,
        inbound_id: int,
        uuid: str
    ) -> Optional[str]:
        """Получает share link для клиента (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            if hasattr(self.py3xui_api, 'get_client_share_link'):
                link = await self.py3xui_api.get_client_share_link(inbound_id=inbound_id, uuid=uuid)
            elif hasattr(self.py3xui_api, 'get_share_link'):
                link = await self.py3xui_api.get_share_link(inbound_id=inbound_id, client_uuid=uuid)
            else:
                # Если метод не найден, возвращаем None
                logger.warning("Share link method not found in py3xui")
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
        """
        Получает share link для клиента.
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
        
        Returns:
            Share link или None если не удалось получить
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(self._get_client_share_link_async(inbound_id, uuid))
    
    def close(self):
        """Закрывает соединение"""
        if self.py3xui_api and hasattr(self.py3xui_api, 'close'):
            try:
                self._run_async_in_sync_context(self.py3xui_api.close())
            except Exception as e:
                logger.warning(f"Error closing API connection: {e}")
        
        self._logged_in = False
        self.py3xui_api = None
        self.connection = None
