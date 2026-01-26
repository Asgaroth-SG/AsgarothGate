#!/usr/bin/env python3
"""
Хелпер для синхронизации пользователей с X-UI.
Используется в скриптах add_user.py, edit_user.py, remove_user.py
"""

import logging
import sys
from pathlib import Path

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent.parent))

from xui.config import get_xui_sync_manager

logger = logging.getLogger(__name__)


def sync_user_create(username: str, expiry_days: int, traffic_limit_gb: int, enable: bool = True, user_plan: str = "standard") -> bool:
    """
    Синхронизирует создание пользователя с X-UI.
    
    Args:
        username: Имя пользователя
        expiry_days: Дни до истечения
        traffic_limit_gb: Лимит трафика в GB
        enable: Включен ли пользователь
        user_plan: План пользователя (standard/premium)
    
    Returns:
        True если синхронизация успешна или отключена
    """
    try:
        sync_manager = get_xui_sync_manager()
        if not sync_manager:
            return True  # Синхронизация отключена
        
        success, error = sync_manager.sync_user_create(
            hysteria_username=username,
            expiry_days=expiry_days,
            traffic_limit_gb=traffic_limit_gb,
            enable=enable,
            user_plan=user_plan
        )
        
        if not success:
            logger.warning(f"X-UI sync failed for user {username}: {error}")
            # Не блокируем создание пользователя, только логируем
        
        return True
    
    except Exception as e:
        logger.error(f"X-UI sync error for user {username}: {e}")
        return True  # Не блокируем создание пользователя


def sync_user_update(
    username: str,
    expiry_days: int = None,
    traffic_limit_gb: int = None,
    enable: bool = None,
    user_plan: str = None
) -> bool:
    """
    Синхронизирует обновление пользователя с X-UI.
    
    Args:
        username: Имя пользователя
        expiry_days: Новые дни до истечения (None = не менять)
        traffic_limit_gb: Новый лимит трафика в GB (None = не менять)
        enable: Новый статус включения (None = не менять)
        user_plan: Новый план пользователя (None = не менять)
    
    Returns:
        True если синхронизация успешна или отключена
    """
    try:
        sync_manager = get_xui_sync_manager()
        if not sync_manager:
            return True
        
        success, error = sync_manager.sync_user_update(
            hysteria_username=username,
            expiry_days=expiry_days,
            traffic_limit_gb=traffic_limit_gb,
            enable=enable,
            user_plan=user_plan
        )
        
        if not success:
            logger.warning(f"X-UI sync failed for user {username}: {error}")
        
        return True
    
    except Exception as e:
        logger.error(f"X-UI sync error for user {username}: {e}")
        return True


def sync_user_delete(username: str) -> bool:
    """
    Синхронизирует удаление пользователя с X-UI.
    
    Args:
        username: Имя пользователя
    
    Returns:
        True если синхронизация успешна или отключена
    """
    try:
        sync_manager = get_xui_sync_manager()
        if not sync_manager:
            return True
        
        success, error = sync_manager.sync_user_delete(
            hysteria_username=username
        )
        
        if not success:
            logger.warning(f"X-UI sync failed for user {username}: {error}")
        
        return True
    
    except Exception as e:
        logger.error(f"X-UI sync error for user {username}: {e}")
        return True


def restart_xray_services() -> bool:
    """
    Перезапускает X-Ray сервисы во всех настроенных 3X-UI панелях.
    
    Returns:
        True если перезапуск успешен или отключен
    """
    try:
        sync_manager = get_xui_sync_manager()
        if not sync_manager:
            return True  # Синхронизация отключена
        
        # Получаем все серверы из конфигурации
        from xui.config import load_xui_config
        config = load_xui_config()
        
        if not config.get('enabled') or not config.get('xui_servers'):
            return True
        
        restarted_count = 0
        errors = []
        
        for server_config in config.get('xui_servers', []):
            if not server_config.get('enabled', True):
                continue
            
            try:
                from xui.xui_api_wrapper import XUIAPIWrapper
                
                # Определяем тип авторизации
                auth_type = server_config.get('auth_type', 'username')
                if auth_type == 'token':
                    # Для token используем специальную логику
                    password = server_config.get('password', '')  # password может быть token
                else:
                    password = server_config.get('password', '')
                
                client = XUIAPIWrapper(
                    host=server_config['host'],
                    username=server_config.get('username', ''),
                    password=password,
                    base_path=server_config.get('base_path', '/'),
                    timeout=server_config.get('timeout', 10),
                    verify_ssl=server_config.get('verify_ssl', True),
                    force_https=server_config.get('force_https', True)
                )
                
                # Авторизуемся
                if not client.login():
                    errors.append(f"Failed to login to {server_config.get('name', server_config['host'])}")
                    continue
                
                # Перезапускаем X-Ray
                result = client.restart_xray_service()
                if result.get('success'):
                    restarted_count += 1
                    logger.info(f"X-Ray restarted on {server_config.get('name', server_config['host'])}: {result.get('msg', '')}")
                else:
                    errors.append(f"Failed to restart X-Ray on {server_config.get('name', server_config['host'])}: {result.get('msg', 'Unknown error')}")
                
                client.close()
                
            except Exception as e:
                server_name = server_config.get('name', server_config.get('host', 'unknown'))
                logger.error(f"Error restarting X-Ray on {server_name}: {e}")
                errors.append(f"{server_name}: {str(e)}")
        
        if errors:
            logger.warning(f"Some X-Ray services failed to restart: {errors}")
        
        if restarted_count > 0:
            logger.info(f"Successfully restarted X-Ray on {restarted_count} server(s)")
        
        return restarted_count > 0 or len(errors) == 0
    
    except Exception as e:
        logger.error(f"Error restarting X-Ray services: {e}")
        return True  # Не блокируем процесс
