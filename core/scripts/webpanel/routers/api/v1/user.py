import json
from typing import List
from fastapi import APIRouter, HTTPException
from .schema.user import (
    UserListResponse,
    UserInfoResponse,
    AddUserInputBody,
    EditUserInputBody,
    UserUriResponse,
    AddBulkUsersInputBody,
    UsernamesRequest
)
from .schema.response import DetailResponse
import cli_api

router = APIRouter()


@router.get('/', response_model=UserListResponse)
async def list_users_api():
    """
    Get a list of all users.

    Returns:
        List of user dictionaries.
    Raises:
        HTTPException: if no users are found, or if an error occurs.
    """
    try:
        if res := cli_api.list_users():
            return res
        raise HTTPException(status_code=404, detail='No users found.')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.post('/', response_model=DetailResponse, status_code=201)
async def add_user_api(body: AddUserInputBody):
    """
    Add a single user.
    """
    try:
        cli_api.get_user(body.username)
        raise HTTPException(
            status_code=409,
            detail=f"User '{body.username}' already exists."
        )
    except cli_api.CommandExecutionError:
        # Ожидаемая ситуация — пользователь не найден
        pass
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"{str(e)}"
        )

    try:
        # Добавляем поддержку max_ips и плана при создании
        cli_api.add_user(
            body.username,
            body.traffic_limit,
            body.expiration_days,
            body.password,
            body.creation_date,
            body.unlimited,
            body.note,
            max_ips=body.max_ips,
            # Тариф пользователя (standard/premium), по умолчанию standard
            plan=getattr(body, "plan", "standard"),
        )
        return DetailResponse(detail=f'User {body.username} has been added.')
    except cli_api.CommandExecutionError as e:
        if "User already exists" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"User '{body.username}' already exists."
            )
        raise HTTPException(
            status_code=400,
            detail=f'Failed to add user {body.username}: {str(e)}'
        )
    except cli_api.PasswordGenerationError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate password for user '{body.username}': {str(e)}"
        )
    except cli_api.InvalidInputError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while adding user '{body.username}': {str(e)}"
        )


@router.post('/bulk/', response_model=DetailResponse, status_code=201)
async def add_bulk_users_api(body: AddBulkUsersInputBody):
    """
    Add multiple users in bulk.
    """
    try:
        cli_api.bulk_user_add(
            traffic_gb=body.traffic_gb,
            expiration_days=body.expiration_days,
            count=body.count,
            prefix=body.prefix,
            start_number=body.start_number,
            unlimited=body.unlimited,
            # Тариф для пакетного создания (один план на все аккаунты)
            plan=getattr(body, "plan", "standard"),
        )
        return DetailResponse(
            detail=f"Successfully started adding {body.count} users with prefix '{body.prefix}'."
        )
    except cli_api.CommandExecutionError as e:
        raise HTTPException(
            status_code=400,
            detail=f'Failed to add bulk users: {str(e)}'
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred while adding bulk users: {str(e)}"
        )


@router.post('/uri/bulk', response_model=List[UserUriResponse])
async def show_multiple_user_uris_api(request: UsernamesRequest):
    """
    Get URI information for multiple users in a single request for efficiency.
    """
    if not request.usernames:
        return []

    try:
        uri_data_list = cli_api.show_user_uri_json(request.usernames)
        if not uri_data_list:
            raise HTTPException(
                status_code=404,
                detail='No URI data found for the provided users.'
            )

        valid_responses = [data for data in uri_data_list if not data.get('error')]

        return valid_responses
    except cli_api.ScriptNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f'Server script error: {str(e)}'
        )
    except cli_api.CommandExecutionError as e:
        raise HTTPException(
            status_code=400,
            detail=f'Error executing script: {str(e)}'
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f'Unexpected error: {str(e)}'
        )


@router.post('/bulk-delete', response_model=DetailResponse)
async def bulk_remove_users_api(body: UsernamesRequest):
    """
    Remove multiple users in bulk.
    """
    if not body.usernames:
        raise HTTPException(status_code=400, detail="No usernames provided.")
    try:
        cli_api.kick_users_by_name(body.usernames)
        cli_api.traffic_status(display_output=False)
        cli_api.remove_users(body.usernames)
        return DetailResponse(detail='Users have been removed.')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.get('/{username}/xui-online-status', summary='Get X-UI Online Status', name='get_user_xui_online_status_api')
async def get_user_xui_online_status_api(username: str):
    """
    Получает статус онлайна пользователя из 3X-UI.
    
    Args:
        username: Имя пользователя Hysteria 2
    
    Returns:
        JSON с информацией о статусе онлайна
    """
    try:
        import sys
        import logging
        from pathlib import Path
        
        logger = logging.getLogger(__name__)
        
        # Добавляем путь только если его еще нет
        core_scripts_path = '/etc/hysteria/core/scripts'
        if core_scripts_path not in sys.path:
            sys.path.insert(0, core_scripts_path)
        
        try:
            from db.database import db
            from xui.config import load_xui_config
        except ImportError as import_err:
            return {
                "online": False,
                "error": f"Failed to import required modules: {str(import_err)}"
            }
        
        if not db:
            return {
                "online": False,
                "error": "Database not available"
            }
        
        # Получаем маппинг пользователя
        mapping = db.get_xui_mapping(username)
        if not mapping:
            return {
                "online": False,
                "error": "User not synced with X-UI"
            }
        
        client_uuid = mapping.get('xui_client_uuid')
        xui_host = mapping.get('xui_host')
        
        if not client_uuid:
            return {
                "online": False,
                "error": "No client UUID in mapping"
            }
        
        # Загружаем конфигурацию X-UI
        config = load_xui_config()
        if not config.get('enabled', False):
            return {
                "online": False,
                "error": "X-UI sync is disabled"
            }
        
        servers = config.get('xui_servers', [])
        if not servers:
            return {
                "online": False,
                "error": "No X-UI servers configured"
            }
        
        # Находим сервер для этого пользователя
        target_server = None
        if xui_host:
            # Если указан хост, ищем по нему
            for server in servers:
                if server.get('host') == xui_host and server.get('enabled', True):
                    target_server = server
                    break
        
        if not target_server:
            # Если хост не указан или не найден, берем первый включенный сервер
            for server in servers:
                if server.get('enabled', True):
                    target_server = server
                    break
        
        if not target_server:
            return {
                "online": False,
                "error": "No enabled X-UI server found"
            }
        
        # Создаем клиент для проверки статуса
        try:
            from xui.xui_api_wrapper import XUIAPIWrapper
        except ImportError as import_err:
            return {
                "online": False,
                "error": f"Failed to import XUIAPIWrapper: {str(import_err)}"
            }
        
        auth_type = target_server.get('auth_type', 'username')
        if auth_type == 'token':
            xui_username = 'admin'  # Заглушка для token
        else:
            xui_username = target_server.get('username', '')
        
        xui_password = target_server.get('password', '')
        
        if not xui_password:
            return {
                "online": False,
                "error": "X-UI server password not configured"
            }
        
        client = XUIAPIWrapper(
            host=target_server.get('host'),
            username=xui_username,
            password=xui_password,
            base_path=target_server.get('base_path', '/'),
            timeout=target_server.get('timeout', 10)
        )
        
        try:
            # Пробуем найти клиента по UUID или email
            # Email обычно в формате: hysteria_username_inbound_id
            inbound_ids = mapping.get('inbound_ids', [])
            is_online = False
            client_ips = []
            
            # Пробуем проверить по UUID
            try:
                is_online = client.is_client_online(client_uuid)
                logger.debug(f"XUI online check for {username} (UUID {client_uuid}): {is_online}")
            except Exception as e:
                logger.warning(f"Error checking online status by UUID for {username}: {e}")
                is_online = False
            
            if not is_online and inbound_ids:
                # Если не нашли по UUID, пробуем по email
                for inbound_id in inbound_ids:
                    client_email = f"{username}_{inbound_id}"
                    try:
                        if client.is_client_online(client_email):
                            is_online = True
                            logger.debug(f"XUI online check for {username} (email {client_email}): {is_online}")
                            break
                    except Exception as e:
                        logger.warning(f"Error checking online status by email {client_email} for {username}: {e}")
                        continue
            
            # Получаем IP адреса если клиент онлайн
            if is_online:
                try:
                    client_ips = client.get_client_ips(client_uuid) or []
                    if not client_ips and inbound_ids:
                        # Пробуем по email
                        for inbound_id in inbound_ids:
                            client_email = f"{username}_{inbound_id}"
                            try:
                                client_ips = client.get_client_ips(client_email) or []
                                if client_ips:
                                    break
                            except Exception as e:
                                logger.warning(f"Error getting IPs by email {client_email} for {username}: {e}")
                                continue
                except Exception as e:
                    logger.warning(f"Error getting client IPs for {username}: {e}")
                    client_ips = []
            
            result = {
                "online": is_online,
                "client_uuid": client_uuid,
                "client_ips": client_ips,
                "xui_host": xui_host or target_server.get('host')
            }
            logger.debug(f"XUI online status result for {username}: {result}")
            return result
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error checking X-UI online status for {username}: {e}", exc_info=True)
            return {
                "online": False,
                "error": f"Error checking status: {str(e)}"
            }
        finally:
            # XUIAPIWrapper не имеет метода close(), но api_client может иметь
            try:
                if hasattr(client, 'close'):
                    client.close()
                elif hasattr(client, 'api_client') and hasattr(client.api_client, 'close'):
                    client.api_client.close()
            except:
                pass
    
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error in get_user_xui_online_status: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f'Error: {str(e)}'
        )


@router.get('/{username}', response_model=UserInfoResponse)
async def get_user_api(username: str):
    """
    Get the details of a user.

    Args:
        username: The username of the user to get.

    Returns:
        A user dictionary.

    Raises:
        HTTPException: if the user is not found, or if an error occurs.
    """
    try:
        user_data = cli_api.get_user(username)
        if not user_data:
            raise HTTPException(
                status_code=404,
                detail=f'User {username} not found.'
            )

        # Нормализуем имя пользователя
        if '_id' in user_data:
            user_data['username'] = user_data.pop('_id')

        return user_data
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse user data from CLI: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f'An unexpected error occurred: {str(e)}'
        )


@router.patch('/{username}', response_model=DetailResponse)
async def edit_user_api(username: str, body: EditUserInputBody):
    """
    Edit a user's details.

    Args:
        username: The username of the user to edit.
        body: An instance of EditUserInputBody containing the new user details.

    Returns:
        A DetailResponse with a message indicating the user has been edited.

    Raises:
        HTTPException: if an error occurs while editing the user.
    """
    try:
        cli_api.kick_users_by_name([username])
        cli_api.traffic_status(display_output=False)

        # Передаем max_ips и новый план пользователя в функцию редактирования
        cli_api.edit_user(
            username=username,
            new_username=body.new_username,
            new_password=body.new_password,
            new_traffic_limit=body.new_traffic_limit,
            new_expiration_days=body.new_expiration_days,
            renew_password=body.renew_password,
            renew_creation_date=body.renew_creation_date,
            blocked=body.blocked,
            unlimited_ip=body.unlimited_ip,
            note=body.note,
            max_ips=body.max_ips,
            # Новый тариф; если None — план не меняем
            new_plan=getattr(body, "new_plan", None),
        )
        return DetailResponse(detail=f'User {username} has been edited.')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.delete('/{username}', response_model=DetailResponse)
async def remove_user_api(username: str):
    """
    Remove a user.

    Args:
        username: The username of the user to remove.

    Returns:
        A DetailResponse with a message indicating the user has been removed.

    Raises:
        HTTPException: 404 if the user is not found, 400 if another error occurs.
    """
    try:
        user = cli_api.get_user(username)
        if not user:
            raise HTTPException(
                status_code=404,
                detail=f'User {username} not found.'
            )

        cli_api.kick_users_by_name([username])
        cli_api.traffic_status(display_output=False)
        cli_api.remove_users([username])
        return DetailResponse(detail=f'User {username} has been removed.')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.get('/{username}/reset', response_model=DetailResponse)
async def reset_user_api(username: str):
    """
    Resets a user.

    Args:
        username: The username of the user to reset.

    Returns:
        A DetailResponse with a message indicating the user has been reset.

    Raises:
        HTTPException: if an error occurs while resetting the user.
    """
    try:
        user = cli_api.get_user(username)
        if not user:
            raise HTTPException(
                status_code=404,
                detail=f'User {username} not found.'
            )

        cli_api.reset_user(username)
        return DetailResponse(detail=f'User {username} has been reset.')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.get('/{username}/uri', response_model=UserUriResponse)
async def show_user_uri_api(username: str):
    """
    Get the URI information for a user in JSON format.

    Args:
        username: The username of the user.

    Returns:
        UserUriResponse: An object containing URI information for the user.

    Raises:
        HTTPException: 404 if the user is not found, 400 if another error occurs.
    """
    try:
        uri_data_list = cli_api.show_user_uri_json([username])
        if not uri_data_list:
            raise HTTPException(
                status_code=404,
                detail=f'URI for user {username} not found.'
            )

        uri_data = uri_data_list[0]
        if uri_data.get('error'):
            raise HTTPException(
                status_code=404,
                detail=f"{uri_data['error']}"
            )

        return UserUriResponse(**uri_data)
    except cli_api.ScriptNotFoundError as e:
        raise HTTPException(
            status_code=500,
            detail=f'Server script error: {str(e)}'
        )
    except cli_api.CommandExecutionError as e:
        raise HTTPException(
            status_code=400,
            detail=f'Error executing script: {str(e)}'
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f'Unexpected error: {str(e)}'
        )
