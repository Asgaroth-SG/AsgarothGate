#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[1;94m'
NC='\033[0m'
BOLD='\033[1m'

CHECK_MARK="[✓]"
CROSS_MARK="[✗]"
INFO_MARK="[i]"
WARNING_MARK="[!]"

log_info() {
    echo -e "${BLUE}${INFO_MARK} ${1}${NC}"
}

log_success() {
    echo -e "${GREEN}${CHECK_MARK} ${1}${NC}"
}

log_warning() {
    echo -e "${YELLOW}${WARNING_MARK} ${1}${NC}"
}

log_error() {
    echo -e "${RED}${CROSS_MARK} ${1}${NC}" >&2
}

handle_error() {
    log_error "Произошла ошибка в строке $1"
    exit 1
}

trap 'handle_error $LINENO' ERR

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "Этот скрипт должен быть запущен от имени root."
        exit 1
    fi
    log_info "Запуск с правами root"
}

check_os_version() {
    local os_name os_version

    log_info "Проверка совместимости ОС..."
    
    if [ -f /etc/os-release ]; then
        os_name=$(grep '^ID=' /etc/os-release | cut -d= -f2)
        os_version=$(grep '^VERSION_ID=' /etc/os-release | cut -d= -f2 | tr -d '"')
    else
        log_error "Неподдерживаемая ОС или невозможно определить версию ОС."
        exit 1
    fi

    if ! command -v bc &> /dev/null; then
        log_info "Установка пакета bc..."
        apt update -qq && apt install -y -qq bc
        if [ $? -ne 0 ]; then
            log_error "Не удалось установить пакет bc."
            exit 1
        fi
    fi

    if [[ "$os_name" == "ubuntu" && $(echo "$os_version >= 22" | bc) -eq 1 ]] ||
       [[ "$os_name" == "debian" && $(echo "$os_version >= 12" | bc) -eq 1 ]]; then
        log_success "Проверка ОС пройдена: $os_name $os_version"
    else
        log_error "Этот скрипт поддерживается только на Ubuntu 22+ или Debian 12+."
        exit 1
    fi
    
    log_info "Проверка процессора на поддержку AVX (требуется для MongoDB)..."
    if grep -q -m1 -o -E 'avx|avx2|avx512' /proc/cpuinfo; then
        log_success "Процессор поддерживает набор инструкций AVX."
    else
        log_error "Процессор не поддерживает требуемый набор инструкций AVX для MongoDB."
        log_info "Для систем без поддержки AVX вы можете использовать версию панели 'nodb' (без БД)."
        log_info "Для установки выполните следующую команду:"
        echo -e "${YELLOW}bash <(curl -sL https://raw.githubusercontent.com/Asgaroth-SG/AsgarothGate/nodb/install.sh)${NC}"
        log_error "Установка прервана."
        exit 1
    fi
}


install_mongodb() {
    log_info "Установка MongoDB..."
    
    if command -v mongod &> /dev/null; then
        log_success "MongoDB уже установлена"
        return 0
    fi
    
    curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
    
    local codename
    codename=$(lsb_release -cs)
    local repo_line=""

    case "$codename" in
        "noble" | "jammy")
            repo_line="deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu $codename/mongodb-org/8.0 multiverse"
            ;;
        "bookworm" | "trixie")
            repo_line="deb [ signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] http://repo.mongodb.org/apt/debian bookworm/mongodb-org/8.0 main"
            ;;
        *)
            log_error "Неподдерживаемое кодовое имя ОС для установки MongoDB: $codename"
            exit 1
            ;;
    esac

    echo "$repo_line" | tee /etc/apt/sources.list.d/mongodb-org-8.0.list > /dev/null
    
    apt update -qq
    apt install -y -qq mongodb-org
    
    systemctl enable mongod
    systemctl start mongod
    
    if systemctl is-active --quiet mongod; then
        log_success "MongoDB успешно установлена и запущена"
    else
        log_error "Ошибка установки MongoDB или сервис не запущен"
        exit 1
    fi
}


install_packages() {
    local REQUIRED_PACKAGES=("jq" "curl" "pwgen" "python3" "python3-pip" "python3-venv" "bc" "zip" "unzip" "lsof" "gnupg" "lsb-release")
    local MISSING_PACKAGES=()
    
    log_info "Проверка необходимых пакетов..."
    
    for package in "${REQUIRED_PACKAGES[@]}"; do
        if ! command -v "$package" &> /dev/null && ! dpkg -l | grep -q "^ii.*$package "; then
            MISSING_PACKAGES+=("$package")
        else
            log_success "Пакет $package уже установлен"
        fi
    done

    if [ ${#MISSING_PACKAGES[@]} -ne 0 ]; then
        log_info "Установка недостающих пакетов: ${MISSING_PACKAGES[*]}"
        apt update -qq || { log_error "Не удалось обновить репозитории apt"; exit 1; }
        apt upgrade -y -qq || { log_warning "Не удалось обновить пакеты, продолжаем..."; }
        
        for package in "${MISSING_PACKAGES[@]}"; do
            log_info "Установка $package..."
            if apt install -y -qq "$package"; then
                log_success "Установлен $package"
            else
                log_error "Не удалось установить $package"
                exit 1
            fi
        done
    else
        log_success "Все необходимые пакеты уже установлены."
    fi
    
    install_mongodb
}

download_and_extract_release() {
    log_info "Скачивание и распаковка панели Asgaroth Gate..."

    if [ -d "/etc/hysteria" ]; then
        log_warning "Директория /etc/hysteria уже существует."
        read -p "Вы хотите удалить её и установить заново? (y/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf /etc/hysteria
        else
            log_info "Пропуск скачивания. Используется существующая директория."
            return 0
        fi
    fi

    local arch
    case $(uname -m) in
        x86_64) arch="amd64" ;;
        aarch64) arch="arm64" ;;
        *)
            log_error "Неподдерживаемая архитектура: $(uname -m)"
            exit 1
            ;;
    esac
    log_info "Обнаружена архитектура: $arch"

    local zip_name="AsgarothGate-${arch}.zip"
    local download_url="https://github.com/Asgaroth-SG/AsgarothGate/releases/latest/download/${zip_name}"
    local temp_zip="/tmp/${zip_name}"

    log_info "Скачивание с ${download_url}..."
    if curl -sL -o "$temp_zip" "$download_url"; then
        log_success "Скачивание завершено."
    else
        log_error "Не удалось скачать релиз. Пожалуйста, проверьте URL и ваше соединение."
        exit 1
    fi

    log_info "Распаковка в /etc/hysteria..."
    mkdir -p /etc/hysteria
    if unzip -q "$temp_zip" -d /etc/hysteria; then
        log_success "Распаковка прошла успешно."
    else
        log_error "Не удалось распаковать архив."
        exit 1
    fi
    
    rm "$temp_zip"
    log_info "Временный файл удален."
    
    local auth_binary="/etc/hysteria/core/scripts/auth/user_auth"
    if [ -f "$auth_binary" ]; then
        chmod +x "$auth_binary"
        log_success "Установлены права на выполнение для бинарного файла auth."
    else
        log_warning "Бинарный файл auth не найден в $auth_binary. Установка может быть неполной."
    fi
}

setup_python_env() {
    log_info "Настройка виртуального окружения Python..."
    
    cd /etc/hysteria || { log_error "Не удалось перейти в директорию /etc/hysteria"; exit 1; }
    
    if python3 -m venv hysteria2_venv &> /dev/null; then
        log_success "Виртуальное окружение Python создано"
    else
        log_error "Не удалось создать виртуальное окружение Python"
        exit 1
    fi
    
    source /etc/hysteria/hysteria2_venv/bin/activate || { log_error "Не удалось активировать виртуальное окружение"; exit 1; }
    
    log_info "Установка зависимостей Python..."
    if pip install -r requirements.txt &> /dev/null; then
        log_success "Зависимости Python установлены"
    else
        log_error "Не удалось установить зависимости Python"
        exit 1
    fi
}

add_alias() {
    log_info "Добавление алиаса 'hys2' в .bashrc..."
    
    if ! grep -q "alias hys2='source /etc/hysteria/hysteria2_venv/bin/activate && /etc/hysteria/menu.sh'" ~/.bashrc; then
        echo "alias hys2='source /etc/hysteria/hysteria2_venv/bin/activate && /etc/hysteria/menu.sh'" >> ~/.bashrc
        log_success "Алиас 'hys2' добавлен в .bashrc"
    else
        log_info "Алиас 'hys2' уже существует в .bashrc"
    fi
}

run_menu() {
    log_info "Подготовка к запуску меню..."
    
    cd /etc/hysteria || { log_error "Не удалось перейти в директорию /etc/hysteria"; exit 1; }
    chmod +x menu.sh || { log_error "Не удалось сделать menu.sh исполняемым"; exit 1; }
    
    log_info "Запуск меню..."
    echo -e "\n${BOLD}${GREEN}======== Запуск меню Asgaroth Gate ========${NC}\n"
    ./menu.sh
}

main() {
    echo -e "\n${BOLD}${BLUE}======== Скрипт установки Asgaroth Gate ========${NC}\n"
    
    check_root
    check_os_version
    install_packages
    download_and_extract_release
    setup_python_env
    add_alias
    
    source ~/.bashrc &> /dev/null || true
    
    echo -e "\n${YELLOW}Запуск Asgaroth Gate через 3 секунды...${NC}"
    sleep 3
    
    run_menu
}

main