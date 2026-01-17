import json
import sys
import logging
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
    XUISyncUserBody
)

logger = logging.getLogger(__name__)

# Добавляем путь к модулям
HYSTERIA_CORE_DIR = '/etc/hysteria/core/scripts'
sys.path.insert(0, HYSTERIA_CORE_DIR)

router = APIRouter()

XUI_CONFIG_PATH = Path("/etc/hysteria/xui_config.json")


def load_xui_config() -> Dict[str, Any]:
    """Загружает конфигурацию X-UI из файла"""
    if not XUI_CONFIG_PATH.exists():
        return {
            "enabled": False,
            "mode": "multi-xui",
            "xui_servers": [],
            "inbound_filter": {}
        }
    
    try:
        with open(XUI_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
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
        
        # Убеждаемся, что структура правильная
        if 'xui_servers' not in config:
            config['xui_servers'] = []
        
        # Очищаем серверы от лишних полей (например, inbound_filter внутри сервера)
        cleaned_servers = []
        for server in config.get('xui_servers', []):
            cleaned_server = {
                'host': server.get('host', ''),
                'base_path': server.get('base_path', '/'),
                'username': server.get('username', ''),
                'password': server.get('password', ''),
                'timeout': server.get('timeout', 10),
                'max_retries': server.get('max_retries', 3),
                'plans': server.get('plans', ['standard', 'premium'])
            }
            cleaned_servers.append(cleaned_server)
        
        config['xui_servers'] = cleaned_servers
        
        # Скрываем пароли в ответе
        safe_config = config.copy()
        for server in safe_config.get('xui_servers', []):
            if 'password' in server and server.get('password'):
                server['password'] = '***'
        
        return XUIConfigResponse(**safe_config)
    except Exception as e:
        import traceback
        logger.error(f"Error loading X-UI config: {e}\n{traceback.format_exc()}")
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
        old_config = load_xui_config()
        for i, new_server in enumerate(config_dict.get('xui_servers', [])):
            if i < len(old_config.get('xui_servers', [])):
                old_server = old_config['xui_servers'][i]
                # Если пароль скрыт (***), используем старый
                if new_server.get('password') == '***' and old_server.get('password'):
                    new_server['password'] = old_server['password']
        
        save_xui_config(config_dict)
        
        logger.info(f"X-UI configuration updated: enabled={config_dict.get('enabled')}, mode={config_dict.get('mode')}, servers={len(config_dict.get('xui_servers', []))}")
        
        return DetailResponse(detail='X-UI configuration updated successfully.')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating X-UI config: {e}")
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.post('/test-connection', response_model=XUITestConnectionResponse, summary='Test X-UI Connection', name='test_xui_connection_api')
async def test_xui_connection_api(body: XUITestConnectionBody):
    """
    Тестирует подключение к серверу X-UI.
    
    Args:
        body: Параметры подключения
    
    Returns:
        XUITestConnectionResponse: Результат теста
    """
        try:
            from xui.xui_client import XUIClient, XUIClientError, XUIAuthError, XUIConnectionError
            
            logger.info(f"Testing X-UI connection to {body.host} with base_path={body.base_path}")
            
            # Проверяем наличие username и password (обязательны)
            if not body.username or not body.password:
                logger.warning("Test connection failed: username and password are required")
                return XUITestConnectionResponse(
                    success=False,
                    message="Username and password are required"
                )
            
            client = XUIClient(
                host=body.host,
                username=body.username,
                password=body.password,
                base_path=body.base_path,
                timeout=10
            )
            
            try:
                inbounds = client.list_inbounds()
                logger.info(f"Test connection successful: found {len(inbounds)} inbounds")
                return XUITestConnectionResponse(
                    success=True,
                    message=f"Successfully connected! Found {len(inbounds)} inbounds.",
                    inbounds_count=len(inbounds),
                    inbounds=inbounds[:10]  # Первые 10 для примера
                )
            except XUIAuthError as e:
                logger.error(f"Test connection failed: Authentication error - {e}")
                return XUITestConnectionResponse(
                    success=False,
                    message=f"Authentication failed: {str(e)}"
                )
            except XUIConnectionError as e:
                logger.error(f"Test connection failed: Connection error - {e}")
                return XUITestConnectionResponse(
                    success=False,
                    message=f"Connection failed: {str(e)}"
                )
            except Exception as e:
                logger.error(f"Test connection failed: Unexpected error - {e}")
                return XUITestConnectionResponse(
                    success=False,
                    message=f"Error: {str(e)}"
                )
        except Exception as e:
            logger.error(f"Error in test connection API: {e}")
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
        
        return XUISyncStatusResponse(
            total_users=len(all_users),
            synced_users=synced_count,
            failed_users=failed_count,
            sync_statuses=sync_statuses
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
        
        sync_manager = get_xui_sync_manager()
        if not sync_manager:
            raise HTTPException(
                status_code=400,
                detail="X-UI sync is not enabled. Please configure it first."
            )
        
        plan = user_data.get('plan', 'standard')
        expiry_days = user_data.get('expiration_days', 0)
        traffic_bytes = user_data.get('max_download_bytes', 0)
        traffic_gb = int(traffic_bytes / (1024 ** 3)) if traffic_bytes > 0 else 0
        enable = not user_data.get('blocked', False)
        
        logger.info(f"Syncing user {body.username} via API (plan: {plan}, expiry: {expiry_days} days, traffic: {traffic_gb} GB)")
        
        success, error = sync_manager.sync_user_create(
            hysteria_username=body.username,
            expiry_days=expiry_days,
            traffic_limit_gb=traffic_gb,
            enable=enable,
            user_plan=plan
        )
        
        if success:
            logger.info(f"User {body.username} synced successfully via API")
            return DetailResponse(detail=f'User {body.username} synced successfully.')
        else:
            logger.error(f"User {body.username} sync failed via API: {error}")
            raise HTTPException(
                status_code=400,
                detail=f'Sync failed: {error}'
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing user {body.username} via API: {e}")
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')


@router.post('/sync-all', response_model=DetailResponse, summary='Sync All Users with X-UI', name='sync_all_users_xui_api')
async def sync_all_users_xui_api():
    """
    Принудительно синхронизирует всех пользователей с X-UI.
    
    Returns:
        DetailResponse: Результат синхронизации
    """
    try:
        from xui.config import get_xui_sync_manager
        from db.database import db
        
        if not db:
            raise HTTPException(status_code=500, detail="Database not available")
        
        sync_manager = get_xui_sync_manager()
        if not sync_manager:
            raise HTTPException(
                status_code=400,
                detail="X-UI sync is not enabled. Please configure it first."
            )
        
        all_users = db.get_all_users()
        logger.info(f"Starting sync for all users via API: {len(all_users)} users")
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
            
            logger.debug(f"Syncing user {username} (plan: {plan}, expiry: {expiry_days} days, traffic: {traffic_gb} GB)")
            
            success, error = sync_manager.sync_user_create(
                hysteria_username=username,
                expiry_days=expiry_days,
                traffic_limit_gb=traffic_gb,
                enable=enable,
                user_plan=plan
            )
            
            if success:
                success_count += 1
                logger.debug(f"User {username} synced successfully")
            else:
                failed_count += 1
                error_msg = f"{username}: {error}"
                errors.append(error_msg)
                logger.warning(f"User {username} sync failed: {error}")
        
        message = f"Synced {success_count} users successfully."
        if failed_count > 0:
            message += f" {failed_count} users failed. Errors: {'; '.join(errors[:5])}"
        
        logger.info(f"Sync all users completed: {success_count} success, {failed_count} failed")
        
        return DetailResponse(detail=message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing all users via API: {e}")
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')
