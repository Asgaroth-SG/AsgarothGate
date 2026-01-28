#!/usr/bin/env python3

import init_paths
import sys
import json
from pathlib import Path
from datetime import datetime
from bson.objectid import ObjectId
from hysteria2_api import Hysteria2Client
from db.database import db
from paths import CONFIG_FILE, API_BASE_URL

def get_secret() -> str | None:
    if not CONFIG_FILE.exists():
        return None
    try:
        with CONFIG_FILE.open('r') as f:
            config_data = json.load(f)
        return config_data.get("trafficStats", {}).get("secret")
    except (json.JSONDecodeError, IOError):
        return None

def convert_datetime_to_str(obj):
    """
    Рекурсивно конвертирует объекты datetime и ObjectId в строки для JSON сериализации.
    """
    if isinstance(obj, datetime):
        # Конвертируем datetime в строку формата YYYY-MM-DD
        return obj.strftime("%Y-%m-%d")
    elif isinstance(obj, ObjectId):
        # Конвертируем ObjectId в строку
        return str(obj)
    elif isinstance(obj, dict):
        return {key: convert_datetime_to_str(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_datetime_to_str(item) for item in obj]
    else:
        return obj

def get_users_from_db() -> list:
    if db is None:
        print("Error: Database connection failed.", file=sys.stderr)
        return []
    try:
        users = db.get_all_users()
        for user in users:
            user['username'] = user.pop('_id')
        return users
    except Exception as e:
        print(f"Error retrieving users from database: {e}", file=sys.stderr)
        return []

def main():
    users_list = get_users_from_db()
    if not users_list:
        print(json.dumps([], indent=2))
        return

    secret = get_secret()
    users_dict = {user['username']: user for user in users_list}

    # Получаем онлайн статус из Hysteria 2 API
    if secret:
        try:
            client = Hysteria2Client(base_url=API_BASE_URL, secret=secret)
            online_clients = client.get_online_clients()

            for username, status in online_clients.items():
                if status.is_online and username in users_dict:
                    users_dict[username]['online_count'] = status.connections

        except Exception as e:
            print(f"Warning: Could not connect to Hysteria2 API to get online status. {e}", file=sys.stderr)
            pass

    # Получаем онлайн статус из 3X-UI
    # ОПТИМИЗАЦИЯ: Используем батчинг для получения маппингов
    # Это критично для производительности при большом количестве пользователей
    try:
        from xui.config import load_xui_config
        config = load_xui_config()
        
        if config.get('enabled', False) and db:
            from xui.xui_api_wrapper import XUIAPIWrapper
            
            servers = config.get('xui_servers', [])
            
            # Батчинг: получаем все маппинги одним запросом
            usernames_list = list(users_dict.keys())
            all_mappings = db.get_users_mappings_batch(usernames_list) if usernames_list else {}
            
            for server in servers:
                if not server.get('enabled', True):
                    continue
                
                auth_type = server.get('auth_type', 'username')
                if auth_type == 'token':
                    xui_username = 'admin'
                else:
                    xui_username = server.get('username', '')
                
                xui_password = server.get('password', '')
                if not xui_password:
                    continue
                
                client = None
                try:
                    # Проверяем кэш для этого сервера
                    server_host = server.get('host')
                    now = time.time()
                    cached_clients = None
                    
                    with _online_clients_cache_lock:
                        if _online_clients_cache:
                            cached_at, cached_data = _online_clients_cache
                            age = now - cached_at
                            if age < _online_clients_cache_ttl:
                                cached_clients = cached_data.get(server_host)
                    
                    client = XUIAPIWrapper(
                        host=server_host,
                        username=xui_username,
                        password=xui_password,
                        base_path=server.get('base_path', '/'),
                        timeout=server.get('timeout', 10)
                    )
                    
                    # Используем кэш или получаем список онлайн клиентов
                    if cached_clients is not None:
                        online_clients = cached_clients
                    else:
                        online_clients = client.get_online_clients()
                        # Сохраняем в кэш
                        with _online_clients_cache_lock:
                            if _online_clients_cache is None:
                                _online_clients_cache = (now, {})
                            cached_at, cached_data = _online_clients_cache
                            cached_data[server_host] = online_clients
                            _online_clients_cache = (now, cached_data)
                    
                    # Если это массив строк, используем детальный метод
                    if online_clients and isinstance(online_clients[0], str):
                        online_clients_by_inbound = client.get_online_clients_detailed()
                        all_online_clients = []
                        for inbound_id, clients in online_clients_by_inbound.items():
                            all_online_clients.extend(clients)
                    else:
                        all_online_clients = online_clients if isinstance(online_clients, list) else []
                    
                    # Сопоставляем онлайн клиентов с пользователями Hysteria 2
                    # Используем предзагруженные маппинги (батчинг)
                    for username in users_dict.keys():
                        mapping = all_mappings.get(username.lower())
                        if not mapping:
                            continue
                        
                        client_uuid = mapping.get('xui_client_uuid')
                        xui_host = mapping.get('xui_host')
                        
                        # Проверяем, что это правильный сервер
                        if xui_host and xui_host != server.get('host'):
                            continue
                        
                        # Ищем клиента в списке онлайн
                        for online_client in all_online_clients:
                            if not isinstance(online_client, dict):
                                continue
                            
                            client_id = online_client.get('id')
                            client_email = online_client.get('email', '')
                            client_ips = online_client.get('ips', [])
                            
                            # Проверяем по UUID
                            if client_uuid and client_id == client_uuid:
                                online_count = len(client_ips) if client_ips else 1
                                # Суммируем количество подключений из Hysteria 2 и 3X-UI
                                # Пользователь может быть подключен к обоим сервисам одновременно
                                current_count = users_dict[username].get('online_count', 0)
                                users_dict[username]['online_count'] = current_count + online_count
                                break
                            
                            # Проверяем по email
                            if client_email:
                                inbound_ids = mapping.get('inbound_ids', [])
                                for inbound_id in inbound_ids:
                                    expected_email = f"{username}_{inbound_id}"
                                    if client_email == expected_email:
                                        online_count = len(client_ips) if client_ips else 1
                                        # Суммируем количество подключений из Hysteria 2 и 3X-UI
                                        # Пользователь может быть подключен к обоим сервисам одновременно
                                        current_count = users_dict[username].get('online_count', 0)
                                        users_dict[username]['online_count'] = current_count + online_count
                                        break
                                
                                if users_dict[username].get('online_count', 0) > 0:
                                    break
                
                except Exception as e:
                    print(f"Warning: Could not get online clients from X-UI server {server.get('host')}: {e}", file=sys.stderr)
                finally:
                    if client:
                        try:
                            client.close()
                        except:
                            pass
    
    except Exception as e:
        print(f"Warning: Could not get online status from X-UI: {e}", file=sys.stderr)
        pass

    users_list = list(users_dict.values())
    
    for user in users_list:
        user.setdefault('online_count', 0)

    # Конвертируем все datetime объекты в строки перед сериализацией
    users_list = convert_datetime_to_str(users_list)
    
    print(json.dumps(users_list, indent=2))

if __name__ == "__main__":
    main()