#!/usr/bin/env python3
"""
Конфигурация интеграции с X-UI/3X-UI.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from dotenv import dotenv_values

logger = logging.getLogger(__name__)

# Путь к конфигурационному файлу X-UI
XUI_CONFIG_PATH = Path("/etc/hysteria/xui_config.json")
XUI_ENV_PATH = Path("/etc/hysteria/.xui.env")


def load_xui_config() -> Dict[str, Any]:
    """
    Загружает конфигурацию X-UI из файла или переменных окружения.
    
    Приоритет:
    1. Файл xui_config.json
    2. Переменные окружения (.xui.env или системные)
    3. Значения по умолчанию
    
    Returns:
        Словарь с конфигурацией
    """
    config = {
        'enabled': False,
        'mode': 'single-xui',
        'xui_servers': [],
        'inbound_filter': {}
    }
    
    # Пытаемся загрузить из JSON файла
    if XUI_CONFIG_PATH.exists():
        try:
            with open(XUI_CONFIG_PATH, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                config.update(file_config)
                logger.info(f"Loaded X-UI config from {XUI_CONFIG_PATH}")
                return config
        except Exception as e:
            logger.warning(f"Failed to load X-UI config from file: {e}")
    
    # Пытаемся загрузить из .env файла
    env_vars = {}
    if XUI_ENV_PATH.exists():
        env_vars = dotenv_values(XUI_ENV_PATH)
    
    # Также проверяем системные переменные окружения
    for key, value in os.environ.items():
        if key.startswith('XUI_'):
            env_vars[key] = value
    
    # Парсим переменные окружения
    if env_vars.get('XUI_ENABLED', '').lower() in ('true', '1', 'yes'):
        config['enabled'] = True
    
    config['mode'] = env_vars.get('XUI_MODE', 'single-xui')
    
    # Парсим серверы
    # Формат: XUI_HOST, XUI_USERNAME, XUI_PASSWORD, XUI_BASE_PATH, XUI_API_TOKEN, XUI_AUTH_TYPE
    # Или для multi: XUI_SERVER_1_HOST, XUI_SERVER_1_USERNAME, etc.
    if env_vars.get('XUI_HOST'):
        server = {
            'host': env_vars.get('XUI_HOST', ''),
            'username': env_vars.get('XUI_USERNAME', ''),
            'password': env_vars.get('XUI_PASSWORD', ''),
            'base_path': env_vars.get('XUI_BASE_PATH', '/'),
            'timeout': int(env_vars.get('XUI_TIMEOUT', '10')),
            'max_retries': int(env_vars.get('XUI_MAX_RETRIES', '3')),
            'api_token': env_vars.get('XUI_API_TOKEN'),
            'auth_type': env_vars.get('XUI_AUTH_TYPE', 'auto')
        }
        if server['host']:
            config['xui_servers'].append(server)
    
    # Multi-XUI режим
    i = 1
    while True:
        host_key = f'XUI_SERVER_{i}_HOST'
        if host_key not in env_vars:
            break
        
        server = {
            'host': env_vars.get(host_key, ''),
            'username': env_vars.get(f'XUI_SERVER_{i}_USERNAME', ''),
            'password': env_vars.get(f'XUI_SERVER_{i}_PASSWORD', ''),
            'base_path': env_vars.get(f'XUI_SERVER_{i}_BASE_PATH', '/'),
            'timeout': int(env_vars.get(f'XUI_SERVER_{i}_TIMEOUT', '10')),
            'max_retries': int(env_vars.get(f'XUI_SERVER_{i}_MAX_RETRIES', '3')),
            'api_token': env_vars.get(f'XUI_SERVER_{i}_API_TOKEN'),
            'auth_type': env_vars.get(f'XUI_SERVER_{i}_AUTH_TYPE', 'auto')
        }
        if server['host']:
            config['xui_servers'].append(server)
        i += 1
    
    # Фильтр inbounds
    if env_vars.get('XUI_INBOUND_PROTOCOL'):
        config['inbound_filter']['protocol'] = env_vars.get('XUI_INBOUND_PROTOCOL')
    if env_vars.get('XUI_INBOUND_TAG'):
        config['inbound_filter']['tag'] = env_vars.get('XUI_INBOUND_TAG')
    if env_vars.get('XUI_INBOUND_REMARK'):
        config['inbound_filter']['remark'] = env_vars.get('XUI_INBOUND_REMARK')
    
    return config


def get_xui_sync_manager():
    """
    Создает и возвращает менеджер синхронизации X-UI.
    
    Returns:
        XUISyncManager или None если синхронизация отключена или нет валидных серверов
    """
    try:
        import sys
        from pathlib import Path
        
        # Добавляем путь к модулям для импорта
        sys.path.insert(0, str(Path(__file__).parent.parent))
        
        from xui.xui_sync import XUISyncConfig, XUISyncManager
        
        config_dict = load_xui_config()
        
        # Проверяем, что синхронизация включена
        if not config_dict.get('enabled', False):
            return None
        
        # Проверяем наличие хотя бы одного валидного сервера
        servers = config_dict.get('xui_servers', [])
        if not servers:
            logger.warning("X-UI sync enabled but no servers configured")
            return None
        
        # Проверяем, что есть хотя бы один включенный сервер с валидными данными
        has_valid_server = False
        for server in servers:
            if not server.get('enabled', True):
                continue
            
            host = server.get('host', '').strip()
            if not host:
                continue
            
            auth_type = server.get('auth_type', 'username')
            password = server.get('password', '').strip()
            
            if auth_type == 'token':
                if password:
                    has_valid_server = True
                    break
            else:
                username = server.get('username', '').strip()
                if username and password:
                    has_valid_server = True
                    break
        
        if not has_valid_server:
            logger.warning("X-UI sync enabled but no valid enabled servers found")
            return None
        
        config = XUISyncConfig(config_dict)
        return XUISyncManager(config)
    
    except Exception as e:
        logger.error(f"Failed to create X-UI sync manager: {e}")
        return None
