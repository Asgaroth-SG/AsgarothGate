#!/usr/bin/env python3
"""
X-UI/3X-UI API Client
Поддерживает работу с X-UI панелью через HTTP API.
"""

import requests
import time
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta

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


class XUIClient:
    """
    Клиент для работы с X-UI/3X-UI API.
    
    Поддерживает:
    - Логин через cookie-сессию
    - Получение списка inbounds
    - Добавление/обновление/удаление клиентов
    - Получение share links
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
            username: Имя пользователя X-UI (опционально, если используется api_token)
            password: Пароль X-UI (опционально, если используется api_token)
            base_path: Базовый путь панели (по умолчанию "/", может быть "/panel" и т.д.)
            timeout: Таймаут запросов в секундах
            max_retries: Максимальное количество попыток при ошибках
            retry_delay: Задержка между попытками в секундах
            api_token: API токен для авторизации без логина (если используется)
            auth_type: Тип авторизации - "auto" (автоопределение), "login" (через login endpoint), 
                      "token" (через API токен), "basic" (Basic Auth)
        """
        # Нормализуем host (добавляем http:// если нет)
        parsed = urlparse(host)
        if not parsed.scheme:
            host = f"http://{host}"
        
        self.base_url = host.rstrip('/')
        self.base_path = base_path.rstrip('/')
        self.username = username
        self.password = password
        self.api_token = api_token
        self.auth_type = auth_type.lower()
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'AsgarothGate-XUI-Client/1.0',
            'Content-Type': 'application/json'
        })
        
        # Если указан API токен, добавляем его в заголовки
        if self.api_token:
            self.session.headers['Authorization'] = self.api_token
            self._logged_in = True  # Считаем авторизованным при наличии токена
            logger.info("Using API token authentication")
        elif self.auth_type == "basic" and self.username and self.password:
            # Basic Auth
            from requests.auth import HTTPBasicAuth
            self.session.auth = HTTPBasicAuth(self.username, self.password)
            self._logged_in = True
            logger.info("Using Basic Auth authentication")
        else:
            self._logged_in = False
        
        self._last_login_time = None
        self._login_cache_duration = 3600  # 1 час
    
    def _make_url(self, endpoint: str) -> str:
        """Формирует полный URL для запроса"""
        # Убираем ведущий слэш из endpoint
        endpoint = endpoint.lstrip('/')
        # Убираем ведущий слэш из base_path если есть
        base = self.base_path.lstrip('/')
        if base:
            path = f"/{base}/{endpoint}"
        else:
            path = f"/{endpoint}"
        return f"{self.base_url}{path}"
    
    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True
    ) -> Dict[str, Any]:
        """
        Выполняет HTTP запрос с обработкой ошибок и ретраями.
        
        Args:
            method: HTTP метод (GET, POST, etc.)
            endpoint: Endpoint API (например, "login" или "inbound/list")
            data: Тело запроса (будет сериализовано в JSON)
            params: Query параметры
            retry: Нужно ли повторять запрос при ошибках
        
        Returns:
            JSON ответ от сервера
        
        Raises:
            XUIConnectionError: При ошибках подключения
            XUIAuthError: При ошибках аутентификации
            XUIClientError: При других ошибках
        """
        url = self._make_url(endpoint)
        
        for attempt in range(self.max_retries if retry else 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    json=data,
                    params=params,
                    timeout=self.timeout
                )
                
                # Проверяем статус код
                if response.status_code == 401:
                    # Неавторизован - возможно сессия истекла
                    if self._logged_in and endpoint != "login":
                        logger.warning("Session expired, re-login required")
                        self._logged_in = False
                        if retry and attempt < self.max_retries - 1:
                            self.login()
                            continue
                    raise XUIAuthError(f"Authentication failed: {response.text}")
                
                if response.status_code >= 500:
                    # Серверная ошибка - можно повторить
                    if retry and attempt < self.max_retries - 1:
                        logger.warning(f"Server error {response.status_code}, retrying...")
                        time.sleep(self.retry_delay * (attempt + 1))
                        continue
                    raise XUIConnectionError(
                        f"Server error {response.status_code}: {response.text}"
                    )
                
                # Пытаемся распарсить JSON
                try:
                    result = response.json()
                except ValueError:
                    raise XUIClientError(
                        f"Invalid JSON response: {response.text[:200]}"
                    )
                
                # X-UI обычно возвращает {success: bool, msg: str, obj: any}
                if isinstance(result, dict):
                    if not result.get('success', False):
                        error_msg = result.get('msg', 'Unknown error')
                        # Некоторые ошибки не критичны (например, клиент уже существует)
                        if 'already exists' in error_msg.lower() or 'not found' in error_msg.lower():
                            return result
                        raise XUIClientError(f"X-UI API error: {error_msg}")
                
                return result
                
            except requests.exceptions.Timeout:
                if retry and attempt < self.max_retries - 1:
                    logger.warning(f"Request timeout, retrying...")
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                raise XUIConnectionError(f"Request timeout to {url}")
            
            except requests.exceptions.ConnectionError as e:
                if retry and attempt < self.max_retries - 1:
                    logger.warning(f"Connection error, retrying...")
                    time.sleep(self.retry_delay * (attempt + 1))
                    continue
                raise XUIConnectionError(f"Connection error to {url}: {e}")
            
            except (XUIAuthError, XUIClientError):
                raise
            
            except Exception as e:
                raise XUIClientError(f"Unexpected error: {e}")
        
        raise XUIConnectionError(f"Failed after {self.max_retries} attempts")
    
    def login(self) -> bool:
        """
        Выполняет логин в X-UI панель (если требуется).
        
        Returns:
            True если авторизован
        
        Raises:
            XUIAuthError: При ошибке аутентификации
            XUIConnectionError: При ошибке подключения
        """
        # Если уже авторизован через токен или Basic Auth, пропускаем
        if self._logged_in and (self.api_token or self.auth_type == "basic"):
            return True
        
        # Проверяем кэш логина
        if self._logged_in and self._last_login_time:
            elapsed = (datetime.now() - self._last_login_time).total_seconds()
            if elapsed < self._login_cache_duration:
                return True
        
        # Если auth_type = "token" или "basic", логин не требуется
        if self.auth_type in ("token", "basic"):
            return True
        
        # Если нет username/password, логин невозможен
        if not self.username or not self.password:
            if self.api_token:
                return True  # Используем токен
            raise XUIAuthError("Username/password or API token required for authentication")
        
        try:
            response = self._request(
                method='POST',
                endpoint='login',
                data={
                    'username': self.username,
                    'password': self.password
                },
                retry=False  # Логин не повторяем
            )
            
            # X-UI возвращает success: true при успешном логине
            if response.get('success', False):
                self._logged_in = True
                self._last_login_time = datetime.now()
                logger.info("Successfully logged in to X-UI")
                return True
            else:
                raise XUIAuthError(f"Login failed: {response.get('msg', 'Unknown error')}")
        
        except requests.exceptions.RequestException as e:
            raise XUIConnectionError(f"Failed to connect to X-UI: {e}")
    
    def ensure_logged_in(self):
        """Проверяет и при необходимости выполняет логин"""
        if not self._logged_in:
            # Пытаемся авторизоваться только если не используется токен/Basic Auth
            if not (self.api_token or self.auth_type == "basic"):
                self.login()
    
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
        
        response = self._request('POST', 'inbound/list')
        
        # X-UI возвращает {success: true, obj: [{id, remark, protocol, ...}]}
        if response.get('success') and 'obj' in response:
            inbounds = response['obj']
            if isinstance(inbounds, list):
                return inbounds
            return []
        
        return []
    
    def get_inbound(self, inbound_id: int) -> Optional[Dict[str, Any]]:
        """
        Получает информацию о конкретном inbound.
        
        Args:
            inbound_id: ID inbound
        
        Returns:
            Информация об inbound или None
        """
        inbounds = self.list_inbounds()
        for inbound in inbounds:
            if inbound.get('id') == inbound_id:
                return inbound
        return None
    
    def filter_inbounds(
        self,
        protocol: Optional[str] = None,
        tag: Optional[str] = None,
        remark: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Фильтрует inbounds по параметрам.
        
        Args:
            protocol: Протокол (например, "vless")
            tag: Тег inbound
            remark: Замечание/название inbound
        
        Returns:
            Отфильтрованный список inbounds
        """
        inbounds = self.list_inbounds()
        filtered = []
        
        for inbound in inbounds:
            if protocol and inbound.get('protocol', '').lower() != protocol.lower():
                continue
            if tag and inbound.get('tag', '') != tag:
                continue
            if remark and remark.lower() not in inbound.get('remark', '').lower():
                continue
            filtered.append(inbound)
        
        return filtered
    
    def add_client(
        self,
        inbound_id: int,
        uuid: Optional[str] = None,
        email: Optional[str] = None,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: bool = True
    ) -> Dict[str, Any]:
        """
        Добавляет клиента в inbound.
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента (если не указан, будет сгенерирован X-UI)
            email: Email клиента (альтернатива UUID)
            expiry_time: Время истечения в миллисекундах (timestamp)
            traffic_limit: Лимит трафика в байтах
            enable: Включен ли клиент
        
        Returns:
            Информация о созданном клиенте
        
        Raises:
            XUIClientError: При ошибке создания клиента
        """
        self.ensure_logged_in()
        
        # Получаем текущий inbound
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            raise XUIClientError(f"Inbound {inbound_id} not found")
        
        # Получаем текущих клиентов
        clients = inbound.get('settings', {}).get('clients', [])
        if not isinstance(clients, list):
            clients = []
        
        # Формируем нового клиента
        new_client = {
            'enable': enable
        }
        
        if uuid:
            new_client['id'] = uuid
        elif email:
            new_client['email'] = email
        else:
            # Генерируем UUID если не указан
            import uuid as uuid_lib
            new_client['id'] = str(uuid_lib.uuid4())
        
        if expiry_time:
            new_client['expiryTime'] = expiry_time
        
        if traffic_limit is not None:
            new_client['totalGB'] = traffic_limit / (1024 ** 3)  # Конвертируем в GB
        
        # Добавляем клиента в список
        clients.append(new_client)
        
        # Обновляем inbound
        return self.update_inbound_clients(inbound_id, clients)
    
    def update_inbound_clients(
        self,
        inbound_id: int,
        clients: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Обновляет список клиентов в inbound.
        
        Args:
            inbound_id: ID inbound
            clients: Список клиентов
        
        Returns:
            Результат обновления
        """
        self.ensure_logged_in()
        
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            raise XUIClientError(f"Inbound {inbound_id} not found")
        
        # Обновляем settings
        settings = inbound.get('settings', {})
        if not isinstance(settings, dict):
            settings = {}
        
        settings['clients'] = clients
        
        # Формируем данные для обновления
        update_data = {
            'id': inbound_id,
            'settings': settings
        }
        
        # Добавляем другие обязательные поля если они есть
        for key in ['remark', 'protocol', 'port', 'listen']:
            if key in inbound:
                update_data[key] = inbound[key]
        
        response = self._request('POST', 'inbound/update', data=update_data)
        return response
    
    def update_client(
        self,
        inbound_id: int,
        client_uuid: Optional[str] = None,
        client_email: Optional[str] = None,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Обновляет параметры клиента.
        
        Args:
            inbound_id: ID inbound
            client_uuid: UUID клиента для поиска
            client_email: Email клиента для поиска
            expiry_time: Новое время истечения в миллисекундах
            traffic_limit: Новый лимит трафика в байтах
            enable: Новый статус включения
        
        Returns:
            Результат обновления
        
        Raises:
            XUIClientError: Если клиент не найден
        """
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            raise XUIClientError(f"Inbound {inbound_id} not found")
        
        clients = inbound.get('settings', {}).get('clients', [])
        if not isinstance(clients, list):
            clients = []
        
        # Ищем клиента
        client_found = False
        for client in clients:
            match = False
            if client_uuid and client.get('id') == client_uuid:
                match = True
            elif client_email and client.get('email') == client_email:
                match = True
            
            if match:
                client_found = True
                # Обновляем параметры
                if expiry_time is not None:
                    client['expiryTime'] = expiry_time
                if traffic_limit is not None:
                    client['totalGB'] = traffic_limit / (1024 ** 3)
                if enable is not None:
                    client['enable'] = enable
                break
        
        if not client_found:
            raise XUIClientError(
                f"Client not found in inbound {inbound_id} "
                f"(uuid={client_uuid}, email={client_email})"
            )
        
        return self.update_inbound_clients(inbound_id, clients)
    
    def delete_client(
        self,
        inbound_id: int,
        client_uuid: Optional[str] = None,
        client_email: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Удаляет клиента из inbound.
        
        Args:
            inbound_id: ID inbound
            client_uuid: UUID клиента для удаления
            client_email: Email клиента для удаления
        
        Returns:
            Результат удаления
        
        Raises:
            XUIClientError: Если клиент не найден
        """
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            raise XUIClientError(f"Inbound {inbound_id} not found")
        
        clients = inbound.get('settings', {}).get('clients', [])
        if not isinstance(clients, list):
            clients = []
        
        # Фильтруем клиентов
        original_count = len(clients)
        clients = [
            c for c in clients
            if not (
                (client_uuid and c.get('id') == client_uuid) or
                (client_email and c.get('email') == client_email)
            )
        ]
        
        if len(clients) == original_count:
            raise XUIClientError(
                f"Client not found in inbound {inbound_id} "
                f"(uuid={client_uuid}, email={client_email})"
            )
        
        return self.update_inbound_clients(inbound_id, clients)
    
    def get_client_share_link(
        self,
        inbound_id: int,
        client_uuid: Optional[str] = None,
        client_email: Optional[str] = None
    ) -> Optional[str]:
        """
        Получает share link для клиента (если X-UI поддерживает).
        
        Args:
            inbound_id: ID inbound
            client_uuid: UUID клиента
            client_email: Email клиента
        
        Returns:
            Share link или None если не поддерживается
        """
        # X-UI может иметь endpoint для получения share links
        # Это зависит от версии, попробуем стандартный способ
        try:
            self.ensure_logged_in()
            
            # Пытаемся получить через API
            response = self._request(
                'POST',
                'inbound/getClientTraffics',
                data={'id': inbound_id}
            )
            
            # Если есть share link в ответе
            if response.get('success') and 'obj' in response:
                # Ищем клиента и его share link
                # Это зависит от реализации X-UI
                pass
            
        except Exception as e:
            logger.warning(f"Could not get share link: {e}")
        
        return None
    
    def build_vless_uri(
        self,
        inbound: Dict[str, Any],
        client_uuid: Optional[str] = None,
        client_email: Optional[str] = None
    ) -> Optional[str]:
        """
        Собирает VLESS URI из параметров inbound и клиента.
        
        Args:
            inbound: Информация об inbound
            client_uuid: UUID клиента
            client_email: Email клиента
        
        Returns:
            VLESS URI или None если не удалось собрать
        """
        if inbound.get('protocol', '').lower() != 'vless':
            return None
        
        # Используем UUID или email
        client_id = client_uuid or client_email
        if not client_id:
            return None
        
        # Получаем параметры из inbound
        settings = inbound.get('settings', {})
        stream_settings = inbound.get('streamSettings', {})
        
        # Базовые параметры
        address = inbound.get('listen', '0.0.0.0')
        port = inbound.get('port', 443)
        
        # SNI из streamSettings
        sni = None
        if stream_settings:
            tls_settings = stream_settings.get('tlsSettings', {})
            sni = tls_settings.get('serverName')
        
        # Reality параметры (если есть)
        reality_settings = None
        if stream_settings:
            reality_settings = stream_settings.get('realitySettings')
        
        # Flow (если есть)
        flow = None
        clients = settings.get('clients', [])
        for client in clients:
            if (client_uuid and client.get('id') == client_uuid) or \
               (client_email and client.get('email') == client_email):
                flow = client.get('flow')
                break
        
        # Transport (ws, grpc, etc.)
        network = stream_settings.get('network', 'tcp')
        security = stream_settings.get('security', 'none')
        
        # Собираем URI
        # Формат: vless://uuid@address:port?params#remark
        uri = f"vless://{client_id}@{address}:{port}"
        
        params = []
        if flow:
            params.append(f"flow={flow}")
        if security and security != 'none':
            params.append(f"security={security}")
        if network and network != 'tcp':
            params.append(f"type={network}")
        if sni:
            params.append(f"sni={sni}")
        
        # Reality параметры
        if reality_settings:
            public_key = reality_settings.get('publicKey')
            short_id = reality_settings.get('shortIds', [])
            if public_key:
                params.append(f"fp={reality_settings.get('fingerprint', 'chrome')}")
                params.append(f"pbk={public_key}")
                if short_id:
                    params.append(f"sid={short_id[0] if isinstance(short_id, list) else short_id}")
        
        # WebSocket path (если есть)
        if network == 'ws':
            ws_settings = stream_settings.get('wsSettings', {})
            path = ws_settings.get('path', '/')
            if path:
                params.append(f"path={path}")
            headers = ws_settings.get('headers', {})
            host = headers.get('Host')
            if host:
                params.append(f"host={host}")
        
        # gRPC serviceName (если есть)
        if network == 'grpc':
            grpc_settings = stream_settings.get('grpcSettings', {})
            service_name = grpc_settings.get('serviceName')
            if service_name:
                params.append(f"serviceName={service_name}")
        
        if params:
            uri += "?" + "&".join(params)
        
        remark = inbound.get('remark', '')
        if remark:
            uri += f"#{remark}"
        
        return uri
    
    def close(self):
        """Закрывает сессию"""
        self.session.close()
        self._logged_in = False
