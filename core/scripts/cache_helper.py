#!/usr/bin/env python3
"""
Модуль для очистки кэша пользователей при критических действиях.
Используется при блокировке, обновлении и удалении пользователей.
"""

import logging
import os
import json
from typing import Optional

logger = logging.getLogger(__name__)


def clear_user_cache(username: str) -> None:
    """
    Принудительно очищает весь кэш для конкретного пользователя.
    Вызывается при критических действиях (блокировка, обновление, удаление).
    
    Очищает:
    1. Кэш нормализованных подписок (normalsub)
    2. Кэш VLESS ссылок из X-UI (в памяти и файле)
    3. Кэш labeled URIs (Hysteria ссылки)
    
    Args:
        username: Имя пользователя для очистки кэша
    """
    if not username:
        return
    
    username_lower = username.lower()
    logger.info(f"Clearing cache for user: {username_lower}")
    
    # 1. Очистка кэша нормализованных подписок
    try:
        from normalsub.normalsub import HysteriaServer
        # Получаем глобальный экземпляр сервера если доступен
        # Или создаем временный для очистки кэша
        try:
            # Пытаемся получить существующий экземпляр через глобальную переменную
            # Если его нет, создаем временный
            server = getattr(clear_user_cache, '_server_instance', None)
            if server and hasattr(server, 'subscription_manager'):
                subscription_manager = server.subscription_manager
                subscription_manager.clear_normalized_subscription_cache(username_lower)
                logger.debug(f"Cleared normalized subscription cache for {username_lower}")
        except Exception as e:
            logger.debug(f"Could not clear normalized subscription cache: {e}")
    except ImportError:
        logger.debug("normalsub module not available for cache clearing")
    except Exception as e:
        logger.warning(f"Error clearing normalized subscription cache: {e}")
    
    # 2. Очистка кэша VLESS ссылок из X-UI (в памяти и файле)
    try:
        cache_path = os.getenv('XUI_LINKS_CACHE_PATH', '/etc/hysteria/xui_links_cache.json')
        
        # Очищаем кэш в файле
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                # Удаляем записи для пользователя (проверяем оба плана: standard и premium)
                keys_to_remove = []
                for key in cache_data.keys():
                    if key.startswith(f"{username_lower}:"):
                        keys_to_remove.append(key)
                
                if keys_to_remove:
                    for key in keys_to_remove:
                        del cache_data[key]
                    
                    # Сохраняем обновленный кэш
                    tmp_path = f"{cache_path}.tmp"
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(cache_data, f, ensure_ascii=False)
                    os.replace(tmp_path, cache_path)
                    logger.debug(f"Cleared X-UI links cache file entries for {username_lower} ({len(keys_to_remove)} entries)")
            except Exception as e:
                logger.debug(f"Could not clear X-UI links cache file: {e}")
        
        # Также очищаем кэш в памяти через SubscriptionManager если доступен
        try:
            from normalsub.normalsub import HysteriaServer
            server = getattr(clear_user_cache, '_server_instance', None)
            if server and hasattr(server, 'subscription_manager'):
                subscription_manager = server.subscription_manager
                # Очищаем кэш для обоих планов
                for plan in ['standard', 'premium']:
                    cache_key = f"{username_lower}:{plan}"
                    with subscription_manager._xui_links_cache_lock:
                        if cache_key in subscription_manager._xui_links_cache:
                            del subscription_manager._xui_links_cache[cache_key]
                            logger.debug(f"Cleared X-UI links cache in memory for {cache_key}")
        except Exception as e:
            logger.debug(f"Could not clear X-UI links cache in memory: {e}")
        
        # Альтернативный способ: очистка через прямой доступ к кэшу
        # Это работает даже если сервер не запущен
        try:
            # Пытаемся очистить кэш напрямую из файла (уже сделано выше)
            # Дополнительно можем очистить кэш в памяти если модуль загружен
            import sys
            for module_name in list(sys.modules.keys()):
                if 'normalsub' in module_name and 'SubscriptionManager' in str(sys.modules[module_name]):
                    # Модуль загружен, но мы не можем получить экземпляр
                    # Поэтому полагаемся на очистку файла, которая уже сделана
                    pass
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Error clearing X-UI links cache: {e}")
    
    # 3. Очистка кэша labeled URIs (Hysteria ссылки)
    try:
        from normalsub.normalsub import HysteriaCLI
        # Создаем временный экземпляр для очистки кэша
        try:
            cli = HysteriaCLI('/etc/hysteria/core/cli.py')
            cli.clear_labeled_uris_cache(username_lower)
            logger.debug(f"Cleared labeled URIs cache for {username_lower}")
        except Exception as e:
            logger.debug(f"Could not clear labeled URIs cache: {e}")
    except ImportError:
        logger.debug("normalsub module not available for labeled URIs cache clearing")
    except Exception as e:
        logger.warning(f"Error clearing labeled URIs cache: {e}")
    
    logger.info(f"Cache clearing completed for user: {username_lower}")


def clear_all_cache() -> None:
    """
    Очищает весь кэш для всех пользователей.
    Используется при глобальных изменениях конфигурации.
    """
    logger.info("Clearing all user caches")
    
    try:
        from normalsub.normalsub import HysteriaServer
        try:
            server = getattr(clear_all_cache, '_server_instance', None)
            if server and hasattr(server, 'subscription_manager'):
                subscription_manager = server.subscription_manager
                subscription_manager.clear_normalized_subscription_cache(None)
                logger.debug("Cleared all normalized subscription cache")
        except Exception as e:
            logger.debug(f"Could not clear normalized subscription cache: {e}")
    except ImportError:
        logger.debug("normalsub module not available")
    except Exception as e:
        logger.warning(f"Error clearing normalized subscription cache: {e}")
    
    # Очистка файла кэша VLESS ссылок
    try:
        cache_path = os.getenv('XUI_LINKS_CACHE_PATH', '/etc/hysteria/xui_links_cache.json')
        if os.path.exists(cache_path):
            os.remove(cache_path)
            logger.debug("Cleared X-UI links cache file")
    except Exception as e:
        logger.warning(f"Error clearing X-UI links cache file: {e}")
    
    logger.info("All cache clearing completed")
