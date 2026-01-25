#!/usr/bin/env python3
"""
3X-UI Official API Client
Использует только официальные эндпоинты из Postman коллекции:
https://www.postman.com/hsanaei/3x-ui/collection/q1l5l0u/3x-ui

Все запросы используют HTTPS и соответствуют официальной документации API.
"""

import asyncio
import logging
import json
import time
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse
from datetime import datetime

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    httpx = None
    HTTPX_AVAILABLE = False
    raise ImportError("httpx library is required. Install it with: pip install httpx")

logger = logging.getLogger(__name__)


class XUIAPIError(Exception):
    """Базовое исключение для 3X-UI API"""
    pass


class XUIAPIAuthError(XUIAPIError):
    """Ошибка аутентификации"""
    pass


class XUIAPIConnectionError(XUIAPIError):
    """Ошибка подключения к 3X-UI"""
    pass


class XUIAPIClient:
    """
    Клиент для работы с официальным API 3X-UI.
    
    Использует только официальные эндпоинты из Postman коллекции:
    - POST /login - авторизация
    - GET /panel/api/inbounds/list - список inbounds
    - GET /panel/api/inbounds/get/{id} - получить inbound
    - POST /panel/api/inbounds/add - добавить inbound
    - POST /panel/api/inbounds/update/{id} - обновить inbound
    - POST /panel/api/inbounds/delete/{id} - удалить inbound
    - GET /panel/api/clients/{clientId} - получить клиента
    - POST /panel/api/clients/add - добавить клиента
    - POST /panel/api/clients/update/{clientId} - обновить клиента
    - POST /panel/api/clients/delete/{clientId} - удалить клиента
    """
    
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        base_path: str = "/",
        timeout: int = 10,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        verify_ssl: bool = True,
        force_https: bool = True
    ):
        """
        Инициализация клиента.
        
        Args:
            host: Хост 3X-UI (например, "https://panel.example.com:5560")
            username: Имя пользователя 3X-UI
            password: Пароль 3X-UI
            base_path: Базовый путь панели (по умолчанию "/")
            timeout: Таймаут запросов в секундах
            max_retries: Максимальное количество попыток при ошибках
            retry_delay: Задержка между попытками в секундах
            verify_ssl: Проверять SSL сертификат
            force_https: Принудительно использовать HTTPS
        """
        if not username or not password:
            raise ValueError("Username and password are required")
        
        # SSL настройки
        self.verify_ssl = verify_ssl
        self.force_https = force_https
        
        # Нормализуем host (добавляем https:// если нет схемы)
        parsed = urlparse(host)
        if not parsed.scheme:
            host = f"https://{host}"
        elif parsed.scheme == 'http' and force_https:
            host = host.replace('http://', 'https://', 1)
            logger.info(f"Forced HTTPS for host: {host}")
        
        # Сохраняем оригинальный host без base_path
        self.original_host = host.rstrip('/')
        self.base_path = base_path.rstrip('/') if base_path else '/'
        
        # Формируем base_url с учётом base_path
        # Если base_path указан и не равен "/", добавляем его к host
        if self.base_path and self.base_path != '/':
            self.base_url = self.original_host.rstrip('/') + '/' + self.base_path.lstrip('/')
        else:
            self.base_url = self.original_host
        
        self.username = username
        self.password = password
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # HTTP клиент с connection pooling
        self._http_client: Optional[httpx.AsyncClient] = None
        self._http_client_loop: Optional[asyncio.AbstractEventLoop] = None
        self._cookies: Optional[Dict[str, str]] = None
        self._last_login_time: Optional[datetime] = None
        self._login_cache_duration = 3600  # 1 час
        
        logger.info(
            f"XUIAPIClient initialized: host={self.original_host}, "
            f"base_path={self.base_path}, base_url={self.base_url}, "
            f"verify_ssl={self.verify_ssl}, force_https={self.force_https}"
        )
        
        # Дополнительное логирование для диагностики
        if self.base_path and self.base_path != '/':
            logger.info(f"Using custom base_path: {self.base_path}, login will be at: {self.base_url}")
        else:
            logger.info(f"Using default base_path (/), login will be at: {self.base_url}")
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """Возвращает HTTP клиент с connection pooling"""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            # Нет запущенного loop - создаем клиент без проверки
            current_loop = None
        
        # Проверяем, нужно ли пересоздать клиент
        need_new_client = (
            self._http_client is None or 
            self._http_client.is_closed or
            (current_loop is not None and self._http_client_loop is not None and 
             self._http_client_loop is not current_loop)
        )
        
        if need_new_client:
            # Закрываем старый клиент, если он существует
            if self._http_client and not self._http_client.is_closed:
                try:
                    await self._http_client.aclose()
                except Exception as e:
                    logger.debug(f"Error closing old HTTP client: {e}")
            
            # Создаем новый клиент
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                verify=self.verify_ssl,
                follow_redirects=True,
                http2=True,
                limits=httpx.Limits(
                    max_keepalive_connections=5,
                    max_connections=10,
                    keepalive_expiry=30.0
                )
            )
            self._http_client_loop = current_loop
            logger.debug(f"Created new HTTP client for {self.base_url} (loop={id(current_loop) if current_loop else 'None'})")
        
        return self._http_client
    
    async def _close_http_client(self):
        """Закрывает HTTP клиент"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
    
    def close(self):
        """Закрывает все соединения"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._close_http_client())
            else:
                loop.run_until_complete(self._close_http_client())
        except Exception as e:
            logger.warning(f"Error closing HTTP client: {e}")
    
    async def _request_with_retry(
        self,
        method: str,
        url: str,
        cookies: Optional[Dict[str, str]] = None,
        json_data: Optional[Dict] = None,
        data: Optional[Dict] = None,
        **kwargs
    ) -> Optional[httpx.Response]:
        """
        Выполняет HTTP запрос с повторными попытками и экспоненциальной задержкой.
        """
        client = await self._get_http_client()
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                if method.upper() == 'GET':
                    response = await client.get(url, cookies=cookies, **kwargs)
                elif method.upper() == 'POST':
                    if json_data is not None:
                        response = await client.post(url, cookies=cookies, json=json_data, **kwargs)
                    else:
                        response = await client.post(url, cookies=cookies, data=data, **kwargs)
                else:
                    response = await client.request(method, url, cookies=cookies, json=json_data, **kwargs)
                
                # Успешный ответ
                if response.status_code in (200, 201):
                    return response
                
                # Ошибка авторизации - не повторяем
                if response.status_code in (401, 403):
                    logger.warning(f"Auth error {response.status_code} for {url}")
                    return response
                
                # Серверная ошибка - повторяем
                if response.status_code >= 500:
                    logger.warning(
                        f"Server error {response.status_code} for {url}, "
                        f"attempt {attempt + 1}/{self.max_retries}"
                    )
                    last_error = f"HTTP {response.status_code}"
                else:
                    return response
                    
            except httpx.TimeoutException as e:
                last_error = f"Timeout: {e}"
                logger.warning(f"Timeout for {url}, attempt {attempt + 1}/{self.max_retries}")
            except httpx.ConnectError as e:
                last_error = f"Connection error: {e}"
                logger.warning(f"Connection error for {url}, attempt {attempt + 1}/{self.max_retries}")
            except Exception as e:
                last_error = f"Error: {e}"
                logger.warning(f"Request error for {url}: {e}, attempt {attempt + 1}/{self.max_retries}")
            
            # Экспоненциальная задержка перед повтором
            if attempt < self.max_retries - 1:
                delay = self.retry_delay * (2 ** attempt)
                await asyncio.sleep(delay)
        
        logger.error(f"All {self.max_retries} attempts failed for {url}: {last_error}")
        return None
    
    async def login(self) -> bool:
        """
        Авторизация в 3X-UI через официальный эндпоинт POST /login.
        
        Returns:
            True если авторизация успешна
        
        Raises:
            XUIAPIAuthError: При ошибке аутентификации
        """
        # Проверяем кэш авторизации
        if self._cookies and self._last_login_time:
            elapsed = (datetime.now() - self._last_login_time).total_seconds()
            if elapsed < self._login_cache_duration:
                logger.debug("Using cached login credentials")
                return True
        
        # Формируем URL для логина
        # Согласно документации API: путь /login/ (с завершающим слэшем)
        # Например: если base_path="/vpn", то login_url = "host/vpn/login/"
        # Если base_path="/", то login_url = "host/login/"
        login_url = f"{self.base_url.rstrip('/')}/login/"
        
        logger.info(f"Attempting login to: {login_url} (base_url={self.base_url}, base_path={self.base_path})")
        
        try:
            client = await self._get_http_client()
            
            # Отправляем данные как JSON согласно документации API
            response = await client.post(
                login_url,
                json={
                    "username": self.username,
                    "password": self.password
                },
                headers={
                    "Content-Type": "application/json"
                }
            )
            
            logger.info(f"Login response: status={response.status_code}, url={login_url}")
            
            if response.status_code != 200:
                # Логируем больше информации для диагностики
                response_text = response.text[:500] if response.text else 'No response body'
                error_msg = f"Login failed: status={response.status_code}, url={login_url}, response={response_text}"
                logger.error(error_msg)
                logger.error(f"Login attempt details: base_path={self.base_path}, base_url={self.base_url}, original_host={self.original_host}")
                raise XUIAPIAuthError(error_msg)
            
            # Сохраняем cookies
            self._cookies = dict(client.cookies)
            if not self._cookies:
                error_msg = "Login returned no cookies"
                logger.error(error_msg)
                raise XUIAPIAuthError(error_msg)
            
            self._last_login_time = datetime.now()
            logger.info(f"Successfully logged in to {login_url}")
            return True
            
        except XUIAPIAuthError:
            raise
        except Exception as e:
            error_msg = f"Login error: {e}"
            logger.error(error_msg)
            raise XUIAPIAuthError(error_msg) from e
    
    async def _ensure_logged_in(self):
        """Убеждается что пользователь авторизован"""
        if not self._cookies or not self._last_login_time:
            await self.login()
        else:
            elapsed = (datetime.now() - self._last_login_time).total_seconds()
            if elapsed >= self._login_cache_duration:
                await self.login()
    
    def _extract_api_obj(self, response_json: Any) -> Any:
        """Извлекает объект из ответа API"""
        if isinstance(response_json, dict):
            for key in ('obj', 'data', 'result'):
                if key in response_json:
                    return response_json.get(key)
        return response_json
    
    def _build_api_url(self, api_path: str) -> str:
        """
        Формирует полный URL для API эндпоинта с учётом base_path.
        
        Args:
            api_path: Путь API (например, "panel/api/inbounds/list")
        
        Returns:
            Полный URL для API эндпоинта
        
        Примеры:
            - Если base_path = "/vpn", то "panel/api/inbounds/list" -> "https://host:port/vpn/panel/api/inbounds/list"
            - Если base_path = "/", то "panel/api/inbounds/list" -> "https://host:port/panel/api/inbounds/list"
        """
        # base_path уже включен в base_url, просто добавляем api_path
        # Например: base_url = "https://host:port/vpn", api_path = "panel/api/inbounds/list"
        # Результат: "https://host:port/vpn/panel/api/inbounds/list"
        url = f"{self.base_url.rstrip('/')}/{api_path.lstrip('/')}"
        return url
    
    # ========================================================================
    # INBOUNDS API
    # ========================================================================
    
    async def get_inbounds_list(self) -> List[Dict[str, Any]]:
        """
        Получает список всех inbounds.
        Эндпоинт: GET /panel/api/inbounds/list
        
        Returns:
            Список inbounds
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url("panel/api/inbounds/list")
        logger.debug(f"Getting inbounds list from: {url}")
        response = await self._request_with_retry('GET', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            raise XUIAPIConnectionError(f"Failed to get inbounds list: status={response.status_code if response else 'No response'}")
        
        data = response.json()
        obj = self._extract_api_obj(data)
        
        if isinstance(obj, list):
            return obj
        elif isinstance(obj, dict) and 'obj' in obj:
            return obj['obj'] if isinstance(obj['obj'], list) else []
        
        return []
    
    async def get_inbound(self, inbound_id: int) -> Optional[Dict[str, Any]]:
        """
        Получает inbound по ID.
        Эндпоинт: GET /panel/api/inbounds/get/{id}
        
        Args:
            inbound_id: ID inbound
        
        Returns:
            Inbound или None если не найден
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url(f"panel/api/inbounds/get/{inbound_id}")
        response = await self._request_with_retry('GET', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.warning(f"Failed to get inbound {inbound_id}: status={response.status_code if response else 'No response'}")
            return None
        
        data = response.json()
        obj = self._extract_api_obj(data)
        
        if isinstance(obj, dict):
            return obj
        return None
    
    async def add_inbound(self, inbound_data: Dict[str, Any]) -> bool:
        """
        Добавляет новый inbound.
        Эндпоинт: POST /panel/api/inbounds/add
        
        Args:
            inbound_data: Данные inbound
        
        Returns:
            True если успешно
        """
        await self._ensure_logged_in()
        
        url = f"{self.base_url.rstrip('/')}/panel/api/inbounds/add"
        response = await self._request_with_retry('POST', url, cookies=self._cookies, json_data=inbound_data)
        
        if not response or response.status_code != 200:
            logger.error(f"Failed to add inbound: status={response.status_code if response else 'No response'}")
            return False
        
        result = response.json()
        return result.get('success', False)
    
    async def update_inbound(self, inbound_id: int, inbound_data: Dict[str, Any]) -> bool:
        """
        Обновляет inbound.
        Эндпоинт: POST /panel/api/inbounds/update/{id}
        
        Args:
            inbound_id: ID inbound
            inbound_data: Данные для обновления
        
        Returns:
            True если успешно
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url(f"panel/api/inbounds/update/{inbound_id}")
        response = await self._request_with_retry('POST', url, cookies=self._cookies, json_data=inbound_data)
        
        if not response or response.status_code != 200:
            logger.error(f"Failed to update inbound {inbound_id}: status={response.status_code if response else 'No response'}")
            return False
        
        result = response.json()
        return result.get('success', False)
    
    async def delete_inbound(self, inbound_id: int) -> bool:
        """
        Удаляет inbound.
        Эндпоинт: POST /panel/api/inbounds/delete/{id}
        
        Args:
            inbound_id: ID inbound
        
        Returns:
            True если успешно
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url(f"panel/api/inbounds/delete/{inbound_id}")
        response = await self._request_with_retry('POST', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.error(f"Failed to delete inbound {inbound_id}: status={response.status_code if response else 'No response'}")
            return False
        
        result = response.json()
        return result.get('success', False)
    
    # ========================================================================
    # CLIENTS API
    # ========================================================================
    
    async def get_client(self, client_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает клиента по ID или email.
        Эндпоинт: GET /panel/api/clients/{clientId}
        
        Args:
            client_id: ID или email клиента
        
        Returns:
            Клиент или None если не найден
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url(f"panel/api/clients/{client_id}")
        response = await self._request_with_retry('GET', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.warning(f"Failed to get client {client_id}: status={response.status_code if response else 'No response'}")
            return None
        
        data = response.json()
        obj = self._extract_api_obj(data)
        
        if isinstance(obj, dict):
            return obj
        return None
    
    async def add_client(self, inbound_id: int, client_data: Dict[str, Any]) -> bool:
        """
        Добавляет клиента в inbound.
        Использует эндпоинт: POST /panel/api/inbounds/update/{id}
        (клиенты добавляются через обновление inbound)
        
        Args:
            inbound_id: ID inbound
            client_data: Данные клиента
        
        Returns:
            True если успешно
        """
        # Получаем текущий inbound
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            logger.error(f"Inbound {inbound_id} not found")
            return False
        
        # Парсим settings
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        clients = settings.get('clients', [])
        
        # Проверяем, не существует ли уже клиент
        client_id = client_data.get('id') or client_data.get('uuid')
        client_email = client_data.get('email')
        
        for existing_client in clients:
            if existing_client.get('id') == client_id or existing_client.get('email') == client_email:
                logger.warning(f"Client {client_id} already exists in inbound {inbound_id}")
                return False
        
        # Добавляем нового клиента
        clients.append(client_data)
        settings['clients'] = clients
        
        # Обновляем inbound
        update_data = inbound.copy()
        update_data['settings'] = json.dumps(settings) if isinstance(settings, dict) else settings
        
        return await self.update_inbound(inbound_id, update_data)
    
    async def update_client(self, inbound_id: int, client_id: str, client_data: Dict[str, Any]) -> bool:
        """
        Обновляет клиента в inbound.
        Использует эндпоинт: POST /panel/api/inbounds/update/{id}
        
        Args:
            inbound_id: ID inbound
            client_id: ID клиента
            client_data: Новые данные клиента
        
        Returns:
            True если успешно
        """
        # Получаем текущий inbound
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            logger.error(f"Inbound {inbound_id} not found")
            return False
        
        # Парсим settings
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        clients = settings.get('clients', [])
        
        # Находим и обновляем клиента
        updated = False
        for i, client in enumerate(clients):
            if client.get('id') == client_id or client.get('email') == client_id:
                clients[i] = {**client, **client_data}
                updated = True
                break
        
        if not updated:
            logger.warning(f"Client {client_id} not found in inbound {inbound_id}")
            return False
        
        # Обновляем inbound
        update_data = inbound.copy()
        update_data['settings'] = json.dumps(settings) if isinstance(settings, dict) else settings
        
        return await self.update_inbound(inbound_id, update_data)
    
    async def delete_client(self, inbound_id: int, client_id: str) -> bool:
        """
        Удаляет клиента из inbound.
        Использует эндпоинт: POST /panel/api/inbounds/update/{id}
        
        Args:
            inbound_id: ID inbound
            client_id: ID клиента (UUID) или email
        
        Returns:
            True если успешно
        """
        # Получаем текущий inbound
        inbound = await self.get_inbound(inbound_id)
        if not inbound:
            logger.error(f"Inbound {inbound_id} not found")
            return False
        
        # Парсим settings
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        clients = settings.get('clients', [])
        
        # Логируем для отладки
        logger.debug(f"Deleting client {client_id} from inbound {inbound_id}. Total clients: {len(clients)}")
        if clients:
            logger.debug(f"Existing client IDs: {[c.get('id') for c in clients]}")
            logger.debug(f"Existing client emails: {[c.get('email') for c in clients]}")
        
        # Ищем клиента по id или email
        original_count = len(clients)
        client_found = False
        removed_client_info = None
        
        # Пробуем найти по точному совпадению id или email
        for c in clients:
            client_id_value = c.get('id')
            client_email_value = c.get('email')
            
            # Проверяем точное совпадение
            if client_id_value == client_id or client_email_value == client_id:
                removed_client_info = f"id={client_id_value}, email={client_email_value}"
                # Удаляем найденного клиента (правильная логика удаления)
                clients = [cl for cl in clients if cl.get('id') != client_id_value or cl.get('email') != client_email_value]
                client_found = True
                logger.info(f"Found client by exact match: {removed_client_info}")
                break
        
        if not client_found:
            logger.warning(f"Client {client_id} not found in inbound {inbound_id} by exact match (id or email)")
            # Не обновляем inbound, если клиент не найден
            return False
        
        # Обновляем inbound с удаленным клиентом
        update_data = inbound.copy()
        # Убеждаемся, что settings - это словарь перед сериализацией
        if isinstance(settings, dict):
            # Обновляем список клиентов в settings
            settings['clients'] = clients
            update_data['settings'] = json.dumps(settings)
        else:
            # Если settings уже строка, парсим, обновляем и сериализуем обратно
            if isinstance(settings, str):
                settings_dict = json.loads(settings)
                settings_dict['clients'] = clients
                update_data['settings'] = json.dumps(settings_dict)
            else:
                update_data['settings'] = settings
        
        logger.debug(f"Updating inbound {inbound_id} with {len(clients)} clients (removed 1 client)")
        
        result = await self.update_inbound(inbound_id, update_data)
        if result:
            logger.info(f"Successfully removed client {client_id} from inbound {inbound_id} ({removed_client_info})")
        else:
            logger.error(f"Failed to update inbound {inbound_id} after removing client {client_id}")
        
        return result
    
    async def get_client_share_link(self, client_id: str) -> Optional[str]:
        """
        Получает share link для клиента.
        Использует эндпоинт: GET /panel/api/clients/{clientId}/share
        
        Args:
            client_id: ID или email клиента
        
        Returns:
            Share link или None
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url(f"panel/api/clients/{client_id}/share")
        response = await self._request_with_retry('GET', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.warning(f"Failed to get share link for client {client_id}: status={response.status_code if response else 'No response'}")
            return None
        
        data = response.json()
        obj = self._extract_api_obj(data)
        
        if isinstance(obj, dict):
            return obj.get('link') or obj.get('shareLink')
        elif isinstance(obj, str):
            return obj
        
        return None
    
    async def reset_client_stat(self, client_id: str) -> bool:
        """
        Сбрасывает статистику клиента.
        Эндпоинт: POST /panel/api/clients/{clientId}/resetStat
        
        Args:
            client_id: ID клиента
        
        Returns:
            True если успешно
        """
        await self._ensure_logged_in()
        
        url = f"{self.base_url.rstrip('/')}/panel/api/clients/{client_id}/resetStat"
        response = await self._request_with_retry('POST', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.error(f"Failed to reset client stat {client_id}: status={response.status_code if response else 'No response'}")
            return False
        
        result = response.json()
        return result.get('success', False)
    
    async def reset_client_ips(self, client_id: str) -> bool:
        """
        Сбрасывает IP адреса клиента.
        Эндпоинт: POST /panel/api/clients/{clientId}/resetIps
        
        Args:
            client_id: ID клиента
        
        Returns:
            True если успешно
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url(f"panel/api/clients/{client_id}/resetIps")
        response = await self._request_with_retry('POST', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.error(f"Failed to reset client IPs {client_id}: status={response.status_code if response else 'No response'}")
            return False
        
        result = response.json()
        return result.get('success', False)
    
    async def get_client_ips(self, client_id: str) -> Optional[List[str]]:
        """
        Получает IP адреса клиента (используется для определения онлайна).
        Эндпоинт: GET /panel/api/clients/{clientId}/ips
        
        Args:
            client_id: ID или email клиента
        
        Returns:
            Список IP адресов или None
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url(f"panel/api/clients/{client_id}/ips")
        response = await self._request_with_retry('GET', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.warning(f"Failed to get client IPs {client_id}: status={response.status_code if response else 'No response'}")
            return None
        
        data = response.json()
        obj = self._extract_api_obj(data)
        
        if isinstance(obj, list):
            return obj
        elif isinstance(obj, dict) and 'ips' in obj:
            return obj['ips']
        
        return None
    
    async def get_online_clients(self) -> List[Dict[str, Any]]:
        """
        Получает список онлайн клиентов через все inbounds.
        Эндпоинт: POST /panel/api/inbounds/onlines
        
        Returns:
            Список онлайн клиентов с их данными
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url("panel/api/inbounds/onlines")
        response = await self._request_with_retry('POST', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.warning(f"Failed to get online clients: status={response.status_code if response else 'No response'}")
            return []
        
        data = response.json()
        obj = self._extract_api_obj(data)
        
        if isinstance(obj, list):
            return obj
        elif isinstance(obj, dict):
            # Может быть структура с ключами 'clients', 'onlines', или другим
            if 'clients' in obj:
                return obj['clients']
            elif 'onlines' in obj:
                return obj['onlines']
            elif 'data' in obj:
                return obj['data'] if isinstance(obj['data'], list) else []
        
        return []
    
    async def is_client_online(self, client_id: str) -> bool:
        """
        Проверяет, онлайн ли клиент.
        
        Args:
            client_id: ID или email клиента
        
        Returns:
            True если клиент онлайн
        """
        try:
            # Сначала пробуем получить IP адреса клиента
            # Если клиент онлайн, у него должны быть IP адреса
            try:
                ips = await self.get_client_ips(client_id)
                if ips and len(ips) > 0:
                    logger.debug(f"Client {client_id} is online (has {len(ips)} IPs)")
                    return True
            except Exception as e:
                logger.debug(f"Could not get IPs for {client_id}: {e}")
            
            # Если IP нет, проверяем через список онлайн клиентов
            # Это резервный метод, если get_client_ips не работает
            try:
                online_clients = await self.get_online_clients()
                logger.debug(f"Checking {len(online_clients)} online clients for {client_id}")
                for client in online_clients:
                    client_email = client.get('email', '')
                    client_id_value = client.get('id', '')
                    # Проверяем по email и по ID
                    if client_email == client_id or client_id_value == client_id:
                        logger.debug(f"Client {client_id} found in online clients list")
                        return True
            except Exception as e:
                logger.warning(f"Could not get online clients list: {e}")
            
            logger.debug(f"Client {client_id} is offline")
            return False
        except Exception as e:
            logger.warning(f"Error checking client online status {client_id}: {e}", exc_info=True)
            return False
    
    # ========================================================================
    # STATISTICS API
    # ========================================================================
    
    async def reset_inbounds_stat(self) -> bool:
        """
        Сбрасывает статистику всех inbounds.
        Эндпоинт: POST /panel/api/inbounds/resetStat
        
        Returns:
            True если успешно
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url("panel/api/inbounds/resetStat")
        response = await self._request_with_retry('POST', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.error(f"Failed to reset inbounds stat: status={response.status_code if response else 'No response'}")
            return False
        
        result = response.json()
        return result.get('success', False)
    
    async def reset_inbound_stat(self, inbound_id: int) -> bool:
        """
        Сбрасывает статистику inbound.
        Эндпоинт: POST /panel/api/inbounds/{id}/resetStat
        
        Args:
            inbound_id: ID inbound
        
        Returns:
            True если успешно
        """
        await self._ensure_logged_in()
        
        url = self._build_api_url(f"panel/api/inbounds/{inbound_id}/resetStat")
        response = await self._request_with_retry('POST', url, cookies=self._cookies)
        
        if not response or response.status_code != 200:
            logger.error(f"Failed to reset inbound stat {inbound_id}: status={response.status_code if response else 'No response'}")
            return False
        
        result = response.json()
        return result.get('success', False)
