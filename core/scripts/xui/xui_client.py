#!/usr/bin/env python3
"""
X-UI/3X-UI API Client
Использует py3xui библиотеку для работы с 3X-UI API.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse, unquote
from datetime import datetime
from dataclasses import dataclass
import uuid as uuid_lib
import re

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


def _normalize_stream_settings(stream_settings: Any) -> Dict[str, Any]:
    """
    Нормализует stream_settings в dict.
    
    Поддерживает:
    - dict → возвращает как есть
    - объект с методом dict() → вызывает dict()
    - объект с методом model_dump() (Pydantic v2) → вызывает model_dump()
    - объект с __dict__ → рекурсивно преобразует
    - JSON строка → парсит
    - другие типы → пытается преобразовать через JSON
    
    Args:
        stream_settings: stream_settings в любом формате
        
    Returns:
        Нормализованный dict
    """
    if stream_settings is None:
        return {}
    
    # Если уже dict
    if isinstance(stream_settings, dict):
        return stream_settings
    
    # Если объект с методом dict() (Pydantic v1)
    if hasattr(stream_settings, 'dict'):
        try:
            result = stream_settings.dict()
            logger.debug(f"_normalize_stream_settings: Used dict() method, keys: {list(result.keys()) if isinstance(result, dict) else 'not a dict'}")
            return result
        except Exception as e:
            logger.debug(f"Failed to call dict() on stream_settings: {e}")
    
    # Если объект с методом model_dump() (Pydantic v2)
    if hasattr(stream_settings, 'model_dump'):
        try:
            result = stream_settings.model_dump()
            logger.debug(f"_normalize_stream_settings: Used model_dump() method, keys: {list(result.keys()) if isinstance(result, dict) else 'not a dict'}")
            return result
        except Exception as e:
            logger.debug(f"Failed to call model_dump() on stream_settings: {e}")
    
    # Если объект с __dict__
    if hasattr(stream_settings, '__dict__'):
        try:
            stream_settings_dict = {}
            for key, value in stream_settings.__dict__.items():
                # Пропускаем приватные атрибуты
                if key.startswith('_'):
                    continue
                    
                if hasattr(value, 'dict'):
                    stream_settings_dict[key] = value.dict()
                elif hasattr(value, 'model_dump'):
                    stream_settings_dict[key] = value.model_dump()
                elif hasattr(value, '__dict__'):
                    # Рекурсивно преобразуем вложенные объекты
                    nested_dict = {}
                    for k, v in value.__dict__.items():
                        if k.startswith('_'):
                            continue
                        if hasattr(v, 'dict'):
                            nested_dict[k] = v.dict()
                        elif hasattr(v, 'model_dump'):
                            nested_dict[k] = v.model_dump()
                        elif isinstance(v, (dict, list, str, int, float, bool, type(None))):
                            nested_dict[k] = v
                        else:
                            try:
                                nested_dict[k] = str(v)
                            except:
                                pass
                    stream_settings_dict[key] = nested_dict
                elif isinstance(value, (dict, list, str, int, float, bool, type(None))):
                    stream_settings_dict[key] = value
                else:
                    try:
                        stream_settings_dict[key] = str(value)
                    except:
                        pass
            logger.debug(f"_normalize_stream_settings: Used __dict__, keys: {list(stream_settings_dict.keys())}")
            return stream_settings_dict
        except Exception as e:
            logger.warning(f"Failed to convert stream_settings from __dict__: {e}")
    
    # Если JSON строка - ОБЯЗАТЕЛЬНО парсим
    if isinstance(stream_settings, str):
        try:
            import json
            parsed = json.loads(stream_settings)
            logger.debug(f"_normalize_stream_settings: Successfully parsed JSON string, keys: {list(parsed.keys()) if isinstance(parsed, dict) else 'not a dict'}")
            return parsed
        except Exception as e:
            logger.warning(f"Failed to parse stream_settings as JSON: {e}, string: {stream_settings[:200]}...")
            return {}
    
    # Последняя попытка через JSON сериализацию
    try:
        import json
        result = json.loads(json.dumps(stream_settings, default=str))
        logger.debug(f"_normalize_stream_settings: Used JSON serialization, keys: {list(result.keys()) if isinstance(result, dict) else 'not a dict'}")
        return result
    except Exception as e:
        logger.warning(f"Failed to normalize stream_settings: {e}")
        return {}


def _extract_xhttp_path(stream_settings: Dict[str, Any], inbound_id: int | str) -> str:
    """
    Извлекает path для xhttp из stream_settings.
    Источник истины - ТОЛЬКО streamSettings из 3X-UI, никаких fallback значений.
    
    Приоритет поиска:
    1. xhttpSettings.path (camelCase)
    2. extra (legacy структура)
    3. xhttp_settings.path (snake_case)
    4. splithttpSettings.path
    
    Args:
        stream_settings: Нормализованный dict stream_settings
        inbound_id: ID inbound для логирования
        
    Returns:
        Path строка (не пустой и не "/")
        
    Raises:
        ValueError: Если path не найден, пустой или равен "/"
    """
    # ПРИОРИТЕТ 1: xhttpSettings (camelCase) - основной источник
    xhttp_settings = stream_settings.get('xhttpSettings')
    if xhttp_settings:
        if not isinstance(xhttp_settings, dict):
            xhttp_settings = _normalize_stream_settings(xhttp_settings)
        if isinstance(xhttp_settings, dict):
            path = xhttp_settings.get('path')
            if path is not None:
                if isinstance(path, str):
                    path = path.strip()
                    if path and path != '/':
                        logger.debug(f"Inbound {inbound_id}: Found xhttp path in xhttpSettings: '{path}'")
                        return path
                elif isinstance(path, (int, float)):
                    path_str = str(path).strip()
                    if path_str and path_str != '/':
                        logger.debug(f"Inbound {inbound_id}: Found xhttp path in xhttpSettings (numeric): '{path_str}'")
                        return path_str
    
    # ПРИОРИТЕТ 2: extra (legacy структура)
    extra = stream_settings.get('extra')
    if extra:
        if not isinstance(extra, dict):
            extra = _normalize_stream_settings(extra)
        if isinstance(extra, dict):
            # Проверяем xhttpSettings внутри extra
            extra_xhttp = extra.get('xhttpSettings') or extra.get('xhttp_settings')
            if extra_xhttp:
                if not isinstance(extra_xhttp, dict):
                    extra_xhttp = _normalize_stream_settings(extra_xhttp)
                if isinstance(extra_xhttp, dict):
                    path = extra_xhttp.get('path')
                    if path is not None:
                        if isinstance(path, str):
                            path = path.strip()
                            if path and path != '/':
                                logger.debug(f"Inbound {inbound_id}: Found xhttp path in extra.xhttpSettings: '{path}'")
                                return path
    
    # ПРИОРИТЕТ 3: xhttp_settings (snake_case)
    xhttp_settings_snake = stream_settings.get('xhttp_settings')
    if xhttp_settings_snake:
        if not isinstance(xhttp_settings_snake, dict):
            xhttp_settings_snake = _normalize_stream_settings(xhttp_settings_snake)
        if isinstance(xhttp_settings_snake, dict):
            path = xhttp_settings_snake.get('path')
            if path is not None:
                if isinstance(path, str):
                    path = path.strip()
                    if path and path != '/':
                        logger.debug(f"Inbound {inbound_id}: Found xhttp path in xhttp_settings: '{path}'")
                        return path
    
    # ПРИОРИТЕТ 4: splithttpSettings (альтернативное название)
    splithttp_settings = stream_settings.get('splithttpSettings') or stream_settings.get('splithttp_settings')
    if splithttp_settings:
        if not isinstance(splithttp_settings, dict):
            splithttp_settings = _normalize_stream_settings(splithttp_settings)
        if isinstance(splithttp_settings, dict):
            path = splithttp_settings.get('path')
            if path is not None:
                if isinstance(path, str):
                    path = path.strip()
                    if path and path != '/':
                        logger.debug(f"Inbound {inbound_id}: Found xhttp path in splithttpSettings: '{path}'")
                        return path
    
    # Если ничего не найдено - логируем warning и выбрасываем исключение
    import json
    try:
        stream_settings_dump = json.dumps(stream_settings, indent=2, default=str)[:1000]
    except:
        stream_settings_dump = str(stream_settings)[:1000]
    
    logger.warning(
        f"Inbound {inbound_id}: Failed to extract xhttp path from stream_settings. "
        f"xhttpSettings key is missing or path not found/is empty/equals '/'. "
        f"stream_settings (truncated): {stream_settings_dump}"
    )
    raise ValueError(
        f"Inbound {inbound_id}: xhttp path not found in stream_settings or path is invalid (empty or '/'). "
        f"Please check inbound configuration in 3X-UI. Available keys: {list(stream_settings.keys()) if isinstance(stream_settings, dict) else 'not a dict'}"
    )


def _parse_vless_link(vless_link: str) -> Dict[str, str]:
    """
    Парсит VLESS ссылку и извлекает все параметры из query string.
    
    Args:
        vless_link: VLESS ссылка вида vless://uuid@host:port?params#remark
    
    Returns:
        Словарь с параметрами из query string (ключи в нижнем регистре, значения URL-decoded)
    """
    if not vless_link or not vless_link.startswith('vless://'):
        return {}
    
    try:
        # Извлекаем query string (часть после ? и до #)
        query_start = vless_link.find('?')
        fragment_start = vless_link.find('#')
        
        if query_start == -1:
            return {}
        
        query_end = fragment_start if fragment_start != -1 else len(vless_link)
        query_string = vless_link[query_start + 1:query_end]
        
        # Парсим query string
        params = {}
        for pair in query_string.split('&'):
            if '=' in pair:
                key, value = pair.split('=', 1)
                key = key.lower()
                # URL-decode значение
                params[key] = unquote(value)
        
        return params
    except Exception as e:
        logger.warning(f"_parse_vless_link: Failed to parse vless link: {e}")
        return {}


def _extract_grpc_service_name(stream_settings: Dict[str, Any], inbound_id: int | str) -> str:
    """
    Извлекает serviceName для grpc из stream_settings.
    Источник истины - ТОЛЬКО streamSettings из 3X-UI.
    
    Приоритет поиска:
    1. grpcSettings.serviceName (camelCase) - основной источник
    2. grpcSettings.service_name (snake_case)
    3. grpcSettings.service (legacy)
    4. grpc_settings.* (альтернативный ключ)
    
    Args:
        stream_settings: Нормализованный dict stream_settings
        inbound_id: ID inbound для логирования
        
    Returns:
        Service name строка (не пустая)
        
    Raises:
        ValueError: Если serviceName не найден или пустой
    """
    def _try_extract_service_name(grpc_dict: dict, source: str) -> str | None:
        """Попытка извлечь serviceName из словаря grpcSettings."""
        # Проверяем все возможные ключи
        for key in ['serviceName', 'service_name', 'service']:
            value = grpc_dict.get(key)
            if value is not None:
                if isinstance(value, str):
                    value = value.strip()
                    if value:
                        logger.debug(f"Inbound {inbound_id}: Found grpc serviceName via {source}.{key}: '{value}'")
                        return value
                elif isinstance(value, (int, float)):
                    value_str = str(value).strip()
                    if value_str:
                        logger.debug(f"Inbound {inbound_id}: Found grpc serviceName via {source}.{key} (numeric): '{value_str}'")
                        return value_str
        return None
    
    # ПРИОРИТЕТ 1: grpcSettings (camelCase) - основной источник
    grpc_settings = stream_settings.get('grpcSettings')
    if grpc_settings:
        if not isinstance(grpc_settings, dict):
            grpc_settings = _normalize_stream_settings(grpc_settings)
        if isinstance(grpc_settings, dict):
            result = _try_extract_service_name(grpc_settings, 'grpcSettings')
            if result:
                return result
    
    # ПРИОРИТЕТ 2: grpc_settings (snake_case)
    grpc_settings_snake = stream_settings.get('grpc_settings')
    if grpc_settings_snake:
        if not isinstance(grpc_settings_snake, dict):
            grpc_settings_snake = _normalize_stream_settings(grpc_settings_snake)
        if isinstance(grpc_settings_snake, dict):
            result = _try_extract_service_name(grpc_settings_snake, 'grpc_settings')
            if result:
                return result
    
    # Если ничего не найдено - логируем warning и выбрасываем исключение
    # НЕ используем fallback значения!
    import json
    try:
        stream_settings_dump = json.dumps(stream_settings, indent=2, default=str)[:1000]
    except:
        stream_settings_dump = str(stream_settings)[:1000]
    
    logger.warning(
        f"Inbound {inbound_id}: Failed to extract grpc serviceName from stream_settings. "
        f"grpcSettings key is missing or serviceName not found/is empty. "
        f"stream_settings (truncated): {stream_settings_dump}"
    )
    raise ValueError(
        f"Inbound {inbound_id}: grpc serviceName not found in stream_settings or is empty. "
        f"Please check inbound configuration in 3X-UI. Available keys: {list(stream_settings.keys()) if isinstance(stream_settings, dict) else 'not a dict'}"
    )


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
    
    async def _check_health_async(self) -> Tuple[bool, str]:
        """
        Проверяет доступность сервера X-UI (асинхронно).
        
        Returns:
            Tuple (is_healthy: bool, message: str)
        """
        try:
            await self._ensure_logged_in_async()
            # Пытаемся получить список inbounds как проверку здоровья
            inbounds = await self.py3xui_api.inbound.get_list()
            return True, f"Online ({len(inbounds)} inbounds)"
        except XUIAuthError as e:
            return False, f"Authentication failed: {str(e)}"
        except XUIConnectionError as e:
            return False, f"Connection failed: {str(e)}"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def check_health(self) -> Tuple[bool, str]:
        """
        Проверяет доступность сервера X-UI.
        
        Returns:
            Tuple (is_healthy: bool, message: str)
        """
        try:
            return self._run_async_in_sync_context(self._check_health_async())
        except Exception as e:
            return False, f"Error: {str(e)}"
    
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
    
    async def _list_clients_async(self, inbound_id: int) -> List[Dict[str, Any]]:
        """Получает список клиентов в inbound (асинхронно)"""
        await self._ensure_logged_in_async()
        
        try:
            inbound = await self.py3xui_api.inbound.get_by_id(inbound_id)
            if not inbound:
                raise XUIClientError(f"Inbound {inbound_id} not found")
            
            clients = []
            try:
                if hasattr(inbound, 'settings') and hasattr(inbound.settings, 'clients'):
                    client_list = inbound.settings.clients
                    if isinstance(client_list, list):
                        for client in client_list:
                            clients.append({
                                'id': getattr(client, 'id', None),
                                'email': getattr(client, 'email', ''),
                                'enable': getattr(client, 'enable', True),
                                'expiry_time': getattr(client, 'expiry_time', None),
                                'total_gb': getattr(client, 'total_gb', None)
                            })
                    elif hasattr(client_list, '__iter__'):
                        for client in client_list:
                            clients.append({
                                'id': getattr(client, 'id', None),
                                'email': getattr(client, 'email', ''),
                                'enable': getattr(client, 'enable', True),
                                'expiry_time': getattr(client, 'expiry_time', None),
                                'total_gb': getattr(client, 'total_gb', None)
                            })
            except Exception as e:
                logger.warning(f"Error accessing clients from inbound {inbound_id}: {e}")
            
            return clients
        except Exception as e:
            logger.error(f"Failed to list clients in inbound {inbound_id}: {e}")
            raise XUIClientError(f"Failed to list clients: {str(e)}")
    
    def list_clients(self, inbound_id: int) -> List[Dict[str, Any]]:
        """
        Получает список клиентов в inbound.
        
        Args:
            inbound_id: ID inbound
        
        Returns:
            Список клиентов с их параметрами
        
        Raises:
            XUIClientError: При ошибке
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(self._list_clients_async(inbound_id))
    
    async def _upsert_client_async(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: Optional[bool] = None,
        email: Optional[str] = None,
        username: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Добавляет или обновляет клиента в inbound (UPSERT).
        
        Returns:
            Tuple (is_updated: bool, message: str)
        """
        await self._ensure_logged_in_async()
        
        try:
            # Генерируем email если не указан
            if not email:
                if username:
                    email = f"{username}_{inbound_id}"
                else:
                    email = f"{uuid}_{inbound_id}"
            
            # Получаем список клиентов в inbound
            clients = await self._list_clients_async(inbound_id)
            
            # Ищем клиента по UUID или email
            client_to_update = None
            for client in clients:
                client_id = client.get('id')
                client_email = client.get('email', '')
                # Ищем по UUID или email (email более стабильный ключ)
                # Проверяем точное совпадение UUID или email
                if (client_id and str(client_id) == str(uuid)) or (client_email and client_email == email):
                    client_to_update = client
                    break
            
            # Если клиент найден - обновляем
            if client_to_update:
                try:
                    # Получаем полный inbound для обновления
                    inbound = await self.py3xui_api.inbound.get_by_id(inbound_id)
                    if not inbound:
                        raise XUIClientError(f"Inbound {inbound_id} not found")
                    
                    # Находим клиента в inbound для получения всех полей
                    actual_client = None
                    if hasattr(inbound, 'settings') and hasattr(inbound.settings, 'clients'):
                        client_list = inbound.settings.clients
                        if isinstance(client_list, list):
                            for c in client_list:
                                if (hasattr(c, 'id') and c.id == uuid) or (hasattr(c, 'email') and c.email == email):
                                    actual_client = c
                                    break
                    
                    if not actual_client:
                        # Клиент не найден в полном inbound, но был в списке - возможно рассинхронизация
                        # Пробуем добавить, но если получим duplicate email - это нормально
                        try:
                            await self._add_client_async(
                                inbound_id=inbound_id,
                                uuid=uuid,
                                expiry_time=expiry_time,
                                traffic_limit=traffic_limit,
                                enable=enable if enable is not None else True,
                                email=email,
                                username=username
                            )
                            return False, "added"
                        except Exception as add_error:
                            add_error_str = str(add_error).lower()
                            # Если ошибка "duplicate email" - клиент уже существует, считаем успехом
                            if "duplicate email" in add_error_str or "already exists" in add_error_str:
                                logger.info(f"Client {uuid} (email: {email}) already exists in inbound {inbound_id}, skipping")
                                return True, "already exists"
                            # Перебрасываем другие ошибки
                            raise XUIClientError(f"Failed to add client: {str(add_error)}")
                    
                    # Создаем обновленный клиент
                    updated_client = Client(
                        id=actual_client.id,  # Используем реальный ID из 3X-UI
                        email=actual_client.email,  # Сохраняем существующий email
                        enable=enable if enable is not None else actual_client.enable
                    )
                    
                    # Устанавливаем лимиты
                    if expiry_time is not None:
                        if expiry_time < 1000000000000:
                            expiry_time = expiry_time * 1000
                        updated_client.expiry_time = expiry_time
                    elif hasattr(actual_client, 'expiry_time'):
                        updated_client.expiry_time = actual_client.expiry_time
                    
                    if traffic_limit is not None:
                        updated_client.total_gb = traffic_limit / (1024 ** 3)
                    elif hasattr(actual_client, 'total_gb'):
                        updated_client.total_gb = actual_client.total_gb
                    
                    # Обновляем используя реальный client.id из 3X-UI
                    await self.py3xui_api.client.update(actual_client.id, updated_client)
                    logger.info(f"Updated client {uuid} (3X-UI id: {actual_client.id}) in inbound {inbound_id}")
                    return True, "updated"
                    
                except Exception as update_error:
                    # Если update не удался, проверяем причину
                    error_str = str(update_error).lower()
                    if "not found" in error_str or "record not found" in error_str:
                        # Клиент не найден для обновления - пробуем добавить
                        logger.warning(f"Update failed (record not found), trying add: {update_error}")
                        try:
                            await self._add_client_async(
                                inbound_id=inbound_id,
                                uuid=uuid,
                                expiry_time=expiry_time,
                                traffic_limit=traffic_limit,
                                enable=enable if enable is not None else True,
                                email=email,
                                username=username
                            )
                            return False, "added (fallback)"
                        except Exception as add_error:
                            add_error_str = str(add_error).lower()
                            # Если ошибка "duplicate email" - клиент уже существует, считаем успехом
                            if "duplicate email" in add_error_str or "already exists" in add_error_str:
                                logger.info(f"Client {uuid} (email: {email}) already exists in inbound {inbound_id}, skipping")
                                return True, "already exists"
                            raise XUIClientError(f"Failed to add client after update failed: {str(add_error)}")
                    elif "duplicate email" in error_str or "already exists" in error_str:
                        # Клиент уже существует - это нормально, считаем успехом
                        logger.info(f"Client {uuid} (email: {email}) already exists in inbound {inbound_id}")
                        return True, "already exists"
                    else:
                        # Другие ошибки обновления - но клиент был найден в списке, значит он существует
                        # Считаем это успехом, так как клиент уже есть в системе
                        logger.warning(f"Update failed for client {uuid} (email: {email}) in inbound {inbound_id}: {update_error}")
                        logger.info(f"Client was found in list, considering as success despite update failure")
                        return True, "update skipped (client exists)"
            else:
                # Клиент не найден в списке - пробуем добавить
                try:
                    await self._add_client_async(
                        inbound_id=inbound_id,
                        uuid=uuid,
                        expiry_time=expiry_time,
                        traffic_limit=traffic_limit,
                        enable=enable if enable is not None else True,
                        email=email,
                        username=username
                    )
                    return False, "added"
                except Exception as add_error:
                    add_error_str = str(add_error).lower()
                    # Если ошибка "duplicate email" - клиент уже существует, считаем успехом
                    if "duplicate email" in add_error_str or "already exists" in add_error_str:
                        logger.info(f"Client {uuid} (email: {email}) already exists in inbound {inbound_id}, skipping")
                        return True, "already exists"
                    # Перебрасываем другие ошибки
                    raise XUIClientError(f"Failed to add client: {str(add_error)}")
                
        except XUIClientError:
            raise
        except Exception as e:
            logger.error(f"Failed to upsert client {uuid} in inbound {inbound_id}: {e}", exc_info=True)
            raise XUIClientError(f"Failed to upsert client: {str(e)}")
    
    def upsert_client(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: Optional[bool] = None,
        email: Optional[str] = None,
        username: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Добавляет или обновляет клиента в inbound (UPSERT).
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
            expiry_time: Время истечения (timestamp в миллисекундах, опционально)
            traffic_limit: Лимит трафика в байтах (опционально)
            enable: Включен ли клиент (опционально)
            email: Email клиента (опционально, будет сгенерирован как username_inbound_id)
            username: Username из Hysteria (используется для генерации email если не указан)
        
        Returns:
            Tuple (is_updated: bool, action: str) - True если обновлен, False если добавлен
        
        Raises:
            XUIClientError: При ошибке
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(
            self._upsert_client_async(inbound_id, uuid, expiry_time, traffic_limit, enable, email, username)
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
        """Обновляет клиента в inbound (асинхронно) - использует upsert внутри"""
        is_updated, _ = await self._upsert_client_async(
            inbound_id, uuid, expiry_time, traffic_limit, enable, email, username
        )
        return True  # Всегда успешно, так как upsert либо обновляет, либо добавляет
    
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
        uuid: str,
        server_host: Optional[str] = None
    ) -> Optional[str]:
        """
        Получает share link для клиента (асинхронно).
        
        Строит полную ссылку с query параметрами из stream_settings inbound.
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
            server_host: Хост сервера для ссылки (если None, извлекается из base_url)
        """
        await self._ensure_logged_in_async()
        
        try:
            # Сначала пытаемся использовать метод py3xui для получения share link напрямую
            # Пытаемся использовать метод py3xui напрямую для получения share link
            # Это гарантирует корректность всех параметров, включая serviceName для gRPC
            # py3xui знает, где находятся все настройки, включая grpcSettings
            share_link = None
            
            try:
                # Вариант 1: client.get_share_link(inbound_id, uuid) - основной метод py3xui
                if hasattr(self.py3xui_api, 'client') and hasattr(self.py3xui_api.client, 'get_share_link'):
                    try:
                        share_link = await self.py3xui_api.client.get_share_link(inbound_id, uuid)
                        if share_link:
                            logger.debug(f"Got share_link from py3xui client.get_share_link for inbound {inbound_id}")
                    except Exception as e:
                        logger.debug(f"py3xui client.get_share_link failed: {e}")
                
                # Вариант 2: проверяем метод get_share_link на объекте inbound
                if not share_link:
                    inbound_obj = await self.py3xui_api.inbound.get_by_id(inbound_id)
                    if inbound_obj and hasattr(inbound_obj, 'get_share_link'):
                        try:
                            share_link = await inbound_obj.get_share_link(uuid)
                            if share_link:
                                logger.debug(f"Got share_link from inbound.get_share_link for inbound {inbound_id}")
                        except Exception as e:
                            logger.debug(f"inbound.get_share_link failed: {e}")
                
                if share_link:
                    # Парсим ссылку от 3X-UI и извлекаем параметры для использования при ручном построении (если нужно)
                    parsed_params_from_3xui = _parse_vless_link(share_link)
                    logger.info(f"_get_client_share_link_async: Parsed params from 3X-UI link: {parsed_params_from_3xui}")
                    
                    # Заменяем хост на нужный (если указан server_host)
                    if server_host and '127.0.0.1' in share_link:
                        share_link = share_link.replace('127.0.0.1', server_host)
                    elif not server_host:
                        # Оставляем 127.0.0.1 для LinkRewriter
                        pass
                    
                    return share_link
                else:
                    logger.warning(f"_get_client_share_link_async: py3xui get_share_link methods returned None, falling back to manual construction")
            except Exception as e:
                logger.warning(f"py3xui get_share_link methods failed: {e}, falling back to manual construction")
            
            # Если метод py3xui недоступен или вернул None, строим URI вручную
            # Получаем inbound
            inbound = await self.py3xui_api.inbound.get_by_id(inbound_id)
            if not inbound:
                logger.warning(f"Inbound {inbound_id} not found")
                return None
            
            protocol = inbound.protocol.lower() if inbound.protocol else ''
            if protocol != 'vless':
                logger.warning(f"Share link generation for protocol {protocol} not implemented")
                return None
            
            # Определяем хост
            # По умолчанию используем 127.0.0.1 — это внутренний адрес inbound
            # LinkRewriter перепишет его на публичный адрес
            host = server_host
            if not host:
                # Пытаемся извлечь listen адрес из inbound
                if hasattr(inbound, 'listen') and inbound.listen:
                    host = inbound.listen
                else:
                    # По умолчанию используем 127.0.0.1 для работы с reverse proxy
                    host = '127.0.0.1'
            
            port = inbound.port
            remark = inbound.remark or ''
            
            # Извлекаем stream_settings из inbound
            # Источник истины - ТОЛЬКО streamSettings из 3X-UI
            # py3xui может хранить stream_settings как объект StreamSettings с атрибутами
            stream_settings_raw = None
            if hasattr(inbound, 'stream_settings'):
                stream_settings_raw = inbound.stream_settings
            elif hasattr(inbound, 'streamSettings'):
                stream_settings_raw = inbound.streamSettings
            
            # Нормализуем stream_settings в dict (обязательно парсим строку, если пришла)
            # _normalize_stream_settings обрабатывает JSON-строки, объекты Pydantic и dict
            stream_settings = _normalize_stream_settings(stream_settings_raw)
            
            # Валидация: проверяем что stream_settings это dict после нормализации
            if not isinstance(stream_settings, dict):
                logger.error(
                    f"Inbound {inbound_id}: stream_settings is not a dict after normalization. "
                    f"Type: {type(stream_settings)}, value: {stream_settings}"
                )
                raise XUIClientError(f"Inbound {inbound_id}: Failed to normalize stream_settings")
            
            # Логируем для диагностики
            network = stream_settings.get('network', '').lower() if isinstance(stream_settings, dict) else ''
            logger.debug(
                f"_get_client_share_link_async: inbound_id={inbound_id}, network={network}, "
                f"normalized keys={list(stream_settings.keys()) if isinstance(stream_settings, dict) else 'not a dict'}"
            )
            
            # Для gRPC: если grpcSettings не найден в нормализованном dict, пытаемся извлечь из объекта напрямую
            if network == 'grpc' and stream_settings_raw and not isinstance(stream_settings_raw, (dict, str)):
                if 'grpcSettings' not in stream_settings and 'grpc_settings' not in stream_settings:
                    # Проверяем атрибуты объекта через dir()
                    all_attrs = [attr for attr in dir(stream_settings_raw) if not attr.startswith('_')]
                    grpc_attrs = [attr for attr in all_attrs if 'grpc' in attr.lower()]
                    
                    for attr_name in grpc_attrs:
                        try:
                            attr_value = getattr(stream_settings_raw, attr_name)
                            # Нормализуем и добавляем в stream_settings
                            grpc_ss_normalized = _normalize_stream_settings(attr_value)
                            if isinstance(grpc_ss_normalized, dict):
                                if 'grpcSettings' not in stream_settings:
                                    stream_settings['grpcSettings'] = grpc_ss_normalized
                                    logger.debug(f"_get_client_share_link_async: Added grpcSettings from {attr_name}")
                                break
                        except Exception as e:
                            logger.debug(f"_get_client_share_link_async: Failed to get {attr_name}: {e}")
            
            # Извлекаем параметры из stream_settings
            network = stream_settings.get('network', 'tcp')
            security = stream_settings.get('security', 'none')
            
            # Собираем query параметры
            query_params = []
            query_params.append(f"type={network}")
            query_params.append("encryption=none")
            
            # Параметры в зависимости от типа сети
            if network == 'ws':
                ws_settings = stream_settings.get('wsSettings', {})
                path = ws_settings.get('path', '/')
                ws_host = ws_settings.get('headers', {}).get('Host', '')
                query_params.append(f"path={self._url_encode(path)}")
                if ws_host:
                    query_params.append(f"host={ws_host}")
            elif network == 'grpc':
                # Извлекаем serviceName для gRPC - ОБЯЗАТЕЛЬНЫЙ параметр
                inbound_id_for_grpc = inbound.id if hasattr(inbound, 'id') else inbound_id
                service_name = None
                
                # ПРИОРИТЕТ 1: Используем serviceName из ссылки 3X-UI (если есть)
                if parsed_params_from_3xui and 'servicename' in parsed_params_from_3xui:
                    service_name = parsed_params_from_3xui.get('servicename', '')
                    if isinstance(service_name, str):
                        service_name = service_name.strip()
                    if not service_name:
                        service_name = None  # Пустое значение - игнорируем
                    else:
                        logger.debug(f"_get_client_share_link_async: Using serviceName from 3X-UI link: '{service_name}'")
                
                # ПРИОРИТЕТ 2: Если не нашли в ссылке, пытаемся извлечь из stream_settings
                if not service_name:
                    try:
                        service_name = _extract_grpc_service_name(stream_settings, inbound_id_for_grpc)
                        logger.debug(f"_get_client_share_link_async: Extracted grpc serviceName='{service_name}' from stream_settings")
                    except ValueError as e:
                        # serviceName не найден - логируем WARNING и НЕ генерируем ссылку
                        import json
                        try:
                            ss_dump = json.dumps(stream_settings, indent=2, default=str)[:500]
                        except:
                            ss_dump = str(stream_settings)[:500]
                        
                        logger.warning(
                            f"gRPC inbound {inbound_id_for_grpc}: serviceName is EMPTY or not found. "
                            f"Cannot generate valid gRPC VLESS link. "
                            f"stream_settings: {ss_dump}"
                        )
                        # НЕ генерируем ссылку с пустым serviceName
                        raise XUIClientError(
                            f"Inbound {inbound_id_for_grpc}: gRPC serviceName is empty. "
                            f"Cannot generate valid VLESS link without serviceName."
                        )
                
                # ВАЛИДАЦИЯ: serviceName ОБЯЗАТЕЛЬНО должен быть не пустым
                if not service_name or not service_name.strip():
                    logger.warning(
                        f"gRPC inbound {inbound_id_for_grpc}: serviceName is EMPTY after extraction. "
                        f"Skipping gRPC link generation."
                    )
                    raise XUIClientError(
                        f"Inbound {inbound_id_for_grpc}: gRPC serviceName is empty. "
                        f"Cannot generate valid VLESS link without serviceName."
                    )
                
                # Добавляем serviceName в query params
                query_params.append(f"serviceName={service_name}")
                
                # Извлекаем grpcSettings для mode и authority (опциональные)
                grpc_settings = stream_settings.get('grpcSettings') or stream_settings.get('grpc_settings')
                if grpc_settings:
                    if not isinstance(grpc_settings, dict):
                        grpc_settings = _normalize_stream_settings(grpc_settings)
                    
                    if isinstance(grpc_settings, dict):
                        # Извлекаем mode (multi/gun) если есть
                        grpc_mode = grpc_settings.get('multiMode') or grpc_settings.get('multi_mode')
                        if grpc_mode is not None:
                            # multiMode=True -> mode=multi, False -> mode=gun
                            mode_value = 'multi' if grpc_mode else 'gun'
                            query_params.append(f"mode={mode_value}")
                        
                        # Извлекаем authority (опциональный)
                        authority = grpc_settings.get('authority')
                        if authority and isinstance(authority, str) and authority.strip():
                            query_params.append(f"authority={authority}")
            elif network in ('xhttp', 'splithttp'):
                # Извлекаем path: сначала из ссылки 3X-UI, потом из stream_settings
                path = None
                
                # ПРИОРИТЕТ 1: Используем path из ссылки 3X-UI (если есть)
                if parsed_params_from_3xui and 'path' in parsed_params_from_3xui:
                    path = parsed_params_from_3xui['path']
                    logger.debug(f"_get_client_share_link_async: Using path from 3X-UI link: '{path}'")
                
                # ПРИОРИТЕТ 2: Если не нашли в ссылке, пытаемся извлечь из stream_settings
                if not path:
                    try:
                        path = _extract_xhttp_path(stream_settings, inbound_id)
                        logger.debug(f"_get_client_share_link_async: Extracted xhttp path='{path}' from stream_settings")
                    except ValueError as e:
                        logger.error(f"_get_client_share_link_async: Failed to extract xhttp path for inbound {inbound_id}: {e}")
                        raise XUIClientError(f"Inbound {inbound_id}: xhttp path not found in 3X-UI link or stream_settings")
                
                if not path:
                    raise XUIClientError(f"Inbound {inbound_id}: xhttp path is empty")
                
                query_params.append(f"path={self._url_encode(path)}")
                
                # Извлекаем host и mode из xhttpSettings
                xhttp_settings = stream_settings.get('xhttpSettings') or stream_settings.get('xhttp_settings')
                xhttp_host = None
                mode = 'auto'  # Дефолт согласно требованиям
                
                if xhttp_settings:
                    if not isinstance(xhttp_settings, dict):
                        xhttp_settings = _normalize_stream_settings(xhttp_settings)
                    if isinstance(xhttp_settings, dict):
                        # Извлекаем mode из settings или используем дефолт 'auto'
                        mode_val = xhttp_settings.get('mode')
                        if mode_val and isinstance(mode_val, str):
                            mode = mode_val.strip() if mode_val.strip() else 'auto'
                        
                        # Извлекаем host (опциональный)
                        xhttp_host = xhttp_settings.get('host')
                
                # Добавляем параметры в query string
                if xhttp_host and isinstance(xhttp_host, str) and xhttp_host.strip():
                    query_params.append(f"host={xhttp_host}")
                query_params.append(f"mode={mode}")
            elif network == 'tcp':
                tcp_settings = stream_settings.get('tcpSettings', {})
                header_type = tcp_settings.get('header', {}).get('type', 'none')
                if header_type != 'none':
                    query_params.append(f"headerType={header_type}")
            
            # Security параметры
            query_params.append(f"security={security}")
            
            if security == 'tls':
                tls_settings = stream_settings.get('tlsSettings', {})
                sni = tls_settings.get('serverName', '')
                alpn = tls_settings.get('alpn', [])
                fp = tls_settings.get('fingerprint', '')
                if sni:
                    query_params.append(f"sni={sni}")
                if alpn and isinstance(alpn, list):
                    query_params.append(f"alpn={','.join(alpn)}")
                if fp:
                    query_params.append(f"fp={fp}")
            elif security == 'reality':
                reality_settings = stream_settings.get('realitySettings', {})
                pbk = reality_settings.get('publicKey', '')
                fp = reality_settings.get('fingerprint', 'chrome')
                sni = reality_settings.get('serverNames', [''])[0] if reality_settings.get('serverNames') else ''
                sid = reality_settings.get('shortIds', [''])[0] if reality_settings.get('shortIds') else ''
                if pbk:
                    query_params.append(f"pbk={pbk}")
                if sni:
                    query_params.append(f"sni={sni}")
                if fp:
                    query_params.append(f"fp={fp}")
                if sid:
                    query_params.append(f"sid={sid}")
            
            # Собираем ссылку
            query_string = '&'.join(query_params)
            uri = f"vless://{uuid}@{host}:{port}?{query_string}"
            
            # Добавляем remark как fragment (URL-encoded)
            if remark:
                uri += f"#{self._url_encode(remark)}"
            
            # Проверяем корректность URI в зависимости от типа сети
            if network == 'xhttp':
                # Проверяем, что path содержит /xhttp/ и не равен "/"
                path_match = re.search(r'path=([^&]*)', uri)
                if path_match:
                    path_value = path_match.group(1)
                    # Декодируем URL-encoded значение для проверки
                    decoded_path = unquote(path_value)
                    
                    # Проверяем, что path содержит /xhttp/ и не равен "/"
                    if '/xhttp/' not in decoded_path or decoded_path == '/':
                        logger.error(f"Inbound {inbound_id}: Generated xhttp URI missing valid path. URI: {uri[:200]}...")
                        raise XUIClientError(
                            f"Inbound {inbound_id}: Generated xhttp URI is invalid - path must contain '/xhttp/' and not be '/'. "
                            f"Current path: '{decoded_path}'. Please check inbound configuration in 3X-UI."
                        )
                else:
                    logger.error(f"Inbound {inbound_id}: Generated xhttp URI missing path parameter. URI: {uri[:200]}...")
                    raise XUIClientError(
                        f"Inbound {inbound_id}: Generated xhttp URI is invalid - path parameter is missing. "
                        f"Please check inbound configuration in 3X-UI."
                    )
            elif network == 'grpc':
                # Проверяем, что serviceName присутствует И не пустой
                service_name_match = re.search(r'serviceName=([^&#]*)', uri)
                if not service_name_match:
                    logger.error(f"Inbound {inbound_id}: Generated grpc URI missing serviceName parameter. URI: {uri[:200]}...")
                    raise XUIClientError(
                        f"Inbound {inbound_id}: Generated grpc URI is invalid - serviceName parameter is missing. "
                        f"Please check inbound configuration in 3X-UI."
                    )
                # Проверяем что serviceName не пустой
                service_name_value = service_name_match.group(1)
                if not service_name_value or not service_name_value.strip():
                    logger.error(f"Inbound {inbound_id}: Generated grpc URI has EMPTY serviceName. URI: {uri[:200]}...")
                    raise XUIClientError(
                        f"Inbound {inbound_id}: Generated grpc URI is invalid - serviceName is EMPTY. "
                        f"Please check inbound configuration in 3X-UI."
                    )
            
            return uri
            
        except Exception as e:
            logger.error(f"Failed to get share link: {e}", exc_info=True)
            return None
    
    def _url_encode(self, value: str) -> str:
        """URL-кодирует строку для использования в URI"""
        from urllib.parse import quote
        return quote(value, safe='')
    
    def get_client_share_link(
        self,
        inbound_id: int,
        uuid: str,
        server_host: Optional[str] = None
    ) -> Optional[str]:
        """
        Получает share link для клиента.
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
            server_host: Хост сервера для ссылки (если None, извлекается из base_url)
        
        Returns:
            Share link или None если не удалось получить
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(self._get_client_share_link_async(inbound_id, uuid, server_host))
    
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
                # Извлекаем stream_settings и нормализуем
                # Источник истины - ТОЛЬКО streamSettings из 3X-UI
                stream_settings_raw = None
                if hasattr(inbound, 'stream_settings'):
                    stream_settings_raw = inbound.stream_settings
                elif hasattr(inbound, 'streamSettings'):
                    stream_settings_raw = inbound.streamSettings
                
                # Нормализуем stream_settings в dict (обязательно парсим строку, если пришла)
                stream_settings = _normalize_stream_settings(stream_settings_raw)
                
                # Для gRPC: проверяем объект stream_settings_raw напрямую после нормализации
                # py3xui может не возвращать grpcSettings в нормализованном dict
                network = stream_settings.get('network', '').lower() if isinstance(stream_settings, dict) else ''
                if network == 'grpc' and stream_settings_raw:
                    logger.info(f"get_inbound: gRPC inbound - checking stream_settings_raw for grpcSettings")
                    # Проверяем через dir() для всех атрибутов
                    all_attrs = [attr for attr in dir(stream_settings_raw) if not attr.startswith('_')]
                    grpc_attrs = [attr for attr in all_attrs if 'grpc' in attr.lower()]
                    if grpc_attrs:
                        logger.info(f"get_inbound: Found grpc-related attributes: {grpc_attrs}")
                        for attr_name in grpc_attrs:
                            try:
                                attr_value = getattr(stream_settings_raw, attr_name)
                                logger.info(f"get_inbound: {attr_name} = {type(attr_value)}, value: {attr_value}")
                                # Нормализуем и добавляем
                                grpc_ss_normalized = _normalize_stream_settings(attr_value)
                                if isinstance(grpc_ss_normalized, dict):
                                    if 'grpcSettings' not in stream_settings:
                                        stream_settings['grpcSettings'] = grpc_ss_normalized
                                        logger.info(f"get_inbound: Added grpcSettings from {attr_name}: {grpc_ss_normalized}")
                            except Exception as e:
                                logger.debug(f"get_inbound: Failed to get {attr_name}: {e}")
                
                # Логируем для отладки
                network = stream_settings.get('network', 'unknown') if isinstance(stream_settings, dict) else 'unknown'
                logger.info(
                    f"get_inbound: inbound_id={inbound_id}, protocol={inbound.protocol or 'unknown'}, "
                    f"network={network}, remark={inbound.remark or 'no remark'}"
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"get_inbound: extracted stream_settings keys: {list(stream_settings.keys()) if isinstance(stream_settings, dict) else 'not a dict'}")
                    if isinstance(stream_settings, dict):
                        if 'xhttpSettings' in stream_settings:
                            xhttp_ss = stream_settings['xhttpSettings']
                            if isinstance(xhttp_ss, dict):
                                logger.debug(f"get_inbound: xhttpSettings keys: {list(xhttp_ss.keys())}, path: {xhttp_ss.get('path', 'NOT FOUND')}")
                        if 'grpcSettings' in stream_settings:
                            grpc_ss = stream_settings['grpcSettings']
                            if isinstance(grpc_ss, dict):
                                logger.debug(f"get_inbound: grpcSettings keys: {list(grpc_ss.keys())}, serviceName: {grpc_ss.get('serviceName', 'NOT FOUND')}")
                
                # Извлекаем listen адрес
                listen = ''
                if hasattr(inbound, 'listen'):
                    listen = inbound.listen or ''
                
                return {
                    'id': inbound.id,
                    'remark': inbound.remark or '',
                    'protocol': inbound.protocol or '',
                    'port': inbound.port,
                    'listen': listen,
                    'enable': inbound.enable if hasattr(inbound, 'enable') else True,
                    'settings': inbound.settings.dict() if hasattr(inbound.settings, 'dict') else {},
                    'stream_settings': stream_settings,
                    'streamSettings': stream_settings  # Для совместимости
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
        Строит полный VLESS URI для клиента на основе inbound.
        
        Извлекает все параметры из stream_settings для построения рабочей ссылки.
        
        Args:
            inbound: Словарь с данными inbound (должен содержать stream_settings)
            client_uuid: UUID клиента
            host: Хост сервера (если не указан, извлекается из base_url)
        
        Returns:
            Полный VLESS URI или None
        """
        try:
            protocol = inbound.get('protocol', '').lower()
            if protocol != 'vless':
                logger.warning(f"build_vless_uri called for non-VLESS protocol: {protocol}")
                return None
            
            port = inbound.get('port')
            if not port:
                logger.warning("Port not found in inbound")
                return None
            
            remark = inbound.get('remark', '')
            
            # Определяем хост
            # По умолчанию используем 127.0.0.1 — это внутренний адрес inbound
            # LinkRewriter перепишет его на публичный адрес
            server_host = host
            if not server_host:
                # Пытаемся извлечь listen адрес из inbound
                listen_addr = inbound.get('listen', '')
                if listen_addr:
                    server_host = listen_addr
                else:
                    # По умолчанию используем 127.0.0.1 для работы с reverse proxy
                    server_host = '127.0.0.1'
            
            # Извлекаем и нормализуем stream_settings
            # Источник истины - ТОЛЬКО streamSettings из 3X-UI
            stream_settings_raw = inbound.get('stream_settings', inbound.get('streamSettings', {}))
            # Нормализуем stream_settings в dict (обязательно парсим строку, если пришла)
            stream_settings = _normalize_stream_settings(stream_settings_raw)
            
            # Извлекаем параметры
            network = stream_settings.get('network', 'tcp')
            security = stream_settings.get('security', 'none')
            
            # Собираем query параметры
            query_params = []
            query_params.append(f"type={network}")
            query_params.append("encryption=none")
            
            # Параметры в зависимости от типа сети
            if network == 'ws':
                ws_settings = stream_settings.get('wsSettings', {})
                if not isinstance(ws_settings, dict):
                    ws_settings = {}
                path = ws_settings.get('path', '/')
                ws_host = ws_settings.get('headers', {}).get('Host', '') if isinstance(ws_settings.get('headers'), dict) else ''
                query_params.append(f"path={self._url_encode(path)}")
                if ws_host:
                    query_params.append(f"host={ws_host}")
            elif network == 'grpc':
                # Извлекаем serviceName - ОБЯЗАТЕЛЬНЫЙ параметр для gRPC
                inbound_id_for_error = inbound.get('id', 'unknown')
                logger.debug(f"build_vless_uri: Extracting grpc serviceName for inbound {inbound_id_for_error}")
                
                try:
                    service_name = _extract_grpc_service_name(stream_settings, inbound_id_for_error)
                    logger.debug(f"build_vless_uri: Successfully extracted grpc serviceName='{service_name}' for inbound {inbound_id_for_error}")
                except ValueError as e:
                    # serviceName не найден - логируем WARNING с dump stream_settings
                    import json
                    try:
                        ss_dump = json.dumps(stream_settings, indent=2, default=str)[:500]
                    except:
                        ss_dump = str(stream_settings)[:500]
                    
                    logger.warning(
                        f"build_vless_uri: gRPC inbound {inbound_id_for_error}: serviceName is EMPTY or not found. "
                        f"Cannot generate valid gRPC VLESS link. "
                        f"stream_settings: {ss_dump}"
                    )
                    return None
                
                # ВАЛИДАЦИЯ: serviceName ОБЯЗАТЕЛЬНО должен быть не пустым
                if not service_name or not service_name.strip():
                    logger.warning(
                        f"build_vless_uri: gRPC inbound {inbound_id_for_error}: serviceName is EMPTY. "
                        f"Skipping gRPC link generation."
                    )
                    return None
                
                query_params.append(f"serviceName={service_name}")
                
                # Извлекаем grpcSettings для mode и authority (опциональные)
                grpc_settings = stream_settings.get('grpcSettings') or stream_settings.get('grpc_settings')
                if grpc_settings:
                    if not isinstance(grpc_settings, dict):
                        grpc_settings = _normalize_stream_settings(grpc_settings)
                    
                    if isinstance(grpc_settings, dict):
                        # Извлекаем mode (multi/gun) если есть
                        grpc_mode = grpc_settings.get('multiMode') or grpc_settings.get('multi_mode')
                        if grpc_mode is not None:
                            mode_value = 'multi' if grpc_mode else 'gun'
                            query_params.append(f"mode={mode_value}")
                        
                        # Извлекаем authority (опциональный)
                        authority = grpc_settings.get('authority')
                        if authority and isinstance(authority, str) and authority.strip():
                            query_params.append(f"authority={authority}")
            elif network in ('xhttp', 'splithttp'):
                # Извлекаем path с альтернативами и проверками
                inbound_id = inbound.get('id', 'unknown')
                try:
                    path = _extract_xhttp_path(stream_settings, inbound_id)
                    query_params.append(f"path={self._url_encode(path)}")
                except ValueError as e:
                    # Если path не найден или равен "/" - возвращаем None
                    logger.error(f"build_vless_uri: Failed to extract xhttp path: {e}")
                    return None
                
                # Извлекаем host и mode (опциональные)
                xhttp_keys = ['xhttpSettings', 'xhttp_settings', 'splithttpSettings', 'splithttp_settings']
                xhttp_host = None
                mode = 'auto'
                
                for key in xhttp_keys:
                    xhttp_settings = stream_settings.get(key)
                    if xhttp_settings:
                        if not isinstance(xhttp_settings, dict):
                            xhttp_settings = _normalize_stream_settings(xhttp_settings)
                        if isinstance(xhttp_settings, dict):
                            if not xhttp_host:
                                xhttp_host = xhttp_settings.get('host')
                            if mode == 'auto':
                                mode_val = xhttp_settings.get('mode')
                                if mode_val:
                                    mode = mode_val
                
                if xhttp_host and isinstance(xhttp_host, str) and xhttp_host.strip():
                    query_params.append(f"host={xhttp_host}")
                query_params.append(f"mode={mode}")
            elif network == 'tcp':
                tcp_settings = stream_settings.get('tcpSettings', {})
                header_type = tcp_settings.get('header', {}).get('type', 'none')
                if header_type != 'none':
                    query_params.append(f"headerType={header_type}")
            
            # Security параметры
            query_params.append(f"security={security}")
            
            if security == 'tls':
                tls_settings = stream_settings.get('tlsSettings', {})
                sni = tls_settings.get('serverName', '')
                alpn = tls_settings.get('alpn', [])
                fp = tls_settings.get('fingerprint', '')
                if sni:
                    query_params.append(f"sni={sni}")
                if alpn and isinstance(alpn, list):
                    query_params.append(f"alpn={','.join(alpn)}")
                if fp:
                    query_params.append(f"fp={fp}")
            elif security == 'reality':
                reality_settings = stream_settings.get('realitySettings', {})
                pbk = reality_settings.get('publicKey', '')
                fp = reality_settings.get('fingerprint', 'chrome')
                sni = reality_settings.get('serverNames', [''])[0] if reality_settings.get('serverNames') else ''
                sid = reality_settings.get('shortIds', [''])[0] if reality_settings.get('shortIds') else ''
                if pbk:
                    query_params.append(f"pbk={pbk}")
                if sni:
                    query_params.append(f"sni={sni}")
                if fp:
                    query_params.append(f"fp={fp}")
                if sid:
                    query_params.append(f"sid={sid}")
            
            # Собираем ссылку
            query_string = '&'.join(query_params)
            uri = f"vless://{client_uuid}@{server_host}:{port}?{query_string}"
            
            # Добавляем remark как fragment (URL-encoded)
            if remark:
                uri += f"#{self._url_encode(remark)}"
            
            # Проверяем корректность URI в зависимости от типа сети
            inbound_id = inbound.get('id', 'unknown')
            if network == 'xhttp':
                # Проверяем, что path содержит /xhttp/ и не равен "/"
                path_match = re.search(r'path=([^&]*)', uri)
                if path_match:
                    path_value = path_match.group(1)
                    decoded_path = unquote(path_value)
                    
                    if '/xhttp/' not in decoded_path or decoded_path == '/':
                        logger.error(f"build_vless_uri: Inbound {inbound_id}: Generated xhttp URI missing valid path. URI: {uri[:200]}..., decoded_path: '{decoded_path}'")
                        return None
                else:
                    logger.error(f"build_vless_uri: Inbound {inbound_id}: Generated xhttp URI missing path parameter. URI: {uri[:200]}...")
                    return None
            elif network == 'grpc':
                # Проверяем, что serviceName присутствует И не пустой
                service_name_match = re.search(r'serviceName=([^&#]*)', uri)
                if not service_name_match:
                    logger.error(f"build_vless_uri: Inbound {inbound_id}: Generated grpc URI missing serviceName parameter. URI: {uri[:200]}...")
                    return None
                # Проверяем что serviceName не пустой
                service_name_value = service_name_match.group(1)
                if not service_name_value or not service_name_value.strip():
                    logger.error(f"build_vless_uri: Inbound {inbound_id}: Generated grpc URI has EMPTY serviceName. URI: {uri[:200]}...")
                    return None
            
            return uri
            
        except Exception as e:
            logger.error(f"Failed to build VLESS URI: {e}", exc_info=True)
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
