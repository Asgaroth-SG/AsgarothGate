#!/usr/bin/env python3
"""
Пример интеграции нового XUIAPIClient в существующий код.

Этот файл показывает, как можно постепенно мигрировать на официальное API 3X-UI.
"""

from xui.xui_api_wrapper import XUIAPIWrapper
from xui.xui_client import XUIClient  # Старый клиент
from xui.config import load_xui_config


def create_xui_client(server_config: dict):
    """
    Создаёт клиент X-UI в зависимости от конфигурации.
    
    Если в конфигурации указано use_official_api=True, использует новый клиент.
    Иначе использует старый клиент для обратной совместимости.
    
    Args:
        server_config: Конфигурация сервера из xui_config.json
    
    Returns:
        XUIAPIWrapper или XUIClient
    """
    use_official_api = server_config.get('use_official_api', False)
    
    if use_official_api:
        # Используем новый клиент на официальном API
        logger.info(f"Using official API client for {server_config.get('host')}")
        return XUIAPIWrapper(
            host=server_config.get('host'),
            username=server_config.get('username'),
            password=server_config.get('password'),
            base_path=server_config.get('base_path', '/'),
            timeout=server_config.get('timeout', 10),
            max_retries=server_config.get('max_retries', 3),
            verify_ssl=server_config.get('verify_ssl', True),
            force_https=server_config.get('force_https', True)
        )
    else:
        # Используем старый клиент (обратная совместимость)
        logger.info(f"Using legacy client for {server_config.get('host')}")
        return XUIClient(
            host=server_config.get('host'),
            username=server_config.get('username'),
            password=server_config.get('password'),
            base_path=server_config.get('base_path', '/'),
            timeout=server_config.get('timeout', 10),
            max_retries=server_config.get('max_retries', 3),
            verify_ssl=server_config.get('verify_ssl', True),
            force_https=server_config.get('force_https', True)
        )


# Пример использования в xui_sync.py:
"""
# В методе __init__ класса XUISyncManager:

def __init__(self, config: XUISyncConfig):
    self.config = config
    self.clients: Dict[str, Any] = {}  # Может быть XUIAPIWrapper или XUIClient
    
    if config.enabled:
        for server in config.xui_servers:
            host = server.get('host')
            if not host:
                continue
            
            # Используем новую функцию для создания клиента
            client = create_xui_client(server)
            
            # Остальной код остаётся без изменений
            self.clients[host] = client
"""
