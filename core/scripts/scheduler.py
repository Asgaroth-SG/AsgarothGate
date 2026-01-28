#!/usr/bin/env python3
import time
import schedule
import logging
import subprocess
import fcntl
from pathlib import Path
from paths import *

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("/var/log/hysteria_scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("HysteriaScheduler")

# Constants
BASE_DIR = Path("/etc/hysteria")
VENV_ACTIVATE = BASE_DIR / "hysteria2_venv/bin/activate"
LOCK_FILE = "/tmp/hysteria_scheduler.lock"

# Импортируем CLI_PATH из paths
try:
    from paths import CLI_PATH
except ImportError:
    # Fallback если paths не доступен
    CLI_PATH = BASE_DIR / "core/cli.py"

def acquire_lock():
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except IOError:
        logger.warning("Another process is already running and has the lock")
        return None

def release_lock(lock_fd):
    if lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

def run_command(command, log_success=False):
    # Используем абсолютный путь к Python из venv
    python_path = BASE_DIR / "hysteria2_venv/bin/python3"
    pip_path = BASE_DIR / "hysteria2_venv/bin/pip3"
    
    # Проверяем существование venv
    if not python_path.exists():
        logger.warning(f"Python venv not found at {python_path}, trying system python3")
        python_path = Path("/usr/bin/python3")
        pip_path = Path("/usr/bin/pip3")
        if not python_path.exists():
            logger.error("System python3 not found either")
            return False
    
    # Проверяем наличие модуля click перед выполнением команды
    if "cli.py" in command or "traffic-status" in command:
        try:
            check_result = subprocess.run(
                [str(python_path), "-c", "import click"],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(BASE_DIR)
            )
            if check_result.returncode != 0:
                logger.warning("Module 'click' not found, attempting to install dependencies...")
                if pip_path.exists():
                    # Устанавливаем из requirements.txt если он существует
                    requirements_file = BASE_DIR / "requirements.txt"
                    if requirements_file.exists():
                        logger.info(f"Installing dependencies from {requirements_file}")
                        install_result = subprocess.run(
                            [str(pip_path), "install", "-r", str(requirements_file)],
                            capture_output=True,
                            text=True,
                            timeout=300,  # 5 минут на установку всех зависимостей
                            cwd=str(BASE_DIR)
                        )
                        if install_result.returncode != 0:
                            logger.error(f"Failed to install dependencies: {install_result.stderr}")
                            logger.error(f"Please run manually: {pip_path} install -r {requirements_file}")
                            return False
                        else:
                            logger.info("Successfully installed dependencies from requirements.txt")
                    else:
                        # Если requirements.txt не найден, устанавливаем только click
                        logger.warning("requirements.txt not found, installing only click")
                        install_result = subprocess.run(
                            [str(pip_path), "install", "click==8.3.1"],
                            capture_output=True,
                            text=True,
                            timeout=60,
                            cwd=str(BASE_DIR)
                        )
                        if install_result.returncode != 0:
                            logger.error(f"Failed to install click: {install_result.stderr}")
                            return False
                        else:
                            logger.info("Successfully installed click module")
                else:
                    logger.error(f"pip3 not found at {pip_path}, cannot install dependencies")
                    logger.error(f"Please install dependencies manually: pip3 install -r {BASE_DIR}/requirements.txt")
                    return False
        except Exception as e:
            logger.warning(f"Error checking for click module: {e}")
    
    # Разбиваем команду на части (например: "core/cli.py traffic-status --no-gui")
    cmd_parts = command.split()
    
    # Определяем путь к скрипту
    if cmd_parts and cmd_parts[0].endswith('.py'):
        # Если первый аргумент - это путь к скрипту
        script_path = BASE_DIR / cmd_parts[0] if not Path(cmd_parts[0]).is_absolute() else Path(cmd_parts[0])
        args = cmd_parts[1:]
    else:
        # Иначе используем CLI_PATH
        script_path = CLI_PATH
        args = cmd_parts
    
    # Формируем полную команду
    full_cmd = [str(python_path), str(script_path)] + args
    
    try:
        result = subprocess.run(
            full_cmd,
            cwd=str(BASE_DIR),  # Устанавливаем рабочую директорию
            capture_output=True,
            text=True,
            timeout=300  # Таймаут 5 минут
        )
        
        if result.returncode != 0:
            logger.error(f"Command failed: {' '.join(full_cmd)}")
            logger.error(f"Error: {result.stderr}")
            if result.stdout:
                logger.debug(f"Output: {result.stdout}")
        elif log_success:
            logger.info(f"Command executed successfully: {' '.join(full_cmd)}")
            
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after 300 seconds: {' '.join(full_cmd)}")
        return False
    except Exception as e:
        logger.exception(f"Exception running command: {' '.join(full_cmd)}")
        return False

def check_traffic_status():
    lock_fd = acquire_lock()
    if not lock_fd:
        return
        
    try:
        # Используем относительный путь от BASE_DIR для CLI
        if CLI_PATH.is_absolute() and BASE_DIR in CLI_PATH.parents:
            cli_relative = CLI_PATH.relative_to(BASE_DIR)
        else:
            cli_relative = Path("core/cli.py")  # Fallback путь
        success = run_command(f"{cli_relative} traffic-status --no-gui", log_success=False)
        if not success:
            pass
    finally:
        release_lock(lock_fd)

def backup_hysteria():
    lock_fd = acquire_lock()
    if not lock_fd:
        logger.warning("Skipping backup due to lock")
        return
        
    try:
        # Используем относительный путь от BASE_DIR для CLI
        if CLI_PATH.is_absolute() and BASE_DIR in CLI_PATH.parents:
            cli_relative = CLI_PATH.relative_to(BASE_DIR)
        else:
            cli_relative = Path("core/cli.py")  # Fallback путь
        run_command(f"{cli_relative} backup-hysteria", log_success=True)
    finally:
        release_lock(lock_fd)

def main():
    logger.info("Starting Hysteria Scheduler")
    
    # Обновление статусов онлайн каждые 30 секунд для более точного отслеживания
    schedule.every(30).seconds.do(check_traffic_status)
    schedule.every(6).hours.do(backup_hysteria)
    
    check_traffic_status()
    backup_hysteria()
    
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down scheduler")
            break
        except Exception as e:
            logger.exception("Error in main loop")
            time.sleep(60)

if __name__ == "__main__":
    main()