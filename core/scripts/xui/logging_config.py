#!/usr/bin/env python3
"""
Настройка логирования для X-UI модулей.
"""

import logging
from pathlib import Path

# Путь к файлу логов
XUI_LOG_FILE = Path("/var/log/hysteria_xui.log")

# Глобальный флаг для отслеживания инициализации
_logging_configured = False


def setup_xui_logging():
    """
    Настраивает логирование для X-UI модулей.
    Логи пишутся в /var/log/hysteria_xui.log
    """
    global _logging_configured
    
    if _logging_configured:
        return
    
    # Создаем директорию для логов если не существует
    log_dir = XUI_LOG_FILE.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Создаем handler для файла
    try:
        file_handler = logging.FileHandler(XUI_LOG_FILE, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        
        # Формат логов
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        # Настраиваем логгер для всех X-UI модулей (xui.xui_client, xui.xui_sync, etc.)
        # Используем корневой логгер 'xui' для всех подмодулей
        root_xui_logger = logging.getLogger('xui')
        root_xui_logger.setLevel(logging.DEBUG)
        
        # Проверяем, нет ли уже такого handler
        if not any(isinstance(h, logging.FileHandler) and hasattr(h, 'baseFilename') and 
                   h.baseFilename == str(XUI_LOG_FILE) for h in root_xui_logger.handlers):
            root_xui_logger.addHandler(file_handler)
        
        # Также добавляем StreamHandler для вывода в консоль (опционально)
        if not any(isinstance(h, logging.StreamHandler) for h in root_xui_logger.handlers):
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)  # В консоль только INFO и выше
            console_handler.setFormatter(formatter)
            root_xui_logger.addHandler(console_handler)
        
        # Настраиваем также для всех дочерних логгеров
        for module_name in ['xui.xui_client', 'xui.xui_sync', 'xui.sync_helper', 'xui.config']:
            module_logger = logging.getLogger(module_name)
            module_logger.setLevel(logging.DEBUG)
            
            # Добавляем handler если его еще нет
            if not any(isinstance(h, logging.FileHandler) and hasattr(h, 'baseFilename') and 
                       h.baseFilename == str(XUI_LOG_FILE) for h in module_logger.handlers):
                module_logger.addHandler(file_handler)
        
        _logging_configured = True
        
    except Exception as e:
        # Если не удалось настроить файловое логирование, используем только консоль
        logging.warning(f"Failed to setup X-UI file logging: {e}")


# Автоматически настраиваем логирование при импорте модуля
setup_xui_logging()
