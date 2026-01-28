import json
import sys
from pathlib import Path
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException
from ..schema.response import DetailResponse
from ..schema.config.xui import (
    XUIConfigInputBody,
    XUIConfigResponse,
    XUITestConnectionBody,
    XUITestConnectionResponse,
    XUISyncStatusResponse,
    XUISyncUserBody,
    XUIServerHealthResponse
)

# Добавляем путь к модулям
HYSTERIA_CORE_DIR = '/etc/hysteria/core/scripts'
sys.path.insert(0, HYSTERIA_CORE_DIR)

router = APIRouter()

XUI_CONFIG_PATH = Path("/etc/hysteria/xui_config.json")
try:
    from xui.config import normalize_xui_server_config
except Exception:
    normalize_xui_server_config = None


def load_xui_config() -> Dict[str, Any]:
    """Загружает конфигурацию X-UI из файла с миграцией для обратной совместимости"""
    if not XUI_CONFIG_PATH.exists():
        return {
            "enabled": False,
            "mode": "multi-xui",
            "xui_servers": [],
            "inbound_filter": {}
        }
    
    try:
        with open(XUI_CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Миграция: если старый формат (один сервер без массива или без name)
        xui_servers = config.get('xui_servers', [])
        if xui_servers:
            migrated = False
            for i, server in enumerate(xui_servers):
                # Если нет поля name - добавляем его
                if 'name' not in server:
                    host = server.get('host', '')
                    if host:
                        # Извлекаем имя из host (убираем протокол и порт)
                        name = host.split('://')[-1].split(':')[0].split('/')[0]
                        server['name'] = name or f'Сервер {i + 1}'
                    else:
                        server['name'] = f'Сервер {i + 1}'
                    migrated = True
                # Если нет auth_type - определяем по наличию username
                if 'auth_type' not in server:
                    if server.get('username'):
                        server['auth_type'] = 'username'
                    else:
                        server['auth_type'] = 'token'
                    migrated = True
                # Если нет verify_tls - добавляем True
                if 'verify_tls' not in server:
                    server['verify_tls'] = True
                    migrated = True
                # Если нет enabled - добавляем True
                if 'enabled' not in server:
                    server['enabled'] = True
                    migrated = True
                # Если нет plans - добавляем стандартные
                if 'plans' not in server or not server.get('plans'):
                    server['plans'] = ['standard', 'premium']
                    migrated = True
                # Если нет public_port - добавляем дефолт 443
                if 'public_port' not in server:
                    server['public_port'] = 443
                    migrated = True
                # Если нет link_host_rewrite_from - добавляем дефолт 127.0.0.1
                if 'link_host_rewrite_from' not in server:
                    server['link_host_rewrite_from'] = '127.0.0.1'
                    migrated = True
                # Если нет sni - берем public_host как дефолт
                if 'sni' not in server and server.get('public_host'):
                    server['sni'] = server.get('public_host')
                    migrated = True
                # Если нет xhttp_* - добавляем дефолтные значения
                if 'xhttp_alpn' not in server:
                    server['xhttp_alpn'] = 'h2'
                    migrated = True
                if 'xhttp_fp' not in server:
                    server['xhttp_fp'] = 'chrome'
                    migrated = True
                if 'xhttp_mode' not in server:
                    server['xhttp_mode'] = 'auto'
                    migrated = True
            
            # Сохраняем мигрированный конфиг
            if migrated:
                save_xui_config(config)
        
        # Автоматически нормализуем публичные параметры (без записи в файл)
        if normalize_xui_server_config:
            config['xui_servers'] = [
                normalize_xui_server_config(s) for s in config.get('xui_servers', [])
            ]
        
        # Миграция: удаляем устаревшие поля (cron и стратегия конфликтов)
        if 'sync_period_type' in config or 'sync_cron' in config or 'conflict_strategy' in config:
            migrated = False
            # Удаляем cron-связанные поля
            if 'sync_period_type' in config:
                del config['sync_period_type']
                migrated = True
            if 'sync_cron' in config:
                del config['sync_cron']
                migrated = True
            # Удаляем стратегию конфликтов
            if 'conflict_strategy' in config:
                del config['conflict_strategy']
                migrated = True
            # Если sync_interval не установлен, устанавливаем значение по умолчанию
            if 'sync_interval' not in config or not config.get('sync_interval'):
                config['sync_interval'] = 60
                migrated = True
            
            if migrated:
                save_xui_config(config)
        
        return config
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load X-UI config: {str(e)}"
        )


def save_xui_config(config: Dict[str, Any]) -> None:
    """Сохраняет конфигурацию X-UI в файл"""
    try:
        # Создаем директорию если не существует
        XUI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Сохраняем конфиг
        with open(XUI_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        
        # Устанавливаем права доступа
        import os
        os.chmod(XUI_CONFIG_PATH, 0o600)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save X-UI config: {str(e)}"
        )


@router.get('/', response_model=XUIConfigResponse, summary='Get X-UI Configuration', name='get_xui_config_api')
async def get_xui_config_api():
    """
    Получает текущую конфигурацию X-UI.
    
    Returns:
        XUIConfigResponse: Текущая конфигурация
    """
    try:
        config = load_xui_config()
        
        # Скрываем пароли в ответе
        safe_config = config.copy()
        for server in safe_config.get('xui_servers', []):
            if 'password' in server:
                server['password'] = '***' if server.get('password') else None
        
        return XUIConfigResponse(**safe_config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')


@router.post('/', response_model=DetailResponse, summary='Update X-UI Configuration', name='update_xui_config_api')
async def update_xui_config_api(body: XUIConfigInputBody):
    """
    Обновляет конфигурацию X-UI.
    
    Args:
        body: Новая конфигурация X-UI
    
    Returns:
        DetailResponse: Результат обновления
    """
    try:
        # Конвертируем Pydantic модель в dict
        config_dict = body.model_dump(exclude_none=True)
        
        # Восстанавливаем скрытые пароли если они не изменились
        # Используем поиск по host/name вместо индекса, чтобы сохранить порядок
        old_config = load_xui_config()
        old_servers_by_key = {}
        for old_server in old_config.get('xui_servers', []):
            # Используем host или name как ключ для поиска (нормализуем пробелы)
            key = (old_server.get('host') or old_server.get('name') or '').strip()
            if key:
                old_servers_by_key[key] = old_server
        
        # ВАЖНО: Сохраняем порядок серверов из нового конфига
        # Восстанавливаем пароли, но не меняем порядок
        for new_server in config_dict.get('xui_servers', []):
            # Ищем старый сервер по host или name
            key = (new_server.get('host') or new_server.get('name') or '').strip()
            old_server = old_servers_by_key.get(key) if key else None
            
            if old_server:
                # Если пароль скрыт (***) или пустой, используем старый
                new_password = new_server.get('password', '')
                if (new_password == '***' or new_password == '') and old_server.get('password') and old_server.get('password') != '***':
                    new_server['password'] = old_server['password']
        
        # Устанавливаем значение по умолчанию для sync_interval, если не указано
        if 'sync_interval' not in config_dict or not config_dict.get('sync_interval'):
            config_dict['sync_interval'] = old_config.get('sync_interval', 60)
        
        # Автоматически нормализуем публичные параметры перед сохранением
        if normalize_xui_server_config:
            config_dict['xui_servers'] = [
                normalize_xui_server_config(s) for s in config_dict.get('xui_servers', [])
            ]
        
        # Логируем порядок серверов перед сохранением для отладки
        import logging
        logger = logging.getLogger(__name__)
        server_order = [s.get('host') or s.get('name') or f'Server {i}' for i, s in enumerate(config_dict.get('xui_servers', []))]
        logger.info(f"Saving X-UI config with server order: {server_order}")
        
        save_xui_config(config_dict)
        
        # Проверяем, что порядок сохранился правильно
        # Небольшая задержка для гарантии записи на диск
        import time
        time.sleep(0.1)  # 100ms задержка для записи на диск
        
        saved_config = load_xui_config()
        saved_order = [s.get('host') or s.get('name') or f'Server {i}' for i, s in enumerate(saved_config.get('xui_servers', []))]
        logger.info(f"Loaded X-UI config with server order: {saved_order}")
        
        # Проверяем, что порядок совпадает
        if saved_order != server_order:
            logger.warning(f"Server order mismatch after save! Expected: {server_order}, Got: {saved_order}")
        
        return DetailResponse(detail='X-UI configuration updated successfully.')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.post('/server/{server_index}/health', response_model=XUIServerHealthResponse, summary='Check X-UI Server Health', name='check_xui_server_health_api')
async def check_xui_server_health_api(server_index: int):
    """
    Проверяет здоровье конкретного сервера X-UI.
    
    Args:
        server_index: Индекс сервера в списке (начиная с 0)
    
    Returns:
        XUIServerHealthResponse: Статус здоровья сервера
    
    ВАЖНО: Пароли НЕ логируются в целях безопасности.
    """
    try:
        config = load_xui_config()
        servers = config.get('xui_servers', [])
        
        if server_index < 0 or server_index >= len(servers):
            raise HTTPException(status_code=404, detail=f"Server index {server_index} not found")
        
        server = servers[server_index]
        if not server.get('enabled', True):
            return XUIServerHealthResponse(
                healthy=False,
                message="Server is disabled"
            )
        
        from xui.xui_api_wrapper import XUIAPIWrapper
        from xui.xui_api_client import XUIAPIAuthError, XUIAPIConnectionError
        
        # Для обратной совместимости
        XUIClient = XUIAPIWrapper
        XUIAuthError = XUIAPIAuthError
        XUIConnectionError = XUIAPIConnectionError
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Определяем username и password в зависимости от auth_type
        auth_type = server.get('auth_type', 'username')
        if auth_type == 'token':
            username = 'admin'  # Заглушка для py3xui
            password = server.get('password', '')
        else:
            username = server.get('username', '')
            password = server.get('password', '')
        
        if not password:
            return XUIServerHealthResponse(
                healthy=False,
                message="Password/token not configured"
            )
        
        server_name = server.get('name', server.get('host', 'Unknown'))
        # ВАЖНО: НЕ логируем пароль! Только имя сервера
        logger.info(f"Checking health of server {server_name}")
        
        client = XUIClient(
            host=server.get('host'),
            username=username,
            password=password,
            base_path=server.get('base_path', '/'),
            timeout=server.get('timeout', 10)
        )
        
        # Измеряем пинг до сервера
        ping_ms = None
        try:
            parsed_host = urlparse(server.get('host', ''))
            hostname = parsed_host.hostname
            if hostname:
                # Пингуем хост
                start_time = time.time()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)  # Таймаут 2 секунды
                port = parsed_host.port or (443 if parsed_host.scheme == 'https' else 80)
                result = sock.connect_ex((hostname, port))
                sock.close()
                if result == 0:
                    ping_ms = (time.time() - start_time) * 1000  # Конвертируем в миллисекунды
        except Exception:
            # Игнорируем ошибки пинга
            pass
        
        try:
            healthy, message = client.check_health()
            if healthy:
                inbounds = client.list_inbounds()
                return XUIServerHealthResponse(
                    healthy=True,
                    message=message,
                    inbounds_count=len(inbounds),
                    ping_ms=ping_ms
                )
            else:
                return XUIServerHealthResponse(
                    healthy=False,
                    message=message,
                    ping_ms=ping_ms
                )
        except Exception as e:
            # НЕ логируем детали с паролем
            logger.warning(f"Health check failed for server {server_name}")
            return XUIServerHealthResponse(
                healthy=False,
                message=f"Error: {str(e)}"
            )
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error in health check: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')


@router.post('/test-connection', response_model=XUITestConnectionResponse, summary='Test X-UI Connection', name='test_xui_connection_api')
async def test_xui_connection_api(body: XUITestConnectionBody):
    """
    Тестирует подключение к серверу X-UI.
    
    Args:
        body: Параметры подключения
    
    Returns:
        XUITestConnectionResponse: Результат теста
    
    ВАЖНО: Пароли НЕ логируются в целях безопасности.
    """
    try:
        from xui.xui_api_wrapper import XUIAPIWrapper
        from xui.xui_api_client import XUIAPIError, XUIAPIAuthError, XUIAPIConnectionError
        
        # Для обратной совместимости
        XUIClient = XUIAPIWrapper
        XUIClientError = XUIAPIError
        XUIAuthError = XUIAPIAuthError
        XUIConnectionError = XUIAPIConnectionError
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Проверяем наличие username и password (обязательны)
        if not body.username or not body.password:
            return XUITestConnectionResponse(
                success=False,
                message="Username and password are required"
            )
        
        # ВАЖНО: НЕ логируем пароль! Только host и username
        logger.info(f"Testing X-UI connection to {body.host} with username {body.username}")
        
        client = XUIClient(
            host=body.host,
            username=body.username,
            password=body.password,
            base_path=body.base_path,
            timeout=10
        )
        
        try:
            inbounds = client.list_inbounds()
            logger.info(f"Successfully connected to {body.host}, found {len(inbounds)} inbounds")
            return XUITestConnectionResponse(
                success=True,
                message=f"Successfully connected! Found {len(inbounds)} inbounds.",
                inbounds_count=len(inbounds),
                inbounds=inbounds[:10]  # Первые 10 для примера
            )
        except XUIAuthError as e:
            # НЕ логируем детали ошибки с паролем
            logger.warning(f"Authentication failed for {body.host} with username {body.username}")
            return XUITestConnectionResponse(
                success=False,
                message=f"Authentication failed: {str(e)}"
            )
        except XUIConnectionError as e:
            logger.warning(f"Connection failed to {body.host}: {str(e)}")
            return XUITestConnectionResponse(
                success=False,
                message=f"Connection failed: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error testing connection to {body.host}: {str(e)}", exc_info=True)
            return XUITestConnectionResponse(
                success=False,
                message=f"Error: {str(e)}"
            )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error in test_connection: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')


@router.get('/sync-status', response_model=XUISyncStatusResponse, summary='Get X-UI Sync Status', name='get_xui_sync_status_api')
async def get_xui_sync_status_api():
    """
    Получает статус синхронизации всех пользователей.
    
    Returns:
        XUISyncStatusResponse: Статус синхронизации
    """
    try:
        from db.database import db
        from datetime import datetime
        
        if not db:
            raise HTTPException(status_code=500, detail="Database not available")
        
        all_users = db.get_all_users()
        all_mappings = db.get_all_xui_mappings() if hasattr(db, 'get_all_xui_mappings') else []
        
        # Создаем словарь маппингов по username
        mappings_dict = {m.get('_id', m.get('hysteria_username')): m for m in all_mappings}
        
        sync_statuses = {}
        synced_count = 0
        failed_count = 0
        
        for user in all_users:
            username = user.get('_id', user.get('username'))
            mapping = mappings_dict.get(username)
            if mapping:
                status = mapping.get('sync_status', 'unknown')
                sync_statuses[username] = status
                if status == 'success':
                    synced_count += 1
                elif status == 'failed':
                    failed_count += 1
            else:
                sync_statuses[username] = 'not_synced'
        
        # Получаем информацию о последнем запуске синхронизации
        # (заглушка - в реальности нужно хранить это в БД или конфиге)
        last_sync_time = None
        last_sync_status = None
        last_sync_stats = None
        
        # Пытаемся получить из конфига или БД
        try:
            config = load_xui_config()
            if 'last_sync' in config:
                last_sync = config['last_sync']
                last_sync_time = last_sync.get('time')
                last_sync_status = last_sync.get('status')
                last_sync_stats = last_sync.get('stats')
        except:
            pass
        
        return XUISyncStatusResponse(
            total_users=len(all_users),
            synced_users=synced_count,
            failed_users=failed_count,
            sync_statuses=sync_statuses,
            last_sync_time=last_sync_time,
            last_sync_status=last_sync_status,
            last_sync_stats=last_sync_stats
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')


@router.post('/sync-user', response_model=DetailResponse, summary='Sync User with X-UI', name='sync_user_xui_api')
async def sync_user_xui_api(body: XUISyncUserBody):
    """
    Принудительно синхронизирует пользователя с X-UI.
    
    Args:
        body: Имя пользователя для синхронизации
    
    Returns:
        DetailResponse: Результат синхронизации
    """
    try:
        from xui.config import get_xui_sync_manager
        from db.database import db
        
        if not db:
            raise HTTPException(status_code=500, detail="Database not available")
        
        user_data = db.get_user(body.username)
        if not user_data:
            raise HTTPException(status_code=404, detail=f"User {body.username} not found")
        
        # Проверяем конфигурацию перед созданием менеджера
        config = load_xui_config()
        if not config.get('enabled', False):
            raise HTTPException(
                status_code=400,
                detail="X-UI sync is not enabled. Enable it in settings first."
            )
        
        servers = config.get('xui_servers', [])
        if not servers:
            raise HTTPException(
                status_code=400,
                detail="No X-UI servers configured. Add at least one server first."
            )
        
        # Проверяем наличие валидных серверов
        has_valid_server = False
        for server in servers:
            if not server.get('enabled', True):
                continue
            host = server.get('host', '').strip()
            if not host:
                continue
            auth_type = server.get('auth_type', 'username')
            password = server.get('password', '').strip()
            if auth_type == 'token' and password:
                has_valid_server = True
                break
            elif auth_type == 'username':
                username = server.get('username', '').strip()
                if username and password:
                    has_valid_server = True
                    break
        
        if not has_valid_server:
            raise HTTPException(
                status_code=400,
                detail="No valid enabled X-UI servers found. Configure at least one server with valid credentials."
            )
        
        sync_manager = get_xui_sync_manager()
        if not sync_manager:
            raise HTTPException(
                status_code=500,
                detail="Failed to initialize X-UI sync manager. Check server logs for details."
            )
        
        plan = user_data.get('plan', 'standard')
        expiry_days = user_data.get('expiration_days', 0)
        traffic_bytes = user_data.get('max_download_bytes', 0)
        traffic_gb = int(traffic_bytes / (1024 ** 3)) if traffic_bytes > 0 else 0
        enable = not user_data.get('blocked', False)
        
        success, error = sync_manager.sync_user_create(
            hysteria_username=body.username,
            expiry_days=expiry_days,
            traffic_limit_gb=traffic_gb,
            enable=enable,
            user_plan=plan
        )
        
        if success:
            return DetailResponse(detail=f'User {body.username} synced successfully.')
        else:
            raise HTTPException(
                status_code=400,
                detail=f'Sync failed: {error}'
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')


@router.get('/logs', summary='Get X-UI Logs', name='get_xui_logs_api')
async def get_xui_logs_api(lines: int = 50):
    """
    Получает логи синхронизации X-UI.
    
    Args:
        lines: Количество последних строк логов (по умолчанию 50, максимум 1000)
    
    Returns:
        JSON с логами
    """
    try:
        from xui.logging_config import XUI_LOG_FILE
        
        # Ограничиваем количество строк
        lines = max(10, min(1000, lines))
        
        if not XUI_LOG_FILE.exists():
            return {
                "success": True,
                "logs": "Файл логов не найден. Логирование еще не началось.",
                "lines_count": 0
            }
        
        # Читаем последние N строк из файла
        try:
            with open(XUI_LOG_FILE, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                # Берем последние N строк
                log_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                logs_text = ''.join(log_lines)
                
                return {
                    "success": True,
                    "logs": logs_text,
                    "lines_count": len(log_lines),
                    "total_lines": len(all_lines)
                }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read log file: {str(e)}"
            )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error getting X-UI logs: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')


@router.post('/clear-subscription-cache', response_model=DetailResponse, summary='Clear X-UI Subscription Links Cache', name='clear_xui_subscription_cache_api')
async def clear_xui_subscription_cache_api():
    """
    Очищает кэш ссылок подписки X-UI.
    Используется после изменения порядка серверов или других изменений конфигурации.
    
    Returns:
        DetailResponse: Результат очистки кэша
    """
    try:
        import os
        
        cache_path = os.environ.get('XUI_LINKS_CACHE_PATH', '/etc/hysteria/xui_links_cache.json')
        
        # Удаляем файл кэша если существует
        if os.path.exists(cache_path):
            try:
                os.remove(cache_path)
                return DetailResponse(detail='Subscription links cache cleared successfully.')
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f'Failed to delete cache file: {str(e)}'
                )
        else:
            return DetailResponse(detail='Cache file does not exist, nothing to clear.')
    
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error clearing subscription cache: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')


@router.post('/sync-all', response_model=DetailResponse, summary='Sync All Users with X-UI', name='sync_all_users_xui_api')
async def sync_all_users_xui_api():
    """
    Принудительно синхронизирует всех пользователей с X-UI.
    
    Returns:
        DetailResponse: Результат синхронизации
    """
    try:
        import logging
        logger = logging.getLogger(__name__)
        
        from xui.config import get_xui_sync_manager
        from db.database import db
        from datetime import datetime
        
        if not db:
            raise HTTPException(status_code=500, detail="Database not available")
        
        # Проверяем конфигурацию перед созданием менеджера
        config = load_xui_config()
        if not config.get('enabled', False):
            raise HTTPException(
                status_code=400,
                detail="X-UI sync is not enabled. Enable it in settings first."
            )
        
        servers = config.get('xui_servers', [])
        if not servers:
            raise HTTPException(
                status_code=400,
                detail="No X-UI servers configured. Add at least one server first."
            )
        
        # Проверяем наличие валидных серверов
        has_valid_server = False
        for server in servers:
            if not server.get('enabled', True):
                continue
            host = server.get('host', '').strip()
            if not host:
                continue
            auth_type = server.get('auth_type', 'username')
            password = server.get('password', '').strip()
            if auth_type == 'token' and password:
                has_valid_server = True
                break
            elif auth_type == 'username':
                username = server.get('username', '').strip()
                if username and password:
                    has_valid_server = True
                    break
        
        if not has_valid_server:
            raise HTTPException(
                status_code=400,
                detail="No valid enabled X-UI servers found. Configure at least one server with valid credentials."
            )
        
        sync_manager = get_xui_sync_manager()
        if not sync_manager:
            raise HTTPException(
                status_code=500,
                detail="Failed to initialize X-UI sync manager. Check server logs for details."
            )
        
        all_users = db.get_all_users()
        success_count = 0
        failed_count = 0
        errors = []
        
        for user in all_users:
            username = user.get('_id', user.get('username'))
            plan = user.get('plan', 'standard')
            expiry_days = user.get('expiration_days', 0)
            traffic_bytes = user.get('max_download_bytes', 0)
            traffic_gb = int(traffic_bytes / (1024 ** 3)) if traffic_bytes > 0 else 0
            enable = not user.get('blocked', False)
            
            try:
                success, error = sync_manager.sync_user_create(
                    hysteria_username=username,
                    expiry_days=expiry_days,
                    traffic_limit_gb=traffic_gb,
                    enable=enable,
                    user_plan=plan
                )
                
                if success:
                    success_count += 1
                else:
                    failed_count += 1
                    error_msg = error if error else "Unknown error"
                    errors.append(f"{username}: {error_msg}")
                    logger.warning(f"Sync failed for user {username}: {error_msg}")
            except Exception as e:
                failed_count += 1
                error_msg = f"Exception during sync: {str(e)}"
                errors.append(f"{username}: {error_msg}")
                logger.error(f"Exception syncing user {username}: {e}", exc_info=True)
        
        # Сохраняем информацию о последнем запуске
        try:
            config = load_xui_config()
            config['last_sync'] = {
                'time': datetime.now().isoformat(),
                'status': 'success' if failed_count == 0 else 'failed',
                'stats': {
                    'synced': success_count,
                    'failed': failed_count
                }
            }
            save_xui_config(config)
        except Exception as e:
            # Не критично, просто логируем
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to save last sync info: {e}")
        
        message = f"Synced {success_count} users successfully."
        if failed_count > 0:
            message += f" {failed_count} users failed. Errors: {'; '.join(errors[:5])}"
        
        return DetailResponse(detail=message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')
