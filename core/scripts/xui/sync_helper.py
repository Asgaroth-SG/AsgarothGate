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

# Импортируем настройку логирования (с обработкой ошибок)
try:
    from xui.logging_config import setup_xui_logging
    setup_xui_logging()
except (ImportError, Exception) as e:
    # Если не удалось импортировать, используем базовое логирование
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


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
            logger.debug(f"X-UI sync is disabled, skipping sync for user {username}")
            return True  # Синхронизация отключена
        
        logger.info(f"Syncing user {username} with X-UI (plan: {user_plan}, expiry: {expiry_days} days, traffic: {traffic_limit_gb} GB)")
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
        else:
            logger.info(f"X-UI sync successful for user {username}")
        
        return True
    
    except Exception as e:
        import traceback
        logger.error(f"X-UI sync error for user {username}: {e}\n{traceback.format_exc()}")
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
