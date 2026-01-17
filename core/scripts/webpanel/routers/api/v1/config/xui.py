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
    XUISyncUserBody
)

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
        
        # Скрываем пароли и токены в ответе
        safe_config = config.copy()
        for server in safe_config.get('xui_servers', []):
            if 'password' in server:
                server['password'] = '***' if server.get('password') else None
            if 'api_token' in server:
                token = server.get('api_token')
                if token:
                    server['api_token'] = f"***{token[-4:]}" if len(token) > 4 else "***"
        
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
        
        # Восстанавливаем скрытые пароли/токены если они не изменились
        old_config = load_xui_config()
        for i, new_server in enumerate(config_dict.get('xui_servers', [])):
            if i < len(old_config.get('xui_servers', [])):
                old_server = old_config['xui_servers'][i]
                # Если пароль/токен скрыт (***), используем старый
                if new_server.get('password') == '***' and old_server.get('password'):
                    new_server['password'] = old_server['password']
                if new_server.get('api_token', '').startswith('***') and old_server.get('api_token'):
                    new_server['api_token'] = old_server['api_token']
        
        save_xui_config(config_dict)
        
        return DetailResponse(detail='X-UI configuration updated successfully.')
    except HTTPException:
        raise
    except Exception as e:
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
        
        client = XUIClient(
            host=body.host,
            base_path=body.base_path,
            username=body.username,
            password=body.password,
            api_token=body.api_token,
            auth_type=body.auth_type,
            timeout=10
        )
        
        try:
            inbounds = client.list_inbounds()
            return XUITestConnectionResponse(
                success=True,
                message=f"Successfully connected! Found {len(inbounds)} inbounds.",
                inbounds_count=len(inbounds),
                inbounds=inbounds[:10]  # Первые 10 для примера
            )
        except XUIAuthError as e:
            return XUITestConnectionResponse(
                success=False,
                message=f"Authentication failed: {str(e)}"
            )
        except XUIConnectionError as e:
            return XUITestConnectionResponse(
                success=False,
                message=f"Connection failed: {str(e)}"
            )
        except Exception as e:
            return XUITestConnectionResponse(
                success=False,
                message=f"Error: {str(e)}"
            )
    except Exception as e:
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
                errors.append(f"{username}: {error}")
        
        message = f"Synced {success_count} users successfully."
        if failed_count > 0:
            message += f" {failed_count} users failed. Errors: {'; '.join(errors[:5])}"
        
        return DetailResponse(detail=message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Error: {str(e)}')
