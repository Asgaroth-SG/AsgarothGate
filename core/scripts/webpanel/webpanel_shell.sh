#!/bin/bash
source /etc/hysteria/core/scripts/utils.sh
define_colors

CADDY_CONFIG_FILE="/etc/hysteria/core/scripts/webpanel/Caddyfile"
WEBPANEL_ENV_FILE="/etc/hysteria/core/scripts/webpanel/.env"

install_dependencies() {
    sudo apt update -y > /dev/null 2>&1

    sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl > /dev/null 2>&1
    apt install libnss3-tools -y > /dev/null 2>&1

    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg > /dev/null 2>&1
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null 2>&1
    chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    chmod o+r /etc/apt/sources.list.d/caddy-stable.list

    sudo apt update -y > /dev/null 2>&1
    sudo apt install -y caddy
    if [ $? -ne 0 ]; then
        echo -e "${red}Ошибка: Не удалось установить Caddy. ${NC}"
        exit 1
    fi

    systemctl stop caddy > /dev/null 2>&1
    systemctl disable caddy > /dev/null 2>&1

    echo -e "${green}Caddy успешно установлен. ${NC}"
}

update_env_file() {
    local domain=$1
    local port=$2
    local admin_username=$3
    local admin_password=$4
    local admin_password_hash=$(echo -n "$admin_password" | sha256sum | cut -d' ' -f1) # хешируем пароль
    local expiration_minutes=$5
    local debug=$6
    local decoy_path=$7

    local api_token=$(openssl rand -hex 32) 
    local root_path=$(openssl rand -hex 16)

    cat <<EOL > /etc/hysteria/core/scripts/webpanel/.env
DEBUG=$debug
DOMAIN=$domain
PORT=$port
ROOT_PATH=$root_path
API_TOKEN=$api_token
ADMIN_USERNAME=$admin_username
ADMIN_PASSWORD=$admin_password_hash
EXPIRATION_MINUTES=$expiration_minutes
EOL

    if [ -n "$decoy_path" ] && [ "$decoy_path" != "None" ]; then
        echo "DECOY_PATH=$decoy_path" >> /etc/hysteria/core/scripts/webpanel/.env
    fi
}

update_caddy_file() {
    source /etc/hysteria/core/scripts/webpanel/.env
    
    if [ -z "$DOMAIN" ] || [ -z "$ROOT_PATH" ] || [ -z "$PORT" ]; then
        echo -e "${red}Ошибка: Отсутствует одна или несколько переменных окружения.${NC}"
        return 1
    fi

    if [ -n "$DECOY_PATH" ] && [ "$DECOY_PATH" != "None" ] && [ "$PORT" -eq 443 ]; then
        cat <<EOL > "$CADDY_CONFIG_FILE"
{
    admin off
    auto_https disable_redirects
}

$DOMAIN:$PORT {
    route /$ROOT_PATH/* {

        reverse_proxy http://127.0.0.1:28260
    }
    
    @otherPaths {
        not path /$ROOT_PATH/*
    }
    
    handle @otherPaths {
        root * $DECOY_PATH
        file_server
    }
}
EOL
    else
        cat <<EOL > "$CADDY_CONFIG_FILE"
# Global configuration (Глобальная конфигурация)
{
    admin off
    auto_https disable_redirects
}

# Listen for incoming requests on the specified domain and port (Прослушивание входящих запросов)
$DOMAIN:$PORT {
    route /$ROOT_PATH/* {
        reverse_proxy http://127.0.0.1:28260
    }
    
    @blocked {
        not path /$ROOT_PATH/*
    }
    
    abort @blocked
}
EOL

        if [ -n "$DECOY_PATH" ] && [ "$DECOY_PATH" != "None" ] && [ "$PORT" -ne 443 ]; then
            cat <<EOL >> "$CADDY_CONFIG_FILE"

# Decoy site on port 443 (Сайт-маскировка на порту 443)
$DOMAIN:443 {
    root * $DECOY_PATH
    file_server
}
EOL
        fi
    fi
}

create_webpanel_service_file() {
    cat <<EOL > /etc/systemd/system/hysteria-webpanel.service
[Unit]
Description=Hysteria Веб-панель
After=network.target

[Service]
WorkingDirectory=/etc/hysteria/core/scripts/webpanel
EnvironmentFile=/etc/hysteria/core/scripts/webpanel/.env
ExecStart=/bin/bash -c 'source /etc/hysteria/hysteria2_venv/bin/activate && /etc/hysteria/hysteria2_venv/bin/python /etc/hysteria/core/scripts/webpanel/app.py'
#Restart=always
User=root
Group=root

[Install]
WantedBy=multi-user.target
EOL
}

create_caddy_service_file() {
    cat <<EOL > /etc/systemd/system/hysteria-caddy.service
[Unit]
Description=Hysteria Caddy
After=network.target

[Service]
WorkingDirectory=/etc/caddy
ExecStart=/usr/bin/caddy run --environ --config $CADDY_CONFIG_FILE
ExecReload=/usr/bin/caddy reload --config $CADDY_CONFIG_FILE --force
TimeoutStopSec=5s
LimitNOFILE=1048576
PrivateTmp=true
User=root
Group=root

[Install]
WantedBy=multi-user.target
EOL
}

start_service() {
    local domain=$1
    local port=$2
    local admin_username=$3
    local admin_password=$4
    local expiration_minutes=$5
    local debug=$6
    local decoy_path=$7 

    install_dependencies

    update_env_file "$domain" "$port" "$admin_username" "$admin_password" "$expiration_minutes" "$debug" "$decoy_path"
    if [ $? -ne 0 ]; then
        echo -e "${red}Ошибка: Не удалось обновить файл окружения.${NC}"
        return 1
    fi

    create_webpanel_service_file
    if [ $? -ne 0 ]; then
        echo -e "${red}Ошибка: Не удалось создать файл службы webpanel.${NC}"
        return 1
    fi

    systemctl daemon-reload
    systemctl enable hysteria-webpanel.service > /dev/null 2>&1
    systemctl start hysteria-webpanel.service > /dev/null 2>&1

    if systemctl is-active --quiet hysteria-webpanel.service; then
        echo -e "${green}Настройка веб-панели Hysteria завершена. Веб-панель запущена локально по адресу: http://127.0.0.1:28260/${NC}"
    else
        echo -e "${red}Ошибка: Не удалось запустить службу веб-панели Hysteria.${NC}"
        return 1
    fi

    update_caddy_file
    if [ $? -ne 0 ]; then
        echo -e "${red}Ошибка: Не удалось обновить Caddyfile.${NC}"
        return 1
    fi

    create_caddy_service_file
    if [ $? -ne 0 ]; then
        echo -e "${red}Ошибка: Не удалось создать файл службы Caddy.${NC}"
        return 1
    fi

    systemctl daemon-reload
    systemctl enable hysteria-caddy.service 
    systemctl start hysteria-caddy.service
    if [ $? -ne 0 ]; then
        echo -e "${red}Ошибка: Не удалось перезапустить Caddy.${NC}"
        return 1
    fi

    if systemctl is-active --quiet hysteria-webpanel.service; then
        source /etc/hysteria/core/scripts/webpanel/.env
        local webpanel_url="http://$domain:$port/$ROOT_PATH/"
        echo -e "${green}Веб-панель Hysteria запущена. Сервис доступен по адресу: $webpanel_url ${NC}"
        
        if [ -n "$DECOY_PATH" ] && [ "$DECOY_PATH" != "None" ]; then
            if [ "$port" -eq 443 ]; then
                echo -e "${green}Сайт-маскировка настроен на том же порту (443) и будет обрабатывать пути, не относящиеся к веб-панели.${NC}"
            else
                echo -e "${green}Сайт-маскировка настроен на порту 443 по адресу: http://$domain:443/${NC}"
            fi
        fi
    else
        echo -e "${red}Ошибка: Веб-панель Hysteria не запустилась после перезапуска Caddy.${NC}"
    fi
}

setup_decoy_site() {
    local domain=$1
    local decoy_path=$2
    
    if [ -z "$domain" ] || [ -z "$decoy_path" ]; then
        echo -e "${red}Использование: $0 decoy <DOMAIN> <PATH_TO_DECOY_SITE>${NC}"
        return 1
    fi
    
    if [ ! -d "$decoy_path" ]; then
        echo -e "${yellow}Внимание: Путь к сайту-маскировке не существует. Создание директории...${NC}"
        mkdir -p "$decoy_path"
        echo "<html><body><h1>Сайт на реконструкции (Website Under Construction)</h1></body></html>" > "$decoy_path/index.html"
    fi
    
    if [ -f "/etc/hysteria/core/scripts/webpanel/.env" ]; then
        source /etc/hysteria/core/scripts/webpanel/.env
        sed -i "/DECOY_PATH=/d" /etc/hysteria/core/scripts/webpanel/.env
        echo "DECOY_PATH=$decoy_path" >> /etc/hysteria/core/scripts/webpanel/.env
        
        update_caddy_file
        
        systemctl restart hysteria-caddy.service
        
        echo -e "${green}Сайт-маскировка успешно настроен для $domain${NC}"
        if [ "$PORT" -eq 443 ]; then
            echo -e "${green}Сайт-маскировка доступен по путям, не относящимся к веб-панели, на: https://$domain:443/${NC}"
        else
            echo -e "${green}Сайт-маскировка доступен по адресу: https://$domain:443/${NC}"
        fi
    else
        echo -e "${red}Ошибка: Веб-панель еще не настроена. Пожалуйста, сначала запустите веб-панель.${NC}"
        return 1
    fi
}

stop_decoy_site() {
    if [ ! -f "/etc/hysteria/core/scripts/webpanel/.env" ]; then
        echo -e "${red}Ошибка: Веб-панель не настроена.${NC}"
        return 1
    fi
    
    source /etc/hysteria/core/scripts/webpanel/.env
    
    if [ -z "$DECOY_PATH" ] || [ "$DECOY_PATH" = "None" ]; then
        echo -e "${yellow}Сайт-маскировка в данный момент не настроен.${NC}"
        return 0
    fi
    
    local was_separate_port=false
    if [ "$PORT" -ne 443 ]; then
        was_separate_port=true
    fi
    
    sed -i "/DECOY_PATH=/d" /etc/hysteria/core/scripts/webpanel/.env
    
    cat <<EOL > "$CADDY_CONFIG_FILE"
# Global configuration
{
    admin off
    auto_https disable_redirects
}

# Listen for incoming requests on the specified domain and port
$DOMAIN:$PORT {
    route /$ROOT_PATH/* {
        reverse_proxy http://127.0.0.1:28260
    }
    
    @blocked {
        not path /$ROOT_PATH/*
    }
    
    abort @blocked
}
EOL
    
    systemctl restart hysteria-caddy.service
    
    echo -e "${green}Сайт-маскировка остановлен и удален из конфигурации.${NC}"
    if [ "$was_separate_port" = true ]; then
        echo -e "${green}Порт 443 больше не обслуживается Caddy.${NC}"
    else
        echo -e "${green}Пути на порту 443, не относящиеся к веб-панели, теперь будут возвращать ошибку соединения вместо показа сайта-маскировки.${NC}"
    fi
}

reset_credentials() {
    local new_username_val=""
    local new_password_val=""
    local changes_made=false

    if [ ! -f "$WEBPANEL_ENV_FILE" ]; then
        echo -e "${red}Ошибка: Файл .env веб-панели не найден. Веб-панель настроена?${NC}"
        exit 1
    fi

    OPTIND=1 
    while getopts ":u:p:" opt; do
        case $opt in
            u) new_username_val="$OPTARG" ;;
            p) new_password_val="$OPTARG" ;;
            \?) echo -e "${red}Неверная опция: -$OPTARG${NC}" >&2; exit 1 ;;
            :) echo -e "${red}Опция -$OPTARG требует аргумента.${NC}" >&2; exit 1 ;;
        esac
    done

    if [ -z "$new_username_val" ] && [ -z "$new_password_val" ]; then
        echo -e "${red}Ошибка: Должна быть указана хотя бы одна опция (-u <новое_имя> или -p <новый_пароль>).${NC}"
        echo -e "${yellow}Использование: $0 resetcreds [-u new_username] [-p new_password]${NC}"
        exit 1
    fi

    if [ -n "$new_username_val" ]; then
        echo "Обновление имени пользователя на: $new_username_val"
        if sudo sed -i "s|^ADMIN_USERNAME=.*|ADMIN_USERNAME=$new_username_val|" "$WEBPANEL_ENV_FILE"; then
            changes_made=true
        else
            echo -e "${red}Не удалось обновить имя пользователя в $WEBPANEL_ENV_FILE${NC}"
            exit 1
        fi
    fi

    if [ -n "$new_password_val" ]; then
        echo "Обновление пароля..."
        local new_password_hash=$(echo -n "$new_password_val" | sha256sum | cut -d' ' -f1)
        if sudo sed -i "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$new_password_hash|" "$WEBPANEL_ENV_FILE"; then
            changes_made=true
        else
             echo -e "${red}Не удалось обновить пароль в $WEBPANEL_ENV_FILE${NC}"
             exit 1
        fi
    fi

    if [ "$changes_made" = true ]; then
        echo "Перезапуск службы веб-панели для применения изменений..."
        if systemctl restart hysteria-webpanel.service; then
            echo -e "${green}Учетные данные веб-панели успешно обновлены.${NC}"
        else
            echo -e "${red}Не удалось перезапустить сервис hysteria-webpanel. Пожалуйста, перезапустите его вручную.${NC}"
        fi
    else
        echo -e "${yellow}Изменения не были указаны.${NC}"
    fi
}

change_expiration() {
    local new_expiration=$1

    if [ -z "$new_expiration" ]; then
        echo -e "${red}Использование: $0 changeexp <МИНУТЫ_ДО_ИСТЕЧЕНИЯ>${NC}"
        exit 1
    fi

    if [ ! -f "$WEBPANEL_ENV_FILE" ]; then
        echo -e "${red}Ошибка: Файл .env веб-панели не найден. Веб-панель настроена?${NC}"
        exit 1
    fi

    echo "Обновление времени истечения сессии до: $new_expiration минут"
    if sudo sed -i "s|^EXPIRATION_MINUTES=.*|EXPIRATION_MINUTES=$new_expiration|" "$WEBPANEL_ENV_FILE"; then
        echo "Перезапуск службы веб-панели для применения изменений..."
        if systemctl restart hysteria-webpanel.service; then
            echo -e "${green}Время истечения сессии веб-панели успешно обновлено.${NC}"
        else
            echo -e "${red}Не удалось перезапустить сервис hysteria-webpanel. Пожалуйста, перезапустите его вручную.${NC}"
        fi
    else
        echo -e "${red}Не удалось обновить время истечения в $WEBPANEL_ENV_FILE${NC}"
        exit 1
    fi
}

change_root_path() {
    local new_root_path=$1

    if [ ! -f "$WEBPANEL_ENV_FILE" ]; then
        echo -e "${red}Ошибка: Файл .env веб-панели не найден. Веб-панель настроена?${NC}"
        exit 1
    fi

    if [ -z "$new_root_path" ]; then
        echo "Генерация нового случайного корневого пути..."
        new_root_path=$(openssl rand -hex 16)
    fi

    echo "Обновление корневого пути на: $new_root_path"
    if sudo sed -i "s|^ROOT_PATH=.*|ROOT_PATH=$new_root_path|" "$WEBPANEL_ENV_FILE"; then
        echo "Обновление конфигурации Caddy..."
        update_caddy_file
        if [ $? -ne 0 ]; then
            echo -e "${red}Ошибка: Не удалось обновить Caddyfile.${NC}"
            exit 1
        fi

        echo "Перезапуск сервисов для применения изменений..."
        if systemctl restart hysteria-webpanel.service && systemctl restart hysteria-caddy.service; then
            echo -e "${green}Корневой путь веб-панели успешно обновлен.${NC}"
            echo -n "Новый URL: "
            show_webpanel_url
        else
            echo -e "${red}Не удалось перезапустить сервисы. Пожалуйста, перезапустите их вручную.${NC}"
        fi
    else
        echo -e "${red}Не удалось обновить корневой путь в $WEBPANEL_ENV_FILE${NC}"
        exit 1
    fi
}

change_port_domain() {
    local new_domain=""
    local new_port=""
    local changes_made=false

    if [ ! -f "$WEBPANEL_ENV_FILE" ]; then
        echo -e "${red}Ошибка: Файл .env веб-панели не найден. Веб-панель настроена?${NC}"
        exit 1
    fi

    OPTIND=1
    while getopts ":d:p:" opt; do
        case $opt in
            d) new_domain="$OPTARG" ;;
            p) new_port="$OPTARG" ;;
            \?) echo -e "${red}Неверная опция: -$OPTARG${NC}" >&2; exit 1 ;;
            :) echo -e "${red}Опция -$OPTARG требует аргумента.${NC}" >&2; exit 1 ;;
        esac
    done

    if [ -z "$new_domain" ] && [ -z "$new_port" ]; then
        echo -e "${red}Ошибка: Должна быть указана хотя бы одна опция (-d <новый_домен> или -p <новый_порт>).${NC}"
        echo -e "${yellow}Использование: $0 changedomain [-d new_domain] [-p new_port]${NC}"
        exit 1
    fi

    if [ -n "$new_domain" ]; then
        echo "Обновление домена на: $new_domain"
        if sudo sed -i "s|^DOMAIN=.*|DOMAIN=$new_domain|" "$WEBPANEL_ENV_FILE"; then
            changes_made=true
        else
            echo -e "${red}Не удалось обновить домен в $WEBPANEL_ENV_FILE${NC}"
            exit 1
        fi
    fi

    if [ -n "$new_port" ]; then
        echo "Обновление порта на: $new_port"
        if sudo sed -i "s|^PORT=.*|PORT=$new_port|" "$WEBPANEL_ENV_FILE"; then
            changes_made=true
        else
            echo -e "${red}Не удалось обновить порт в $WEBPANEL_ENV_FILE${NC}"
            exit 1
        fi
    fi

    if [ "$changes_made" = true ]; then
        echo "Обновление конфигурации Caddy..."
        update_caddy_file
        if [ $? -ne 0 ]; then
            echo -e "${red}Ошибка: Не удалось обновить Caddyfile.${NC}"
            exit 1
        fi

        echo "Перезапуск службы Caddy для применения изменений..."
        if systemctl restart hysteria-caddy.service; then
            echo -e "${green}Домен/порт веб-панели успешно обновлены.${NC}"
            echo -n "Новый URL: "
            show_webpanel_url
        else
            echo -e "${red}Не удалось перезапустить Caddy. Пожалуйста, перезапустите его вручную.${NC}"
        fi
    else
        echo -e "${yellow}Изменения не были внесены.${NC}"
    fi
}

show_webpanel_url() {
    source /etc/hysteria/core/scripts/webpanel/.env
    local webpanel_url="https://$DOMAIN:$PORT/$ROOT_PATH/"
    echo "$webpanel_url"
}

show_webpanel_api_token() {
    source /etc/hysteria/core/scripts/webpanel/.env
    echo "$API_TOKEN"
}

stop_service() {
    echo "Остановка Caddy..."
    systemctl disable hysteria-caddy.service > /dev/null 2>&1
    systemctl stop hysteria-caddy.service > /dev/null 2>&1
    echo "Caddy остановлен."
    
    echo "Остановка веб-панели Hysteria..."
    systemctl disable hysteria-webpanel.service > /dev/null 2>&1
    systemctl stop hysteria-webpanel.service > /dev/null 2>&1
    echo "Веб-панель Hysteria остановлена."

    systemctl daemon-reload
    rm -f /etc/hysteria/core/scripts/webpanel/.env
    rm -f "$CADDY_CONFIG_FILE"
}

case "$1" in
    start)
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo -e "${red}Использование: $0 start <DOMAIN> <PORT> [ADMIN_USERNAME] [ADMIN_PASSWORD] [EXPIRATION_MINUTES] [DEBUG] [DECOY_PATH]${NC}"
            exit 1
        fi
        start_service "$2" "$3" "$4" "$5" "$6" "$7" "$8"
        ;;
    stop)
        stop_service
        ;;
    decoy)
        if [ -z "$2" ] || [ -z "$3" ]; then
            echo -e "${red}Использование: $0 decoy <DOMAIN> <PATH_TO_DECOY_SITE>${NC}"
            exit 1
        fi
        setup_decoy_site "$2" "$3"
        ;;
    stopdecoy)
        stop_decoy_site
        ;;
    resetcreds)
        shift 
        reset_credentials "$@"
        ;;
    changeexp)
        change_expiration "$2"
        ;;
    changeroot)
        change_root_path "$2"
        ;;
    changedomain)
        shift
        change_port_domain "$@"
        ;;
    url)
        show_webpanel_url
        ;;
    api-token)
        show_webpanel_api_token
        ;;
    *)
        echo -e "${red}Использование: $0 {start|stop|decoy|stopdecoy|resetcreds|changeexp|changeroot|changedomain|url|api-token} [опции]${NC}"
        echo -e "${yellow}start <DOMAIN> <PORT> [ADMIN_USERNAME] [ADMIN_PASSWORD] [EXPIRATION_MINUTES] [DEBUG] [DECOY_PATH]${NC}"
        echo -e "${yellow}stop${NC}"
        echo -e "${yellow}decoy <DOMAIN> <PATH_TO_DECOY_SITE>${NC}"
        echo -e "${yellow}stopdecoy${NC}"
        echo -e "${yellow}resetcreds [-u new_username] [-p new_password]${NC}"
        echo -e "${yellow}changeexp <NEW_EXPIRATION_MINUTES>${NC}"
        echo -e "${yellow}changeroot [NEW_ROOT_PATH] # Генерирует случайный, если не указан${NC}"
        echo -e "${yellow}changedomain [-d new_domain] [-p new_port]${NC}"
        echo -e "${yellow}url${NC}"
        echo -e "${yellow}api-token${NC}"
        exit 1
        ;;
esac