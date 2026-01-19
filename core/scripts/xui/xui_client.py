#!/usr/bin/env python3
"""
X-UI/3X-UI API Client
Использует py3xui библиотеку для работы с 3X-UI API.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse
from datetime import datetime
from dataclasses import dataclass
import uuid as uuid_lib

# Импортируем nest_asyncio для работы в уже запущенном event loop
try:
    import nest_asyncio
    nest_asyncio.apply()
    NEST_ASYNCIO_AVAILABLE = True
except ImportError:
    NEST_ASYNCIO_AVAILABLE = False

# Обязательный импорт py3xui
try:
    from py3xui import AsyncApi, Client, Inbound
    PY3XUI_AVAILABLE = True
except ImportError:
    AsyncApi = None
    Client = None
    Inbound = None
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
        
        # Сохраняем оригинальный host без base_path
        self.base_url = host.rstrip('/')
        self.base_path = base_path.rstrip('/') if base_path else '/'
        
        # Если указан base_path, добавляем его к host для py3xui
        # py3xui требует полный путь в host, если используется custom URI path
        if self.base_path and self.base_path != '/':
            self.base_url = self.base_url.rstrip('/') + '/' + self.base_path.lstrip('/')
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
            # Создаем экземпляр AsyncApi
            # py3xui не принимает logger в конструкторе, убираем его
            self.py3xui_api = AsyncApi(
                host=self.base_url,
                username=self.config.USERNAME,
                password=self.config.PASSWORD
            )
            
            # Выполняем вход через login()
            await self.py3xui_api.login()
            
            # Создаем объект Connection
            self.connection = Connection(
                host=self.base_url,
                api=self.py3xui_api,
                config=self.config
            )
            
            self._logged_in = True
            self._last_login_time = datetime.now()
            logger.info(f"Successfully authorized via py3xui on {self.base_url}")
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
            # Используем правильный метод из py3xui: api.inbound.get_list()
            inbounds = await self.py3xui_api.inbound.get_list()
            
            # Преобразуем объекты Inbound в словари
            result = []
            for inbound in inbounds:
                if isinstance(inbound, Inbound):
                    result.append({
                        'id': inbound.id,
                        'remark': inbound.remark or '',
                        'protocol': inbound.protocol or '',
                        'port': inbound.port,
                        'enable': inbound.enable if hasattr(inbound, 'enable') else True,
                        'settings': inbound.settings.dict() if hasattr(inbound.settings, 'dict') else {}
                    })
                elif isinstance(inbound, dict):
                    result.append(inbound)
                else:
                    # Fallback для других типов
                    result.append({
                        'id': getattr(inbound, 'id', None),
                        'remark': getattr(inbound, 'remark', ''),
                        'protocol': getattr(inbound, 'protocol', ''),
                        'port': getattr(inbound, 'port', None),
                        'enable': getattr(inbound, 'enable', True),
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
        enable: bool = True,
        email: Optional[str] = None,
        username: Optional[str] = None
    ) -> bool:
        """Добавляет клиента в inbound (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            # В 3X-UI email должен быть уникальным глобально во всех inbounds
            # Используем формат: username_inbound_id для обеспечения уникальности
            if not email:
                if username:
                    # Формат: username_inbound_id (например: admin_1, admin_2)
                    email = f"{username}_{inbound_id}"
                else:
                    # Fallback: используем UUID_inbound_id
                    email = f"{uuid}_{inbound_id}"
                    logger.warning(f"Email and username not provided for client {uuid}, using UUID_inbound_id as email")
            
            client = Client(
                id=uuid,
                email=email,
                enable=enable
            )
            
            # Устанавливаем лимиты если указаны
            if expiry_time is not None:
                # py3xui использует expiry_time в миллисекундах (timestamp)
                # Проверяем, что это действительно миллисекунды
                if expiry_time < 1000000000000:  # Если меньше этого, значит секунды, конвертируем
                    expiry_time = expiry_time * 1000
                client.expiry_time = expiry_time
            
            if traffic_limit is not None:
                # py3xui использует total_gb для лимита трафика
                # Конвертируем байты в GB
                client.total_gb = traffic_limit / (1024 ** 3)
            
            # Используем правильный метод: api.client.add(inbound_id, [client])
            logger.debug(f"Calling py3xui api.client.add(inbound_id={inbound_id}, clients=[{client}])")
            await self.py3xui_api.client.add(inbound_id, [client])
            
            logger.info(f"Successfully added client {uuid} (email: {email}) to inbound {inbound_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add client {uuid} to inbound {inbound_id}: {e}", exc_info=True)
            raise XUIClientError(f"Failed to add client: {str(e)}")
    
    def add_client(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: bool = True,
        email: Optional[str] = None,
        username: Optional[str] = None
    ) -> bool:
        """
        Добавляет клиента в inbound.
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
            expiry_time: Время истечения (timestamp в миллисекундах, опционально)
            traffic_limit: Лимит трафика в байтах (опционально)
            enable: Включен ли клиент
            email: Email клиента (опционально, будет сгенерирован как username_inbound_id)
            username: Username из Hysteria (используется для генерации email если не указан)
        
        Returns:
            True если успешно
        
        Raises:
            XUIClientError: При ошибке
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(
            self._add_client_async(inbound_id, uuid, expiry_time, traffic_limit, enable, email, username)
        )
    
    async def _update_client_async(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: Optional[bool] = None,
        email: Optional[str] = None,
        username: Optional[str] = None
    ) -> bool:
        """Обновляет клиента в inbound (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            # Сначала получаем текущего клиента по UUID
            # В py3xui нужно получить inbound, найти клиента и обновить его
            inbound = await self.py3xui_api.inbound.get_by_id(inbound_id)
            
            if not inbound:
                raise XUIClientError(f"Inbound {inbound_id} not found")
            
            # Ищем клиента по UUID
            client_to_update = None
            try:
                # Проверяем, что clients существует и является итерируемым
                if hasattr(inbound, 'settings') and hasattr(inbound.settings, 'clients'):
                    clients = inbound.settings.clients
                    if isinstance(clients, list):
                        for client in clients:
                            if hasattr(client, 'id') and client.id == uuid:
                                client_to_update = client
                                break
                    elif hasattr(clients, '__iter__'):
                        # Если это не список, но итерируемый объект
                        for client in clients:
                            if hasattr(client, 'id') and client.id == uuid:
                                client_to_update = client
                                break
            except Exception as e:
                logger.warning(f"Error accessing clients from inbound {inbound_id}: {e}")
                client_to_update = None
            
            # Если клиент не найден в этом inbound, добавляем его
            if not client_to_update:
                logger.info(f"Client {uuid} not found in inbound {inbound_id}, adding it...")
                # Используем текущие значения или значения по умолчанию
                add_enable = enable if enable is not None else True
                try:
                    await self._add_client_async(
                        inbound_id=inbound_id,
                        uuid=uuid,
                        expiry_time=expiry_time,
                        traffic_limit=traffic_limit,
                        enable=add_enable,
                        email=email,
                        username=username
                    )
                    logger.info(f"Successfully added client {uuid} to inbound {inbound_id}")
                    return True
                except Exception as add_error:
                    logger.error(f"Failed to add client {uuid} to inbound {inbound_id}: {add_error}")
                    raise XUIClientError(f"Failed to add client to inbound: {str(add_error)}")
            
            # Обновляем параметры существующего клиента
            # Создаем копию клиента для обновления
            updated_client = Client(
                id=client_to_update.id,
                email=client_to_update.email,  # Сохраняем существующий email
                enable=enable if enable is not None else client_to_update.enable
            )
            
            # Устанавливаем лимиты
            if expiry_time is not None:
                # Проверяем формат времени (должно быть в миллисекундах)
                if expiry_time < 1000000000000:  # Если меньше этого, значит секунды, конвертируем
                    expiry_time = expiry_time * 1000
                updated_client.expiry_time = expiry_time
            elif hasattr(client_to_update, 'expiry_time'):
                updated_client.expiry_time = client_to_update.expiry_time
            
            if traffic_limit is not None:
                updated_client.total_gb = traffic_limit / (1024 ** 3)
            elif hasattr(client_to_update, 'total_gb'):
                updated_client.total_gb = client_to_update.total_gb
            
            # Используем правильный метод: api.client.update(client_uuid, client)
            await self.py3xui_api.client.update(uuid, updated_client)
            
            logger.info(f"Updated client {uuid} in inbound {inbound_id}")
            return True
            
        except XUIClientError:
            raise
        except Exception as e:
            logger.error(f"Failed to update client {uuid} in inbound {inbound_id}: {e}", exc_info=True)
            raise XUIClientError(f"Failed to update client: {str(e)}")
    
    def update_client(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: Optional[bool] = None,
        email: Optional[str] = None,
        username: Optional[str] = None
    ) -> bool:
        """
        Обновляет клиента в inbound.
        Если клиент не найден в inbound, добавляет его.
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
            expiry_time: Время истечения (timestamp в миллисекундах, опционально)
            traffic_limit: Лимит трафика в байтах (опционально)
            enable: Включен ли клиент (опционально)
            email: Email клиента (опционально, будет сгенерирован как username_inbound_id)
            username: Username из Hysteria (используется для генерации email если не указан)
        
        Returns:
            True если успешно
        
        Raises:
            XUIClientError: При ошибке
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(
            self._update_client_async(inbound_id, uuid, expiry_time, traffic_limit, enable, email, username)
        )
    
    async def _delete_client_async(
        self,
        inbound_id: int,
        uuid: str
    ) -> bool:
        """Удаляет клиента из inbound (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            # Используем правильный метод: api.client.delete(inbound_id, client_uuid)
            await self.py3xui_api.client.delete(inbound_id, uuid)
            
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
            # Получаем inbound
            inbound = await self.py3xui_api.inbound.get_by_id(inbound_id)
            if not inbound:
                logger.warning(f"Inbound {inbound_id} not found")
                return None
            
            # Пытаемся получить share link через метод API
            # Если такого метода нет, строим URI вручную на основе inbound и client
            try:
                # py3xui может иметь метод для получения share link
                # Если нет, строим вручную на основе протокола
                if inbound.protocol.lower() == 'vless':
                    # Строим VLESS URI вручную
                    # Это упрощенная версия, может потребоваться доработка
                    return f"vless://{uuid}@{inbound.remark or 'server'}:{inbound.port}"
                else:
                    logger.warning(f"Share link generation for protocol {inbound.protocol} not implemented")
                    return None
            except Exception as e:
                logger.warning(f"Failed to get share link via API: {e}")
                return None
            
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
    
    def filter_inbounds(
        self,
        protocol: Optional[str] = None,
        tag: Optional[str] = None,
        remark: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Фильтрует inbounds по указанным критериям.
        
        Args:
            protocol: Протокол (vless, vmess, etc.)
            tag: Тег
            remark: Замечание
        
        Returns:
            Отфильтрованный список inbounds
        """
        inbounds = self.list_inbounds()
        filtered = []
        
        for inbound in inbounds:
            if protocol and inbound.get('protocol', '').lower() != protocol.lower():
                continue
            if tag and inbound.get('tag') != tag:
                continue
            if remark and inbound.get('remark') != remark:
                continue
            filtered.append(inbound)
        
        return filtered
    
    async def _get_inbound_async(self, inbound_id: int) -> Optional[Dict[str, Any]]:
        """Получает inbound по ID (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            inbound = await self.py3xui_api.inbound.get_by_id(inbound_id)
            if not inbound:
                return None
            
            if isinstance(inbound, Inbound):
                return {
                    'id': inbound.id,
                    'remark': inbound.remark or '',
                    'protocol': inbound.protocol or '',
                    'port': inbound.port,
                    'enable': inbound.enable if hasattr(inbound, 'enable') else True,
                    'settings': inbound.settings.dict() if hasattr(inbound.settings, 'dict') else {}
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get inbound {inbound_id}: {e}")
            return None
    
    def get_inbound(self, inbound_id: int) -> Optional[Dict[str, Any]]:
        """
        Получает inbound по ID.
        
        Args:
            inbound_id: ID inbound
        
        Returns:
            Inbound или None если не найден
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(self._get_inbound_async(inbound_id))
    
    def build_vless_uri(
        self,
        inbound: Dict[str, Any],
        client_uuid: str,
        host: Optional[str] = None
    ) -> Optional[str]:
        """
        Строит VLESS URI для клиента на основе inbound.
        
        Args:
            inbound: Словарь с данными inbound
            client_uuid: UUID клиента
            host: Хост сервера (опционально, если не указан, используется remark)
        
        Returns:
            VLESS URI или None
        """
        try:
            protocol = inbound.get('protocol', '').lower()
            if protocol != 'vless':
                logger.warning(f"build_vless_uri called for non-VLESS protocol: {protocol}")
                return None
            
            # Получаем параметры из inbound
            port = inbound.get('port')
            if not port:
                logger.warning("Port not found in inbound")
                return None
            
            remark = inbound.get('remark', '')
            
            # Используем host если указан, иначе пытаемся извлечь из base_url или используем remark
            server_host = host
            if not server_host:
                # Пытаемся извлечь host из base_url
                parsed = urlparse(self.base_url)
                if parsed.hostname:
                    server_host = parsed.hostname
                else:
                    server_host = remark or 'server'
            
            # Строим базовый VLESS URI
            # Формат: vless://uuid@host:port?params#remark
            # Это упрощенная версия, может потребоваться доработка для полной поддержки всех параметров
            # Для полной версии нужно извлекать параметры из stream_settings
            uri = f"vless://{client_uuid}@{server_host}:{port}"
            
            # Добавляем remark как fragment если есть
            if remark:
                uri += f"#{remark}"
            
            return uri
        except Exception as e:
            logger.error(f"Failed to build VLESS URI: {e}")
            return None
    
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
