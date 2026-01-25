from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional

class User(BaseModel):
    username: str
    status: str
    quota: str
    traffic_used: str
    expiry_date: str
    expiry_days: str
    day_usage: str
    enable: bool
    unlimited_ip: bool
    max_ips: int = 0
    online_count: int = 0
    note: Optional[str] = None
    # Тариф пользователя: 'standard' или 'premium'
    plan: str = "standard"
    # Статус синхронизации с X-UI: 'success', 'failed', 'not_synced', 'unknown'
    xui_sync_status: Optional[str] = None

    @staticmethod
    def from_dict(username: str, user_data: dict):
        user_data = {'username': username, **user_data}
        user_data = User.__parse_user_data(user_data)
        
        # Получаем статус синхронизации X-UI из БД
        try:
            import sys
            sys.path.insert(0, '/etc/hysteria/core/scripts')
            from db.database import db
            if db:
                mapping = db.get_xui_mapping(username)
                if mapping:
                    user_data['xui_sync_status'] = mapping.get('sync_status', 'unknown')
                else:
                    user_data['xui_sync_status'] = 'not_synced'
            else:
                user_data['xui_sync_status'] = None
        except Exception:
            user_data['xui_sync_status'] = None
        
        return User(**user_data)

    @staticmethod
    def __parse_user_data(user_data: dict) -> dict:
        # Безопасное получение и конвертация max_ips
        raw_max_ips = user_data.get('max_ips')
        try:
            # Если значение есть (не None), пробуем превратить в число. Иначе 0.
            max_ips = int(raw_max_ips) if raw_max_ips is not None else 0
        except (ValueError, TypeError):
            max_ips = 0

        # Тариф/план пользователя, по умолчанию стандартный
        plan = user_data.get('plan', 'standard')

        essential_keys = [
            'password',
            'max_download_bytes',
            'expiration_days',
            'blocked'
        ]

        if not all(key in user_data for key in essential_keys):
            return {
                'username': user_data.get('username', 'Unknown'),
                'status': 'Conflict',
                'quota': 'N/A',
                'traffic_used': 'N/A',
                'expiry_date': 'N/A',
                'expiry_days': 'N/A',
                'day_usage': 'N/A',
                'enable': False,
                'unlimited_ip': False,
                'max_ips': max_ips,  # Используем обработанное значение
                'online_count': 0,
                'note': user_data.get('note', None),
                'plan': plan,
            }

        expiration_days = user_data.get('expiration_days', 0)
        creation_date_str = user_data.get("account_creation_date")

        day_usage = "On-hold"
        display_expiry_days = "On-hold"
        display_expiry_date = "On-hold"

        if creation_date_str:
            try:
                creation_date = datetime.strptime(creation_date_str, "%Y-%m-%d")
                day_usage = str((datetime.now() - creation_date).days)

                if expiration_days <= 0:
                    display_expiry_days = "Unlimited"
                    display_expiry_date = "Unlimited"
                else:
                    display_expiry_days = str(expiration_days)
                    expiry_dt_obj = creation_date + timedelta(days=expiration_days)
                    display_expiry_date = expiry_dt_obj.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                display_expiry_date = "Error"
                day_usage = "Error"

        used_bytes = user_data.get("download_bytes", 0) + user_data.get("upload_bytes", 0)
        quota_bytes = user_data.get('max_download_bytes', 0)

        used_formatted = User.__format_traffic(used_bytes)
        quota_formatted = "Безлимит" if quota_bytes <= 0 else User.__format_traffic(quota_bytes)

        percentage = 0
        if quota_bytes > 0:
            percentage = (used_bytes / quota_bytes) * 100

        traffic_used_display = f"{used_formatted}/{quota_formatted} ({percentage:.1f}%)"

        # Определяем финальный статус пользователя
        final_status = user_data.get('status', 'Not Active')
        
        # Если статус "On-hold" или "Offline", проверяем статус онлайна из 3X-UI
        if final_status in ('On-hold', 'Offline'):
            try:
                import sys
                sys.path.insert(0, '/etc/hysteria/core/scripts')
                from db.database import db
                from xui.config import load_xui_config
                
                if db:
                    mapping = db.get_xui_mapping(user_data['username'])
                    if mapping:
                        client_uuid = mapping.get('xui_client_uuid')
                        xui_host = mapping.get('xui_host')
                        
                        if client_uuid:
                            config = load_xui_config()
                            if config.get('enabled', False):
                                servers = config.get('xui_servers', [])
                                if servers:
                                    # Находим сервер
                                    target_server = None
                                    if xui_host:
                                        for server in servers:
                                            if server.get('host') == xui_host and server.get('enabled', True):
                                                target_server = server
                                                break
                                    
                                    if not target_server:
                                        for server in servers:
                                            if server.get('enabled', True):
                                                target_server = server
                                                break
                                    
                                    if target_server:
                                        from xui.xui_api_wrapper import XUIAPIWrapper
                                        
                                        auth_type = target_server.get('auth_type', 'username')
                                        if auth_type == 'token':
                                            xui_username = 'admin'
                                        else:
                                            xui_username = target_server.get('username', '')
                                        
                                        xui_password = target_server.get('password', '')
                                        
                                        if xui_password:
                                            try:
                                                # Используем короткий таймаут для быстрой проверки в интерфейсе
                                                client = XUIAPIWrapper(
                                                    host=target_server.get('host'),
                                                    username=xui_username,
                                                    password=xui_password,
                                                    base_path=target_server.get('base_path', '/'),
                                                    timeout=3  # Короткий таймаут для быстрой проверки
                                                )
                                                
                                                try:
                                                    # Проверяем по UUID
                                                    is_online = client.is_client_online(client_uuid)
                                                    
                                                    if not is_online:
                                                        # Пробуем по email
                                                        inbound_ids = mapping.get('inbound_ids', [])
                                                        for inbound_id in inbound_ids:
                                                            client_email = f"{user_data['username']}_{inbound_id}"
                                                            if client.is_client_online(client_email):
                                                                is_online = True
                                                                break
                                                    
                                                    # Если пользователь онлайн в 3X-UI, меняем статус на Online
                                                    # (для On-hold это активация, для Offline - обновление статуса)
                                                    if is_online:
                                                        final_status = 'Online'
                                                finally:
                                                    try:
                                                        client.close()
                                                    except:
                                                        pass
                                            except Exception:
                                                # Игнорируем ошибки проверки статуса
                                                pass
            except Exception:
                # Игнорируем ошибки при проверке статуса из 3X-UI
                pass
        
        return {
            'username': user_data['username'],
            'status': final_status,
            'quota': quota_formatted,
            'traffic_used': traffic_used_display,
            'expiry_date': display_expiry_date,
            'expiry_days': display_expiry_days,
            'day_usage': day_usage,
            'enable': not user_data.get('blocked', False),
            'unlimited_ip': user_data.get('unlimited_user', False),
            'max_ips': max_ips,  # Используем обработанное значение
            'online_count': user_data.get('online_count', 0),
            'note': user_data.get('note', None),
            'plan': plan,
        }

    @staticmethod
    def __format_traffic(traffic_bytes) -> str:
        if traffic_bytes <= 0:
            return "0 B"
        if traffic_bytes < 1024:
            return f'{traffic_bytes} B'
        elif traffic_bytes < 1024**2:
            return f'{traffic_bytes / 1024:.2f} KB'
        elif traffic_bytes < 1024**3:
            return f'{traffic_bytes / 1024**2:.2f} MB'
        else:
            return f'{traffic_bytes / 1024**3:.2f} GB'
