from fastapi import APIRouter, HTTPException
from ..schema.response import DetailResponse
import json
import os
from scripts.db.database import db

from ..schema.config.ip import (
    EditInputBody,
    StatusResponse,
    AddNodeBody,
    DeleteNodeBody,
    ReorderNodesBody,
    NodeListResponse,
    NodesTrafficPayload,
)
import cli_api

router = APIRouter()


@router.get('/get', response_model=StatusResponse, summary='Get Local Server IP Status')
async def get_ip_api():
    """
    Retrieves the current status of the main server's IP addresses.

    Returns:
        StatusResponse: A response model containing the current IP address details.
    """
    try:
        ipv4, ipv6 = cli_api.get_ip_address()
        return StatusResponse(ipv4=ipv4, ipv6=ipv6)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.get('/add', response_model=DetailResponse, summary='Detect and Add Local Server IP')
async def add_ip_api():
    """
    Adds the auto-detected IP addresses to the .configs.env file.

    Returns:
        A DetailResponse with a message indicating the IP addresses were added successfully.
    """
    try:
        cli_api.add_ip_address()
        return DetailResponse(detail='IP addresses added successfully.')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.post('/edit', response_model=DetailResponse, summary='Edit Local Server IP')
async def edit_ip_api(body: EditInputBody):
    """
    Edits the main server's IP addresses in the .configs.env file.

    Args:
        body: An instance of EditInputBody containing the new IPv4 and/or IPv6 addresses.
    """
    try:
        cli_api.edit_ip_address(str(body.ipv4), str(body.ipv6))
        return DetailResponse(detail='IP address edited successfully.')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.get('/nodes', response_model=NodeListResponse, summary='Get All External Nodes')
async def get_all_nodes():
    """
    Retrieves the list of all configured external nodes.

    Returns:
        A list of node objects, each containing a name, IP and optional parameters.
        Node type (standard/premium) is returned in the `type` field.
    """
    if not os.path.exists(cli_api.NODES_JSON_PATH):
        return []

    try:
        with open(cli_api.NODES_JSON_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                return []

            nodes = json.loads(content)

            # Нормализуем тип ноды: всегда отдаём поле "type"
            normalized_nodes = []
            for node in nodes:
                # поддерживаем как старые записи без type, так и возможное node_type
                raw_type = (node.get('type') or node.get('node_type') or 'standard')
                node_type = str(raw_type).strip().lower()

                if node_type not in ('standard', 'premium'):
                    node_type = 'standard'

                node['type'] = node_type
                # на всякий случай можно убрать node_type, чтобы не путать фронт
                # но это не обязательно, если схема его игнорирует
                normalized_nodes.append(node)

            return normalized_nodes

    except (json.JSONDecodeError, IOError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read or parse nodes file: {e}")


@router.post('/nodes/add', response_model=DetailResponse, summary='Add External Node')
async def add_node(body: AddNodeBody):
    """
    Adds a new external node to the configuration.

    Args:
        body: Request body containing the full details of the node.
    """
    try:
        # Нормализуем тип ноды: standard/premium
        node_type = (body.node_type or "standard").strip().lower()
        if node_type not in ("standard", "premium"):
            node_type = "standard"

        cli_api.add_node(
            name=body.name,
            ip=body.ip,
            port=body.port,
            sni=body.sni,
            pinSHA256=body.pinSHA256,
            obfs=body.obfs,
            insecure=body.insecure,
            node_type=node_type,  # ← ВАЖНО: пробрасываем тип до CLI/скрипта node.py
        )
        return DetailResponse(detail=f"Node '{body.name}' added successfully.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/nodes/delete', response_model=DetailResponse, summary='Delete External Node')
async def delete_node(body: DeleteNodeBody):
    """
    Deletes an external node from the configuration by its name.

    Args:
        body: Request body containing the name of the node to delete.
    """
    try:
        cli_api.delete_node(body.name)
        return DetailResponse(detail=f"Node '{body.name}' deleted successfully.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/nodes/reorder', response_model=DetailResponse, summary='Reorder External Nodes', name='reorder_nodes')
async def reorder_nodes(body: ReorderNodesBody):
    """
    Reorders external nodes according to the provided list of names.

    Args:
        body: Request body containing the list of node names in desired order.
    """
    try:
        cli_api.reorder_nodes(body.names)
        return DetailResponse(detail=f"Successfully reordered {len(body.names)} nodes.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/nodestraffic', response_model=DetailResponse, summary='Receive and Aggregate Traffic from Node')
async def receive_node_traffic(body: NodesTrafficPayload):
    """
    Receives traffic delta from a node and adds it to the user's total in the database.
    Also updates user online status and online_count from the node.
    Authentication is handled by the AuthMiddleware.
    """
    if db is None:
        raise HTTPException(status_code=500, detail="Database connection is not available.")

    updated_count = 0
    for user_traffic in body.users:
        try:
            db_user = db.get_user(user_traffic.username)
            if not db_user:
                continue

            # Агрегируем трафик
            new_upload = db_user.get('upload_bytes', 0) + user_traffic.upload_bytes
            new_download = db_user.get('download_bytes', 0) + user_traffic.download_bytes

            # Объединяем статусы: если пользователь онлайн на узле или локально - он онлайн
            node_online_count = user_traffic.online_count
            local_online_count = db_user.get('online_count', 0)
            
            # Суммируем подключения из разных источников
            # local_online_count уже включает подключения с локального Hysteria 2 и 3X-UI (через traffic.py)
            # node_online_count - это подключения с внешнего узла
            # Если пользователь подключен к локальному серверу и к внешнему узлу - суммируем
            # Но нужно учесть, что при повторных запросах с узла local_online_count уже может включать
            # подключения с этого узла, поэтому используем максимальное значение для избежания дублирования
            # Однако, если это первый запрос с узла или пользователь подключен к разным источникам - суммируем
            if node_online_count > 0 and local_online_count > 0:
                # Пользователь подключен к обоим источникам - суммируем
                combined_online_count = local_online_count + node_online_count
            else:
                # Используем максимальное значение (избегаем дублирования при повторных запросах)
                combined_online_count = max(local_online_count, node_online_count)
            
            # Определяем статус: Online если есть подключения на узле или локально
            node_status = user_traffic.status
            local_status = db_user.get('status', 'Offline')
            
            # Если пользователь онлайн на узле, статус должен быть Online
            if node_online_count > 0:
                combined_status = 'Online'
            elif combined_online_count > 0:
                combined_status = 'Online'
            elif local_status == 'Online' and node_online_count == 0:
                # Если локально онлайн, но на узле нет - оставляем локальный статус
                combined_status = local_status
            else:
                # Используем статус с узла, если локально офлайн
                combined_status = node_status if node_status in ['Online', 'Offline', 'On-hold'] else local_status

            update_data = {
                'upload_bytes': new_upload,
                'download_bytes': new_download,
                'status': combined_status,
                'online_count': combined_online_count,
            }

            if not db_user.get('account_creation_date') and user_traffic.account_creation_date:
                update_data['account_creation_date'] = user_traffic.account_creation_date

            db.update_user(user_traffic.username, update_data)
            updated_count += 1

        except Exception as e:
            print(f"Error updating traffic for user {user_traffic.username}: {e}")

    return DetailResponse(detail=f"Successfully processed and aggregated traffic for {updated_count} users.")
