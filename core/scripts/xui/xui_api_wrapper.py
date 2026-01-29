#!/usr/bin/env python3
"""
Wrapper для XUIAPIClient, обеспечивающий совместимость с текущим интерфейсом XUIClient.
Это позволяет постепенно мигрировать на официальное API без изменения остального кода.
"""

import asyncio
import logging
import json
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

from xui.xui_api_client import XUIAPIClient, XUIAPIError, XUIAPIAuthError, XUIAPIConnectionError

logger = logging.getLogger(__name__)


class XUIAPIWrapper:
    """
    Wrapper для XUIAPIClient, обеспечивающий совместимость с интерфейсом XUIClient.
    
    Этот класс предоставляет те же методы, что и XUIClient, но использует
    только официальное API 3X-UI из Postman коллекции.
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
        Инициализация wrapper.
        
        Параметры совпадают с XUIClient для совместимости.
        """
        self.api_client = XUIAPIClient(
            host=host,
            username=username,
            password=password,
            base_path=base_path,
            timeout=timeout,
            max_retries=max_retries,
            retry_delay=retry_delay,
            verify_ssl=verify_ssl,
            force_https=force_https
        )
        
        self.base_url = self.api_client.base_url
        self._logged_in = False
    
    def _run_async_in_sync_context(self, coro):
        """
        Запускает корутину в синхронном или асинхронном контексте.
        Работает как в обычном синхронном коде, так и в уже запущенном event loop (FastAPI).
        """
        try:
            loop = asyncio.get_running_loop()
            # Если loop уже запущен, используем nest_asyncio
            try:
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(coro)
            except ImportError:
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
                    return future.result(timeout=30)
        except RuntimeError:
            # Loop не запущен - можно использовать asyncio.run() или существующий loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    # Loop закрыт, создаем новый через asyncio.run()
                    return asyncio.run(coro)
                else:
                    # Loop существует, но не запущен - используем его
                    return loop.run_until_complete(coro)
            except RuntimeError:
                # Нет loop вообще - создаем новый через asyncio.run()
                return asyncio.run(coro)
    
    def login(self) -> bool:
        """
        Синхронная авторизация (совместимость с XUIClient).
        
        Returns:
            True если авторизация успешна
        """
        try:
            result = self._run_async_in_sync_context(self.api_client.login())
            self._logged_in = result
            return result
        except XUIAPIConnectionError as e:
            logger.error(f"Login failed: {e}")
            self._logged_in = False
            return False
        except XUIAPIAuthError as e:
            logger.error(f"Login failed: {e}")
            self._logged_in = False
            return False
    
    def ensure_logged_in(self):
        """Убеждается что пользователь авторизован"""
        if not self._logged_in:
            self.login()
    
    def get_inbound(self, inbound_id: int) -> Optional[Dict[str, Any]]:
        """
        Получает inbound по ID (совместимость с XUIClient).
        
        Args:
            inbound_id: ID inbound
        
        Returns:
            Inbound или None
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(self.api_client.get_inbound(inbound_id))
    
    def get_inbounds_list(self) -> List[Dict[str, Any]]:
        """
        Получает список всех inbounds (совместимость с XUIClient).
        
        Returns:
            Список inbounds
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(self.api_client.get_inbounds_list())
    
    def list_inbounds(self) -> List[Dict[str, Any]]:
        """
        Получает список всех inbounds (альтернативное имя для совместимости).
        
        Returns:
            Список inbounds
        """
        return self.get_inbounds_list()
    
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
            tag: Тег inbound
            remark: Замечание/название inbound
        
        Returns:
            Отфильтрованный список inbounds
        """
        all_inbounds = self.get_inbounds_list()
        
        filtered = []
        for inbound in all_inbounds:
            # Проверяем фильтры
            if protocol and inbound.get('protocol', '').lower() != protocol.lower():
                continue
            if tag and inbound.get('tag') != tag:
                continue
            if remark and inbound.get('remark') != remark:
                continue
            
            filtered.append(inbound)
        
        return filtered
    
    def upsert_client(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: bool = True,
        username: Optional[str] = None,
        limit_ip: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Создает или обновляет клиента (совместимость с XUIClient).
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
            expiry_time: Время истечения (timestamp в миллисекундах)
            traffic_limit: Лимит трафика в байтах
            enable: Включен ли клиент
            username: Имя пользователя (для email)
            limit_ip: Лимит количества IP-адресов (0 = без ограничений)
        
        Returns:
            Tuple (is_updated: bool, action: str)
        """
        self.ensure_logged_in()
        
        # Формируем email
        email = f"{username}_{inbound_id}" if username else f"{uuid}_{inbound_id}"
        
        # Формируем данные клиента
        client_data = {
            'id': uuid,
            'email': email,
            'enable': enable
        }
        
        if expiry_time is not None:
            # Проверяем формат (миллисекунды или секунды)
            if expiry_time < 1000000000000:  # Если меньше этого, значит секунды
                expiry_time = expiry_time * 1000
            client_data['expiryTime'] = expiry_time
        
        if traffic_limit is not None:
            # Используем totalGB в байтах (как в текущей реализации)
            client_data['totalGB'] = traffic_limit
        
        if limit_ip is not None:
            # Добавляем лимит IP-адресов (0 = без ограничений)
            client_data['limitIp'] = limit_ip
        
        # Проверяем, существует ли клиент
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            logger.error(f"Inbound {inbound_id} not found")
            return False, "inbound not found"
        
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            import json
            settings = json.loads(settings)
        
        clients = settings.get('clients', [])
        client_exists = any(
            c.get('id') == uuid or c.get('email') == email
            for c in clients
        )
        
        if client_exists:
            # Обновляем существующего клиента
            result = self._run_async_in_sync_context(
                self.api_client.update_client(inbound_id, uuid, client_data)
            )
            return result, "updated"
        else:
            # Создаем нового клиента
            result = self._run_async_in_sync_context(
                self.api_client.add_client(inbound_id, client_data)
            )
            return result, "created"
    
    async def _upsert_client_async(
        self,
        inbound_id: int,
        uuid: str,
        expiry_time: Optional[int] = None,
        traffic_limit: Optional[int] = None,
        enable: bool = True,
        email: Optional[str] = None,
        username: Optional[str] = None,
        limit_ip: Optional[int] = None
    ) -> Tuple[bool, str]:
        """
        Асинхронная версия upsert_client (для совместимости с xui_sync).
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
            expiry_time: Время истечения (timestamp в миллисекундах)
            traffic_limit: Лимит трафика в байтах
            enable: Включен ли клиент
            email: Email клиента (опционально)
            username: Имя пользователя (для email)
            limit_ip: Лимит количества IP-адресов (0 = без ограничений)
        
        Returns:
            Tuple (is_updated: bool, action: str)
        """
        await self.api_client._ensure_logged_in()
        
        # Формируем email
        if not email:
            email = f"{username}_{inbound_id}" if username else f"{uuid}_{inbound_id}"
        
        # Формируем данные клиента
        client_data = {
            'id': uuid,
            'email': email,
            'enable': enable
        }
        
        if expiry_time is not None:
            # Проверяем формат (миллисекунды или секунды)
            if expiry_time < 1000000000000:  # Если меньше этого, значит секунды
                expiry_time = expiry_time * 1000
            client_data['expiryTime'] = expiry_time
        
        if traffic_limit is not None:
            # Используем totalGB в байтах (как в текущей реализации)
            client_data['totalGB'] = traffic_limit
        
        if limit_ip is not None:
            # Добавляем лимит IP-адресов (0 = без ограничений)
            client_data['limitIp'] = limit_ip
        
        # Проверяем, существует ли клиент
        inbound = await self.api_client.get_inbound(inbound_id)
        if not inbound:
            logger.error(f"Inbound {inbound_id} not found")
            return False, "inbound not found"
        
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            import json
            settings = json.loads(settings)
        
        clients = settings.get('clients', [])
        client_exists = any(
            c.get('id') == uuid or c.get('email') == email
            for c in clients
        )
        
        if client_exists:
            # Обновляем существующего клиента
            result = await self.api_client.update_client(inbound_id, uuid, client_data)
            return result, "updated"
        else:
            # Создаем нового клиента
            result = await self.api_client.add_client(inbound_id, client_data)
            return result, "created"
    
    def delete_client(self, inbound_id: int, uuid: str) -> bool:
        """
        Удаляет клиента (совместимость с XUIClient).
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
        
        Returns:
            True если успешно
        """
        self.ensure_logged_in()
        return self._run_async_in_sync_context(
            self.api_client.delete_client(inbound_id, uuid)
        )
    
    def get_client_share_link(self, inbound_id: int, uuid: str) -> Optional[str]:
        """
        Получает share link для клиента (совместимость с XUIClient).
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
        
        Returns:
            Share link или None
        """
        self.ensure_logged_in()
        
        # Формируем client_id (может быть UUID или email)
        inbound = self.get_inbound(inbound_id)
        if not inbound:
            return None
        
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            import json
            settings = json.loads(settings)
        
        clients = settings.get('clients', [])
        for client in clients:
            if client.get('id') == uuid:
                client_email = client.get('email')
                if client_email:
                    return self._run_async_in_sync_context(
                        self.api_client.get_client_share_link(inbound_id, client_email)
                    )
                break
        
        # Fallback: используем UUID
        return self._run_async_in_sync_context(
            self.api_client.get_client_share_link(inbound_id, uuid)
        )
    
    async def _get_client_share_link_async(self, inbound_id: int, uuid: str) -> Optional[str]:
        """
        Асинхронная версия get_client_share_link (для совместимости с xui_public_links).
        
        Args:
            inbound_id: ID inbound
            uuid: UUID клиента
        
        Returns:
            Share link или None
        """
        await self.api_client._ensure_logged_in()
        
        # Формируем client_id (может быть UUID или email)
        inbound = await self.api_client.get_inbound(inbound_id)
        if not inbound:
            return None
        
        settings = inbound.get('settings', {})
        if isinstance(settings, str):
            import json
            settings = json.loads(settings)
        
        clients = settings.get('clients', [])
        for client in clients:
            if client.get('id') == uuid:
                client_email = client.get('email')
                if client_email:
                    # Используем email как client_id для API
                    return await self.api_client.get_client_share_link(client_email)
                break
        
        # Fallback: используем UUID
        return await self.api_client.get_client_share_link(uuid)
    
    def check_health(self) -> Tuple[bool, str]:
        """
        Проверяет доступность сервера (совместимость с XUIClient).
        
        Returns:
            Tuple (is_healthy: bool, message: str)
        """
        try:
            self.ensure_logged_in()
            # Просто проверяем доступность, не возвращаем количество inbounds
            return True, "Сервер Online"
        except Exception as e:
            return False, f"Error: {str(e)}"
    
    def get_client_ips(self, client_id: str) -> Optional[List[str]]:
        """
        Получает IP адреса клиента (используется для определения онлайна).
        
        Args:
            client_id: ID или email клиента
        
        Returns:
            Список IP адресов или None
        """
        return self._run_async_in_sync_context(
            self.api_client.get_client_ips(client_id)
        )
    
    def get_online_clients(self) -> List[Dict[str, Any]]:
        """
        Получает список онлайн клиентов.
        
        Returns:
            Список онлайн клиентов с их данными (может быть список объектов или список строк)
        """
        return self._run_async_in_sync_context(
            self.api_client.get_online_clients()
        )
    
    def get_online_clients_detailed(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Получает детальный список онлайн клиентов через проверку всех inbounds.
        Используется когда /panel/api/inbounds/onlines возвращает только строки.
        
        Returns:
            Словарь {inbound_id: [список онлайн клиентов]}
        """
        return self._run_async_in_sync_context(
            self.api_client.get_online_clients_detailed()
        )
    
    def is_client_online(self, client_id: str) -> bool:
        """
        Проверяет, онлайн ли клиент.
        
        Args:
            client_id: ID или email клиента
        
        Returns:
            True если клиент онлайн
        """
        return self._run_async_in_sync_context(
            self.api_client.is_client_online(client_id)
        )
    
    def get_client_traffics(self, client_uuid: str) -> List[Dict[str, Any]]:
        """
        Получает статистику трафика клиента по UUID из всех inbounds.
        
        Args:
            client_uuid: UUID клиента
        
        Returns:
            Список объектов с трафиком клиента из всех inbounds
        """
        return self._run_async_in_sync_context(
            self.api_client.get_client_traffics(client_uuid)
        )
    
    def close(self):
        """Закрывает все соединения"""
        self.api_client.close()
    
    def restart_xray_service(self) -> Dict[str, Any]:
        """
        Перезапускает X-Ray сервис в 3X-UI.
        
        Returns:
            dict с результатом перезапуска
        """
        return self._run_async_in_sync_context(self.api_client.restart_xray_service())