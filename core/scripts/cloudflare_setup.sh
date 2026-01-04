#!/bin/bash

# Подгружаем общие переменные и цвета (если они есть в utils.sh, иначе определяем тут)
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

INI_FILE="/etc/hysteria/cloudflare.ini"
VENV_DIR="/etc/hysteria/hysteria2_venv"
CLI_PATH="/etc/hysteria/core/cli.py"

echo -e "${CYAN}--- Настройка Cloudflare DNS SSL ---${NC}"
echo "Этот скрипт настроит автоматическое получение сертификатов через Cloudflare API."
echo "Это позволяет использовать 'чистый' сертификат и скрывать IP сервера."
echo ""

# 1. Проверка и установка зависимостей
echo -e "${YELLOW}[1/3] Проверка зависимостей...${NC}"
if [ -d "$VENV_DIR" ]; then
    source "$VENV_DIR/bin/activate"
    if ! pip show certbot-dns-cloudflare > /dev/null 2>&1; then
        echo "Установка плагина certbot-dns-cloudflare..."
        pip install certbot certbot-dns-cloudflare
        if [ $? -ne 0 ]; then
            echo -e "${RED}Ошибка установки pip пакетов.${NC}"
            deactivate
            exit 1
        fi
        echo -e "${GREEN}Плагин установлен.${NC}"
    else
        echo -e "${GREEN}Плагин уже установлен.${NC}"
    fi
else
    echo -e "${RED}Виртуальное окружение не найдено!${NC}"
    exit 1
fi

# 2. Ввод и сохранение токена
echo -e "\n${YELLOW}[2/3] Настройка API Token${NC}"
if [ -f "$INI_FILE" ]; then
    echo -e "Файл настроек уже существует."
    read -p "Хотите перезаписать токен? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Используем текущий токен."
        SKIP_TOKEN=true
    fi
fi

if [ "$SKIP_TOKEN" != "true" ]; then
    echo -e "Введите ваш ${CYAN}Cloudflare API Token${NC} (Permissions: Zone:DNS:Edit):"
    read -r CF_TOKEN
    
    if [ -z "$CF_TOKEN" ]; then
        echo -e "${RED}Токен не может быть пустым.${NC}"
        deactivate
        exit 1
    fi

    # Записываем в файл
    echo "dns_cloudflare_api_token = $CF_TOKEN" > "$INI_FILE"
    chmod 600 "$INI_FILE"
    echo -e "${GREEN}Токен сохранен в $INI_FILE (права 600).${NC}"
fi

# 3. Выпуск сертификата через CLI
echo -e "\n${YELLOW}[3/3] Выпуск сертификата${NC}"
echo -e "Введите домен (SNI), для которого нужно выпустить сертификат."
echo -e "Убедитесь, что домен добавлен в ваш аккаунт Cloudflare."
read -p "Домен (например, vpn.example.com): " DOMAIN

if [ -z "$DOMAIN" ]; then
    echo -e "${RED}Домен не введен.${NC}"
    deactivate
    exit 1
fi

echo -e "Запускаем процесс получения сертификата для ${CYAN}$DOMAIN${NC}..."
# Вызываем наш Python CLI, который уже умеет работать с cloudflare.ini
python3 "$CLI_PATH" change-hysteria2-sni --sni "$DOMAIN"

deactivate

echo -e "\n${GREEN}Готово!${NC}"
echo -e "Нажмите Enter, чтобы вернуться в меню."
read