#!/bin/bash

set -euo pipefail
trap 'echo -e "\n❌ Произошла ошибка. Прерывание."; exit 1' ERR

# ========== Переменные ==========
HYSTERIA_INSTALL_DIR="/etc/hysteria"
HYSTERIA_VENV_DIR="$HYSTERIA_INSTALL_DIR/hysteria2_venv"
GEOSITE_URL="https://raw.githubusercontent.com/runetfreedom/russia-blocked-geosite/release/geosite.dat"
GEOIP_URL="https://raw.githubusercontent.com/runetfreedom/russia-blocked-geoip/release/geoip.dat"
MIGRATE_SCRIPT_PATH="$HYSTERIA_INSTALL_DIR/core/scripts/db/migrate_users.py"

# ========== Настройка цветов ==========
GREEN=$(tput setaf 2)
RED=$(tput setaf 1)
YELLOW=$(tput setaf 3)
BLUE=$(tput setaf 4)
RESET=$(tput sgr0)

info() { echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')] [ИНФО] - ${RESET} $1"; }
success() { echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] [ОК] - ${RESET} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] [ВНИМАНИЕ] - ${RESET} $1"; }
error() { echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] [ОШИБКА] - ${RESET} $1"; }

# ========== Проверка поддержки AVX ==========
check_avx_support() {
    info "Проверка процессора на поддержку AVX (требуется для MongoDB)..."
    if grep -q -m1 -o -E 'avx|avx2|avx512' /proc/cpuinfo; then
        success "Процессор поддерживает набор инструкций AVX."
    else
        error "Процессор не поддерживает требуемый набор инструкций AVX для MongoDB."
        info "Ваша система не совместима с этой версией."
        info "Пожалуйста, используйте скрипт обновления 'nodb' (без базы данных):"
        echo -e "${YELLOW}bash <(curl -sL https://raw.githubusercontent.com/Asgaroth-SG/AsgarothGate/nodb/upgrade.sh)${RESET}"
        error "Обновление прервано."
        exit 1
    fi
}

# ========== Исправление репозитория Caddy ==========
fix_caddy_repo() {
    info "Проверка конфигурации репозитория Caddy..."
    local caddy_source_list="/etc/apt/sources.list.d/caddy-stable.list"
    local new_caddy_keyring="/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
    local old_caddy_key="/etc/apt/trusted.gpg.d/caddy.asc"

    if [[ -f "$old_caddy_key" ]] || { [[ -f "$caddy_source_list" ]] && grep -q "caddy.asc" "$caddy_source_list"; }; then
        warn "Обнаружена устаревшая конфигурация репозитория Caddy. Исправляем..."
        
        if [[ -f "$old_caddy_key" ]]; then
            rm -f "$old_caddy_key"
            info "Удален старый GPG ключ Caddy."
        fi
        
        rm -f "$new_caddy_keyring"
        info "Скачивание нового GPG ключа Caddy..."
        if ! curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o "$new_caddy_keyring"; then
            error "Не удалось скачать или обработать GPG ключ Caddy."
            exit 1
        fi
        
        info "Обновление списка источников Caddy..."
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee "$caddy_source_list" > /dev/null
        
        chmod o+r "$new_caddy_keyring"
        chmod o+r "$caddy_source_list"
        
        info "Запуск apt update для применения изменений репозитория..."
        apt-get update -qq
        success "Конфигурация репозитория Caddy обновлена."
    else
        success "Конфигурация репозитория Caddy актуальна."
    fi
}

# ========== Установка MongoDB ==========
install_mongodb() {
    info "Проверка наличия MongoDB..."
    if ! command -v mongod &>/dev/null; then
        warn "MongoDB не найдена. Установка из официального репозитория..."
        
        local os_name os_version
        os_name=$(grep '^ID=' /etc/os-release | cut -d= -f2 | tr -d '"')
        os_version=$(grep '^VERSION_ID=' /etc/os-release | cut -d= -f2 | tr -d '"')
        
        apt-get update 
        apt-get install -y gnupg curl lsb-release
        
        curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
        
        if [[ "$os_name" == "ubuntu" ]]; then
            if [[ "$os_version" == "24.04" ]]; then
                echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu noble/mongodb-org/8.0 multiverse" > /etc/apt/sources.list.d/mongodb-org-8.0.list
            elif [[ "$os_version" == "22.04" ]]; then
                echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/8.0 multiverse" > /etc/apt/sources.list.d/mongodb-org-8.0.list
            else
                echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/8.0 multiverse" > /etc/apt/sources.list.d/mongodb-org-8.0.list
            fi
        elif [[ "$os_name" == "debian" && "$os_version" == "12" ]]; then
            echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] http://repo.mongodb.org/apt/debian bookworm/mongodb-org/8.0 main" > /etc/apt/sources.list.d/mongodb-org-8.0.list
        else
            error "Неподдерживаемая ОС для установки MongoDB: $os_name $os_version"
            exit 1
        fi
        
        apt-get update -qq
        apt-get install -y mongodb-org
        systemctl start mongod
        systemctl enable mongod
        success "MongoDB успешно установлена и запущена."
    else
        success "MongoDB уже установлена."
    fi
}

# ========== Новая функция для миграции данных ==========
migrate_json_to_mongo() {
    info "Проверка необходимости миграции пользовательских данных..."
    if [[ -f "$HYSTERIA_INSTALL_DIR/users.json" ]]; then
        info "Найден users.json. Приступаем к миграции в MongoDB."
        if python3 "$MIGRATE_SCRIPT_PATH"; then
            success "Миграция данных успешно завершена."
        else
            error "Скрипт миграции данных завершился с ошибкой. Пожалуйста, проверьте вывод выше."
            exit 1
        fi
    else
        info "users.json не найден. Миграция пропущена."
    fi
}

download_and_extract_latest_release() {
    local arch
    case $(uname -m) in
        x86_64) arch="amd64" ;;
        aarch64) arch="arm64" ;;
        *)
            error "Неподдерживаемая архитектура: $(uname -m)"
            exit 1
            ;;
    esac
    info "Обнаружена архитектура: $arch"

    local zip_name="AsgarothGate-${arch}.zip"
    local download_url="https://github.com/Asgaroth-SG/AsgarothGate/releases/latest/download/${zip_name}"
    local temp_zip="/tmp/${zip_name}"

    info "Скачивание последнего релиза с ${download_url}..."
    if ! curl -sL -o "$temp_zip" "$download_url"; then
        error "Не удалось скачать архив релиза. Пожалуйста, проверьте URL и ваше соединение."
        exit 1
    fi
    success "Скачивание завершено."

    info "Удаление старой директории установки..."
    rm -rf "$HYSTERIA_INSTALL_DIR"
    mkdir -p "$HYSTERIA_INSTALL_DIR"
    
    info "Распаковка в ${HYSTERIA_INSTALL_DIR}..."
    if ! unzip -q "$temp_zip" -d "$HYSTERIA_INSTALL_DIR"; then
        error "Не удалось распаковать архив."
        exit 1
    fi
    success "Распаковка прошла успешно."
    
    rm "$temp_zip"
    info "Временный файл удален."
}

# ========== Захват активных сервисов ==========
declare -a ACTIVE_SERVICES_BEFORE_UPGRADE=()
ALL_SERVICES=(
    hysteria-caddy.service
    hysteria-server.service
    hysteria-auth.service
    hysteria-scheduler.service
    hysteria-telegram-bot.service
    hysteria-normal-sub.service
    hysteria-caddy-normalsub.service
    hysteria-webpanel.service
    hysteria-ip-limit.service
)

info "Проверка активных сервисов перед обновлением..."
for SERVICE in "${ALL_SERVICES[@]}"; do
    if systemctl is-active --quiet "$SERVICE"; then
        ACTIVE_SERVICES_BEFORE_UPGRADE+=("$SERVICE")
        info "Сервис '$SERVICE' активен и будет перезапущен."
    fi
done

# ========== Проверка поддержки AVX (Предварительное условие) ==========
check_avx_support

# ========== Исправление репозитория Caddy (Предварительное условие) ==========
fix_caddy_repo

# ========== Установка MongoDB (Предварительное условие) ==========
install_mongodb

# ========== Резервное копирование файлов ==========
cd /root
TEMP_DIR=$(mktemp -d)
FILES=(
    "$HYSTERIA_INSTALL_DIR/ca.key"
    "$HYSTERIA_INSTALL_DIR/ca.crt"
    "$HYSTERIA_INSTALL_DIR/users.json"
    "$HYSTERIA_INSTALL_DIR/config.json"
    "$HYSTERIA_INSTALL_DIR/.configs.env"
    "$HYSTERIA_INSTALL_DIR/nodes.json"
    "$HYSTERIA_INSTALL_DIR/extra.json"
    "$HYSTERIA_INSTALL_DIR/core/scripts/telegrambot/.env"
    "$HYSTERIA_INSTALL_DIR/core/scripts/normalsub/.env"
    "$HYSTERIA_INSTALL_DIR/core/scripts/normalsub/Caddyfile.normalsub"
    "$HYSTERIA_INSTALL_DIR/core/scripts/webpanel/.env"
    "$HYSTERIA_INSTALL_DIR/core/scripts/webpanel/Caddyfile"
    "$HYSTERIA_INSTALL_DIR/xui_config.json"
)

info "Резервное копирование конфигурационных файлов в: $TEMP_DIR"
for FILE in "${FILES[@]}"; do
    if [[ -f "$FILE" ]]; then
        mkdir -p "$TEMP_DIR/$(dirname "$FILE")"
        cp -p "$FILE" "$TEMP_DIR/$FILE"
        success "Создана резервная копия: $FILE"
    else
        warn "Файл не найден: $FILE"
    fi
done

# ========== Скачивание и замена установки ==========
download_and_extract_latest_release

# ========== Скачивание Geo-данных ==========
info "Скачивание geosite.dat и geoip.dat..."
wget -q -O "$HYSTERIA_INSTALL_DIR/geosite.dat" "$GEOSITE_URL"
wget -q -O "$HYSTERIA_INSTALL_DIR/geoip.dat" "$GEOIP_URL"
success "Geo-данные скачаны."

# ========== Восстановление резервной копии ==========
info "Восстановление конфигурационных файлов..."
for FILE in "${FILES[@]}"; do
    BACKUP="$TEMP_DIR/$FILE"
    if [[ -f "$BACKUP" ]]; then
        # Создаем директорию если не существует
        mkdir -p "$(dirname "$FILE")"
        cp -p "$BACKUP" "$FILE"
        success "Восстановлен: $FILE"
    else
        warn "Отсутствует файл резервной копии: $BACKUP"
    fi
done

# Устанавливаем права доступа для xui_config.json (если файл существует)
if [[ -f "$HYSTERIA_INSTALL_DIR/xui_config.json" ]]; then
    chmod 600 "$HYSTERIA_INSTALL_DIR/xui_config.json"
    success "Права доступа для xui_config.json установлены."
fi

# ========== Обновление конфигурации ==========
info "Обновление конфигурации Hysteria для HTTP аутентификации..."
auth_block='{"type": "http", "http": {"url": "http://127.0.0.1:28262/auth"}}'
if [[ -f "$HYSTERIA_INSTALL_DIR/config.json" ]]; then
    jq --argjson auth_block "$auth_block" '.auth = $auth_block' "$HYSTERIA_INSTALL_DIR/config.json" > "$HYSTERIA_INSTALL_DIR/config.json.tmp" && mv "$HYSTERIA_INSTALL_DIR/config.json.tmp" "$HYSTERIA_INSTALL_DIR/config.json"
    success "config.json обновлен для использования сервера аутентификации."
else
    warn "config.json не найден после восстановления. Пропуск обновления аутентификации."
fi

# ========== Права доступа ==========
info "Настройка владельца и прав доступа..."
if id -u hysteria >/dev/null 2>&1; then
    chown hysteria:hysteria "$HYSTERIA_INSTALL_DIR/ca.key" "$HYSTERIA_INSTALL_DIR/ca.crt" 2>/dev/null || true
    chmod 640 "$HYSTERIA_INSTALL_DIR/ca.key" "$HYSTERIA_INSTALL_DIR/ca.crt" 2>/dev/null || true
    chown -R hysteria:hysteria "$HYSTERIA_INSTALL_DIR/core/scripts/telegrambot" 2>/dev/null || true
fi
chmod +x "$HYSTERIA_INSTALL_DIR/core/scripts/hysteria2/kick.py"
chmod +x "$HYSTERIA_INSTALL_DIR/core/scripts/auth/user_auth"
# Установка прав на выполнение для основных скриптов
if [[ -f "$HYSTERIA_INSTALL_DIR/install.sh" ]]; then
    chmod +x "$HYSTERIA_INSTALL_DIR/install.sh"
    info "Права на выполнение установлены для install.sh"
fi
if [[ -f "$HYSTERIA_INSTALL_DIR/menu.sh" ]]; then
    chmod +x "$HYSTERIA_INSTALL_DIR/menu.sh"
    info "Права на выполнение установлены для menu.sh"
fi
if [[ -f "$HYSTERIA_INSTALL_DIR/upgrade.sh" ]]; then
    chmod +x "$HYSTERIA_INSTALL_DIR/upgrade.sh"
    info "Права на выполнение установлены для upgrade.sh"
fi
# Установка прав на выполнение для скриптов в core/scripts
find "$HYSTERIA_INSTALL_DIR/core/scripts" -type f -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true
success "Права доступа обновлены."

# ========== Виртуальное окружение ==========
info "Настройка виртуального окружения и установка зависимостей..."
cd "$HYSTERIA_INSTALL_DIR"
python3 -m venv "$HYSTERIA_VENV_DIR"
source "$HYSTERIA_VENV_DIR/bin/activate"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt >/dev/null
# Установка py3xui и nest-asyncio для интеграции с 3X-UI
info "Установка py3xui и nest-asyncio для интеграции с 3X-UI..."
if pip install py3xui nest-asyncio >/dev/null 2>&1; then
    success "py3xui и nest-asyncio установлены."
else
    warn "Не удалось установить py3xui/nest-asyncio. Установите вручную: pip install py3xui nest-asyncio"
fi
success "Среда Python готова."

# ========== Миграция данных ==========
migrate_json_to_mongo

# ========== Сервисы Systemd ==========
info "Обеспечение конфигурации сервисов systemd..."
if source "$HYSTERIA_INSTALL_DIR/core/scripts/scheduler.sh"; then
    if ! check_auth_server_service; then
        setup_hysteria_auth_server && success "Сервис сервера аутентификации настроен." || warn "Настройка сервера аутентификации не удалась."
    else
        success "Сервис сервера аутентификации уже настроен."
    fi

    if ! check_scheduler_service; then
        setup_hysteria_scheduler && success "Сервис планировщика настроен." || warn "Настройка планировщика не удалась."
    else
        success "Сервис планировщика уже настроен."
    fi
else
    warn "Не удалось загрузить scheduler.sh, продолжаем без настройки сервисов..."
fi

# ========== Перезапуск сервисов ==========
info "Перезагрузка демона systemd..."
systemctl daemon-reload

info "Перезапуск сервисов, которые были активны до обновления..."
if [ ${#ACTIVE_SERVICES_BEFORE_UPGRADE[@]} -eq 0 ]; then
    warn "Не было активных соответствующих сервисов до обновления. Пропуск перезапуска."
else
    for SERVICE in "${ACTIVE_SERVICES_BEFORE_UPGRADE[@]}"; do
        info "Попытка перезапуска $SERVICE..."
        systemctl enable "$SERVICE" &>/dev/null || warn "Не удалось включить $SERVICE. Возможно, он не существует."
        systemctl restart "$SERVICE"
        sleep 2
        if systemctl is-active --quiet "$SERVICE"; then
            success "$SERVICE успешно перезапущен и активен."
        else
            warn "$SERVICE не удалось перезапустить или он не активен."
            warn "Показ последних 5 записей журнала для $SERVICE:"
            journalctl -u "$SERVICE" -n 5 --no-pager
        fi
    done
fi

# ========== Финальная проверка ==========
if systemctl is-active --quiet hysteria-server.service; then
    success "🎉 Обновление успешно завершено!"
else
    warn "⚠️ hysteria-server.service не активен. Проверьте журналы при необходимости."
fi

# ========== Завершение ==========
info "Процесс обновления завершен."
success "Вы можете вернуться в меню, выбрав соответствующую опцию."