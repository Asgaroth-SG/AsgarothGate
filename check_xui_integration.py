#!/usr/bin/env python3
"""
Скрипт для проверки интеграции X-UI на наличие ошибок.
"""

import sys
import os
from pathlib import Path

# Добавляем пути для импорта
sys.path.insert(0, '/etc/hysteria/core/scripts')
sys.path.insert(0, '/etc/hysteria/core')

def check_imports():
    """Проверка импортов модулей X-UI"""
    print("=" * 60)
    print("Проверка импортов модулей X-UI")
    print("=" * 60)
    
    errors = []
    
    # 1. Проверка py3xui
    print("\n1. Проверка библиотеки py3xui...")
    try:
        from py3xui import AsyncApi
        print("   ✓ py3xui установлена")
    except ImportError as e:
        errors.append(f"py3xui не установлена: {e}")
        print(f"   ✗ py3xui не установлена: {e}")
    
    # 2. Проверка nest_asyncio
    print("\n2. Проверка библиотеки nest_asyncio...")
    try:
        import nest_asyncio
        print("   ✓ nest_asyncio установлена")
    except ImportError as e:
        errors.append(f"nest_asyncio не установлена: {e}")
        print(f"   ✗ nest_asyncio не установлена: {e}")
    
    # 3. Проверка импорта xui.logging_config
    print("\n3. Проверка xui.logging_config...")
    try:
        from xui.logging_config import setup_xui_logging
        print("   ✓ xui.logging_config импортируется")
    except ImportError as e:
        errors.append(f"xui.logging_config не импортируется: {e}")
        print(f"   ✗ xui.logging_config не импортируется: {e}")
    
    # 4. Проверка импорта xui.xui_client
    print("\n4. Проверка xui.xui_client...")
    try:
        from xui.xui_client import XUIClient, XUIClientError, XUIAuthError, XUIConnectionError
        print("   ✓ xui.xui_client импортируется")
    except ImportError as e:
        errors.append(f"xui.xui_client не импортируется: {e}")
        print(f"   ✗ xui.xui_client не импортируется: {e}")
    except Exception as e:
        errors.append(f"Ошибка при импорте xui.xui_client: {e}")
        print(f"   ✗ Ошибка при импорте xui.xui_client: {e}")
    
    # 5. Проверка импорта xui.xui_sync
    print("\n5. Проверка xui.xui_sync...")
    try:
        from xui.xui_sync import XUISyncConfig, XUISyncManager
        print("   ✓ xui.xui_sync импортируется")
    except ImportError as e:
        errors.append(f"xui.xui_sync не импортируется: {e}")
        print(f"   ✗ xui.xui_sync не импортируется: {e}")
    except Exception as e:
        errors.append(f"Ошибка при импорте xui.xui_sync: {e}")
        print(f"   ✗ Ошибка при импорте xui.xui_sync: {e}")
    
    # 6. Проверка импорта xui.config
    print("\n6. Проверка xui.config...")
    try:
        from xui.config import load_xui_config, get_xui_sync_manager
        print("   ✓ xui.config импортируется")
    except ImportError as e:
        errors.append(f"xui.config не импортируется: {e}")
        print(f"   ✗ xui.config не импортируется: {e}")
    except Exception as e:
        errors.append(f"Ошибка при импорте xui.config: {e}")
        print(f"   ✗ Ошибка при импорте xui.config: {e}")
    
    # 7. Проверка импорта xui.sync_helper
    print("\n7. Проверка xui.sync_helper...")
    try:
        from xui.sync_helper import sync_user_create, sync_user_update, sync_user_delete
        print("   ✓ xui.sync_helper импортируется")
    except ImportError as e:
        errors.append(f"xui.sync_helper не импортируется: {e}")
        print(f"   ✗ xui.sync_helper не импортируется: {e}")
    except Exception as e:
        errors.append(f"Ошибка при импорте xui.sync_helper: {e}")
        print(f"   ✗ Ошибка при импорте xui.sync_helper: {e}")
    
    return errors

def check_files():
    """Проверка наличия всех необходимых файлов"""
    print("\n" + "=" * 60)
    print("Проверка наличия файлов")
    print("=" * 60)
    
    files = [
        "/etc/hysteria/core/scripts/xui/__init__.py",
        "/etc/hysteria/core/scripts/xui/xui_client.py",
        "/etc/hysteria/core/scripts/xui/xui_sync.py",
        "/etc/hysteria/core/scripts/xui/config.py",
        "/etc/hysteria/core/scripts/xui/sync_helper.py",
        "/etc/hysteria/core/scripts/xui/logging_config.py",
        "/etc/hysteria/xui_config.json",
        "/etc/hysteria/core/scripts/webpanel/routers/api/v1/config/xui.py",
        "/etc/hysteria/core/scripts/webpanel/routers/api/v1/schema/config/xui.py",
    ]
    
    missing = []
    for file_path in files:
        if os.path.exists(file_path):
            print(f"   ✓ {file_path}")
        else:
            missing.append(file_path)
            print(f"   ✗ {file_path} - НЕ НАЙДЕН")
    
    return missing

def check_config():
    """Проверка конфигурации X-UI"""
    print("\n" + "=" * 60)
    print("Проверка конфигурации X-UI")
    print("=" * 60)
    
    config_path = Path("/etc/hysteria/xui_config.json")
    
    if not config_path.exists():
        print(f"   ✗ Файл конфигурации не найден: {config_path}")
        return ["Конфигурационный файл не найден"]
    
    try:
        import json
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        print(f"   ✓ Файл конфигурации загружен")
        print(f"\n   Конфигурация:")
        print(f"   - Enabled: {config.get('enabled', False)}")
        print(f"   - Mode: {config.get('mode', 'N/A')}")
        print(f"   - Servers: {len(config.get('xui_servers', []))}")
        
        # Проверяем каждый сервер
        for i, server in enumerate(config.get('xui_servers', [])):
            print(f"\n   Сервер {i+1}:")
            print(f"     - Host: {server.get('host', 'N/A')}")
            print(f"     - Base Path: {server.get('base_path', 'N/A')}")
            print(f"     - Username: {'***' if server.get('username') else 'НЕ УКАЗАН'}")
            print(f"     - Password: {'***' if server.get('password') else 'НЕ УКАЗАН'}")
            print(f"     - Plans: {server.get('plans', [])}")
            
            if not server.get('username'):
                print(f"     ✗ ОШИБКА: Username не указан")
            if not server.get('password'):
                print(f"     ✗ ОШИБКА: Password не указан")
        
        return []
    except Exception as e:
        print(f"   ✗ Ошибка при чтении конфигурации: {e}")
        return [f"Ошибка чтения конфигурации: {e}"]

def check_syntax():
    """Проверка синтаксиса Python файлов"""
    print("\n" + "=" * 60)
    print("Проверка синтаксиса Python файлов")
    print("=" * 60)
    
    files = [
        "/etc/hysteria/core/scripts/xui/xui_client.py",
        "/etc/hysteria/core/scripts/xui/xui_sync.py",
        "/etc/hysteria/core/scripts/xui/config.py",
        "/etc/hysteria/core/scripts/xui/sync_helper.py",
        "/etc/hysteria/core/scripts/xui/logging_config.py",
        "/etc/hysteria/core/scripts/webpanel/routers/api/v1/config/xui.py",
    ]
    
    errors = []
    for file_path in files:
        if not os.path.exists(file_path):
            continue
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            compile(code, file_path, 'exec')
            print(f"   ✓ {os.path.basename(file_path)}")
        except SyntaxError as e:
            errors.append(f"{file_path}: {e}")
            print(f"   ✗ {os.path.basename(file_path)}: {e}")
    
    return errors

def main():
    print("\n" + "=" * 60)
    print("ПРОВЕРКА ИНТЕГРАЦИИ X-UI С HYSTERIA 2")
    print("=" * 60)
    
    all_errors = []
    
    # 1. Проверка файлов
    missing_files = check_files()
    all_errors.extend(missing_files)
    
    # 2. Проверка синтаксиса
    syntax_errors = check_syntax()
    all_errors.extend(syntax_errors)
    
    # 3. Проверка конфигурации
    config_errors = check_config()
    all_errors.extend(config_errors)
    
    # 4. Проверка импортов
    import_errors = check_imports()
    all_errors.extend(import_errors)
    
    # Итоги
    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТЫ ПРОВЕРКИ")
    print("=" * 60)
    
    if not all_errors:
        print("\n✓ Все проверки пройдены успешно!")
        print("\nИнтеграция X-UI настроена корректно.")
        return 0
    else:
        print(f"\n✗ Найдено ошибок: {len(all_errors)}")
        print("\nСписок ошибок:")
        for i, error in enumerate(all_errors, 1):
            print(f"{i}. {error}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
