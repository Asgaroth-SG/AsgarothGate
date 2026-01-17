#!/usr/bin/env python3
"""
Скрипт для синхронизации существующих пользователей с 3X-UI
"""
import sys
from pathlib import Path

# Добавляем путь к модулям
sys.path.insert(0, '/etc/hysteria/core/scripts')

from xui.config import get_xui_sync_manager
from db.database import db

def sync_all_users():
    sync_manager = get_xui_sync_manager()
    if not sync_manager:
        print("❌ X-UI sync is not enabled or not configured")
        print("   Check /etc/hysteria/xui_config.json")
        return
    
    if not db:
        print("❌ Database connection failed")
        return
    
    users = db.get_all_users()
    print(f"📋 Found {len(users)} users to sync\n")
    
    success_count = 0
    failed_count = 0
    
    for user in users:
        username = user['_id']
        plan = user.get('plan', 'standard')
        expiry_days = user.get('expiration_days', 0)
        traffic_bytes = user.get('max_download_bytes', 0)
        traffic_gb = int(traffic_bytes / (1024 ** 3)) if traffic_bytes > 0 else 0
        enable = not user.get('blocked', False)
        
        print(f"🔄 Syncing user: {username} (plan: {plan}, traffic: {traffic_gb}GB, expiry: {expiry_days} days)")
        
        success, error = sync_manager.sync_user_create(
            hysteria_username=username,
            expiry_days=expiry_days,
            traffic_limit_gb=traffic_gb,
            enable=enable,
            user_plan=plan
        )
        
        if success:
            print(f"   ✅ Successfully synced {username}\n")
            success_count += 1
        else:
            print(f"   ❌ Failed to sync {username}: {error}\n")
            failed_count += 1
    
    print(f"\n📊 Summary:")
    print(f"   ✅ Success: {success_count}")
    print(f"   ❌ Failed: {failed_count}")
    print(f"   📝 Total: {len(users)}")

if __name__ == "__main__":
    sync_all_users()
