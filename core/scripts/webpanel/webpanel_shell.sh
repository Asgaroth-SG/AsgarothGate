#!/bin/bash
source /etc/hysteria/core/scripts/utils.sh
define_colors

CADDY_CONFIG_FILE="/etc/hysteria/core/scripts/webpanel/Caddyfile"
WEBPANEL_ENV_FILE="/etc/hysteria/core/scripts/webpanel/.env"
NORMALSUB_ENV_FILE="/etc/hysteria/core/scripts/normalsub/.env"

DEFAULT_XHTTP_ENABLED="true"  
DEFAULT_XHTTP_PATH="xhttp/9f3a1cfba29df6b437aed633b158d0e9" 
DEFAULT_XHTTP_UPSTREAM="127.0.0.1:20000"

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
    local admin_password_hash
    admin_password_hash=$(echo -n "$admin_password" | sha256sum | cut -d' ' -f1)
    local expiration_minutes=$5
    local debug=$6
    local decoy_path=$7

    local xhttp_path=${8:-""}
    local xhttp_upstream=${9:-""}

    local xhttp_enabled="false"
    if [ "${DEFAULT_XHTTP_ENABLED}" = "true" ]; then
        xhttp_enabled="true"
    fi

    if [ "$xhttp_enabled" = "true" ]; then
        xhttp_path="${xhttp_path:-$DEFAULT_XHTTP_PATH}"
        xhttp_upstream="${xhttp_upstream:-$DEFAULT_XHTTP_UPSTREAM}"
    fi

    local api_token
    api_token=$(openssl rand -hex 32)
    local root_path
    root_path=$(openssl rand -hex 16)

    cat <<EOL > "$WEBPANEL_ENV_FILE"
DEBUG=$debug
DOMAIN=$domain
PORT=$port
ROOT_PATH=$root_path
API_TOKEN=$api_token
ADMIN_USERNAME=$admin_username
ADMIN_PASSWORD=$admin_password_hash
EXPIRATION_MINUTES=$expiration_minutes
XHTTP_ENABLED=$xhttp_enabled
EOL

    if [ -n "$decoy_path" ] && [ "$decoy_path" != "None" ]; then
        echo "DECOY_PATH=$decoy_path" >> "$WEBPANEL_ENV_FILE"
    fi

    if [ "$xhttp_enabled" = "true" ]; then
        echo "XHTTP_PATH=$xhttp_path" >> "$WEBPANEL_ENV_FILE"
        echo "XHTTP_UPSTREAM=$xhttp_upstream" >> "$WEBPANEL_ENV_FILE"
    fi
}

update_caddy_file() {
    source "$WEBPANEL_ENV_FILE"

    local XHTTP_ENABLED="${XHTTP_ENABLED:-}"
    local XHTTP_PATH="${XHTTP_PATH:-}"
    local XHTTP_UPSTREAM="${XHTTP_UPSTREAM:-}"

    if [ -z "$XHTTP_ENABLED" ]; then
        if [ "${DEFAULT_XHTTP_ENABLED}" = "true" ]; then
            XHTTP_ENABLED="true"
        else
            XHTTP_ENABLED="false"
        fi
    fi

    if [ "$XHTTP_ENABLED" = "true" ]; then
        XHTTP_PATH="${XHTTP_PATH:-$DEFAULT_XHTTP_PATH}"
        XHTTP_UPSTREAM="${XHTTP_UPSTREAM:-$DEFAULT_XHTTP_UPSTREAM}"
    fi

    local SUB_PATH=""
    local SUB_PORT="28261"
    local SUB_DOMAIN=""
    local SUB_EXT_PORT=""

    if [ -f "$NORMALSUB_ENV_FILE" ]; then
        local sub_path_val
        sub_path_val=$(grep "^SUBPATH=" "$NORMALSUB_ENV_FILE" | cut -d'=' -f2)
        local sub_port_val
        sub_port_val=$(grep "^AIOHTTP_LISTEN_PORT=" "$NORMALSUB_ENV_FILE" | cut -d'=' -f2)
        local sub_dom_val
        sub_dom_val=$(grep "^HYSTERIA_DOMAIN=" "$NORMALSUB_ENV_FILE" | cut -d'=' -f2)
        local sub_ext_p_val
        sub_ext_p_val=$(grep "^HYSTERIA_PORT=" "$NORMALSUB_ENV_FILE" | cut -d'=' -f2)

        [ -n "$sub_path_val" ] && SUB_PATH="$sub_path_val"
        [ -n "$sub_port_val" ] && SUB_PORT="$sub_port_val"
        [ -n "$sub_dom_val" ] && SUB_DOMAIN="$sub_dom_val"
        [ -n "$sub_ext_p_val" ] && SUB_EXT_PORT="$sub_ext_p_val"
    fi

    if [ -z "$DOMAIN" ] || [ -z "$ROOT_PATH" ] || [ -z "$PORT" ]; then
        echo -e "${red}Ошибка: Отсутствует одна или несколько переменных окружения.${NC}"
        return 1
    fi

    cat <<EOL > "$CADDY_CONFIG_FILE"
{
    admin off
    auto_https disable_redirects
    # Глобально отключаем HTTP/3 (UDP), чтобы не конфликтовать с Hysteria
    servers {
        protocols h1 h2
    }
}
EOL

    cat <<EOL >> "$CADDY_CONFIG_FILE"

$DOMAIN:$PORT {
    # Веб-панель
    route /$ROOT_PATH/* {
        reverse_proxy http://127.0.0.1:28260
    }
EOL

    if [ "$XHTTP_ENABLED" = "true" ] && [ -n "$XHTTP_PATH" ] && [ "$XHTTP_PATH" != "None" ]; then
        cat <<EOL >> "$CADDY_CONFIG_FILE"

    # 3X-UI XHTTP VLESS
    route /$XHTTP_PATH/* {
        reverse_proxy $XHTTP_UPSTREAM
    }
EOL
    fi

    local MERGE_SUBS=false
    if [ -n "$SUB_PATH" ] && [ "$SUB_DOMAIN" == "$DOMAIN" ] && [ "$SUB_EXT_PORT" == "$PORT" ]; then
        MERGE_SUBS=true
        cat <<EOL >> "$CADDY_CONFIG_FILE"

    # Подписки
    route /$SUB_PATH/* {
        reverse_proxy http://127.0.0.1:$SUB_PORT {
            header_up X-Real-IP {remote_host}
            header_up X-Forwarded-For {remote_host}
            header_up X-Forwarded-Port {server_port}
            header_up X-Forwarded-Proto {scheme}
        }
    }
EOL
    fi

    cat <<EOL >> "$CADDY_CONFIG_FILE"

    @otherPaths {
        not path /$ROOT_PATH/*
EOL

    if [ "$XHTTP_ENABLED" = "true" ] && [ -n "$XHTTP_PATH" ] && [ "$XHTTP_PATH" != "None" ]; then
        echo "        not path /$XHTTP_PATH/*" >> "$CADDY_CONFIG_FILE"
    fi

    if [ "$MERGE_SUBS" = true ]; then
        echo "        not path /$SUB_PATH/*" >> "$CADDY_CONFIG_FILE"
    fi

    cat <<EOL >> "$CADDY_CONFIG_FILE"
    }

    handle @otherPaths {
EOL

    if [ -n "$DECOY_PATH" ] && [ "$DECOY_PATH" != "None" ]; then
        echo "        root * $DECOY_PATH" >> "$CADDY_CONFIG_FILE"
        echo "        file_server" >> "$CADDY_CONFIG_FILE"
    else
        echo "        abort" >> "$CADDY_CONFIG_FILE"
    fi

    cat <<EOL >> "$CADDY_CONFIG_FILE"
    }
}
EOL

    if [ -n "$SUB_PATH" ] && ([ "$SUB_DOMAIN" != "$DOMAIN" ] || [ "$SUB_EXT_PORT" != "$PORT" ]); then
        cat <<EOL >> "$CADDY_CONFIG_FILE"

$SUB_DOMAIN:$SUB_EXT_PORT {
    route /$SUB_PATH/* {
        reverse_proxy http://127.0.0.1:$SUB_PORT {
            header_up X-Real-IP {remote_host}
            header_up X-Forwarded-For {remote_host}
            header_up X-Forwarded-Port {server_port}
            header_up X-Forwarded-Proto {scheme}
        }
    }

    # Блокируем всё остальное на домене подписок
    @blocked {
        not path /$SUB_PATH/*
    }
    abort @blocked
}
EOL
    fi

    local SUBS_ON_443=false
    if [ "$SUB_EXT_PORT" == "443" ] && [ -n "$SUB_PATH" ]; then
        SUBS_ON_443=true
    fi

    if [ -n "$DECOY_PATH" ] && [ "$DECOY_PATH" != "None" ] && [ "$PORT" -ne 443 ] && [ "$SUBS_ON_443" = false ]; then
        cat <<EOL >> "$CADDY_CONFIG_FILE"

$DOMAIN:443 {
    root * $DECOY_PATH
    file_server
}
EOL
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
    local xhttp_path=${8:-""}
    local xhttp_upstream=${9:-""}

    install_dependencies

    update_env_file "$domain" "$port" "$admin_username" "$admin_password" "$expiration_minutes" "$debug" "$decoy_path" "$xhttp_path" "$xhttp_upstream"
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
        echo -e "${red}Ошибка: Не удалось запустить Caddy.${NC}"
        return 1
    fi

    if systemctl is-active --quiet hysteria-webpanel.service; then
        source "$WEBPANEL_ENV_FILE"
        local webpanel_url="https://$domain:$port/$ROOT_PATH/"
        echo -e "${green}Веб-панель Hysteria запущена. Сервис доступен по адресу: $webpanel_url ${NC}"

        if [ "${XHTTP_ENABLED:-false}" = "true" ]; then
            echo -e "${green}XHTTP (3X-UI) включён: /${XHTTP_PATH:-$DEFAULT_XHTTP_PATH}/* -> ${XHTTP_UPSTREAM:-$DEFAULT_XHTTP_UPSTREAM}${NC}"
        else
            echo -e "${yellow}XHTTP (3X-UI) выключен.${NC}"
        fi

        if [ -n "${DECOY_PATH:-}" ] && [ "${DECOY_PATH:-}" != "None" ]; then
            if [ "$port" -eq 443 ]; then
                echo -e "${green}Сайт-маскировка настроен на том же порту (443) и будет обрабатывать пути, не относящиеся к веб-панели.${NC}"
            else
                echo -e "${green}Сайт-маскировка настроен на порту 443 по адресу: https://$domain:443/${NC}"
            fi
        fi
    else
        echo -e "${red}Ошибка: Веб-панель Hysteria не запустилась после запуска Caddy.${NC}"
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

    if [ -f "$WEBPANEL_ENV_FILE" ]; then
        source "$WEBPANEL_ENV_FILE"
        sed -i "/DECOY_PATH=/d" "$WEBPANEL_ENV_FILE"
        echo "DECOY_PATH=$decoy_path" >> "$WEBPANEL_ENV_FILE"

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
    if [ ! -f "$WEBPANEL_ENV_FILE" ]; then
        echo -e "${red}Ошибка: Веб-панель не настроена.${NC}"
        return 1
    fi

    source "$WEBPANEL_ENV_FILE"

    if [ -z "${DECOY_PATH:-}" ] || [ "${DECOY_PATH:-}" = "None" ]; then
        echo -e "${yellow}Сайт-маскировка в данный момент не настроен.${NC}"
        return 0
    fi

    local was_separate_port=false
    if [ "$PORT" -ne 443 ]; then
        was_separate_port=true
    fi

    sed -i "/DECOY_PATH=/d" "$WEBPANEL_ENV_FILE"

    DECOY_PATH=""
    update_caddy_file
    systemctl restart hysteria-caddy.service

    echo -e "${green}Сайт-маскировка остановлен и удален из конфигурации.${NC}"
    if [ "$was_separate_port" = true ]; then
        echo -e "${green}Порт 443 больше не обслуживается Caddy.${NC}"
    else
        echo -e "${green}Пути на порту 443, не относящиеся к веб-панели, теперь будут возвращать ошибку соединения (или 403 Forbidden).${NC}"
    fi
}

setup_xhttp_route() {
    local xhttp_path=$1
    local xhttp_upstream=${2:-"$DEFAULT_XHTTP_UPSTREAM"}

    if [ -z "$xhttp_path" ]; then
        echo -e "${red}Использование: $0 xhttp <XHTTP_PATH (без ведущего /)> [UPSTREAM default ${DEFAULT_XHTTP_UPSTREAM}]${NC}"
        return 1
    fi

    if [ ! -f "$WEBPANEL_ENV_FILE" ]; then
        echo -e "${red}Ошибка: .env веб-панели не найден. Сначала запусти: $0 start ...${NC}"
        return 1
    fi

    sed -i "/^XHTTP_ENABLED=/d" "$WEBPANEL_ENV_FILE"
    sed -i "/^XHTTP_PATH=/d" "$WEBPANEL_ENV_FILE"
    sed -i "/^XHTTP_UPSTREAM=/d" "$WEBPANEL_ENV_FILE"
    echo "XHTTP_ENABLED=true" >> "$WEBPANEL_ENV_FILE"
    echo "XHTTP_PATH=$xhttp_path" >> "$WEBPANEL_ENV_FILE"
    echo "XHTTP_UPSTREAM=$xhttp_upstream" >> "$WEBPANEL_ENV_FILE"

    update_caddy_file
    systemctl restart hysteria-caddy.service
    echo -e "${green}XHTTP включён: /$xhttp_path/* -> $xhttp_upstream${NC}"
}

stop_xhttp_route() {
    if [ ! -f "$WEBPANEL_ENV_FILE" ]; then
        echo -e "${red}Ошибка: .env веб-панели не найден.${NC}"
        return 1
    fi

    sed -i "/^XHTTP_ENABLED=/d" "$WEBPANEL_ENV_FILE"
    sed -i "/^XHTTP_PATH=/d" "$WEBPANEL_ENV_FILE"
    sed -i "/^XHTTP_UPSTREAM=/d" "$WEBPANEL_ENV_FILE"
    echo "XHTTP_ENABLED=false" >> "$WEBPANEL_ENV_FILE"

    update_caddy_file
    systemctl restart hysteria-caddy.service
    echo -e "${green}XHTTP выключен.${NC}"
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
        local new_password_hash
        new_password_hash=$(echo -n "$new_password_val" | sha256sum | cut -d' ' -f1)
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
    source "$WEBPANEL_ENV_FILE"
    local webpanel_url="https://$DOMAIN:$PORT/$ROOT_PATH/"
    echo "$webpanel_url"
}

show_webpanel_api_token() {
    source "$WEBPANEL_ENV_FILE"
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
    rm -f "$WEBPANEL_ENV_FILE"
    rm -f "$CADDY_CONFIG_FILE"
}

case "$1" in
    start)
        if [ -z "${2:-}" ] || [ -z "${3:-}" ]; then
            echo -e "${red}Использование: $0 start <DOMAIN> <PORT> [ADMIN_USERNAME] [ADMIN_PASSWORD] [EXPIRATION_MINUTES] [DEBUG] [DECOY_PATH] [XHTTP_PATH] [XHTTP_UPSTREAM]${NC}"
            exit 1
        fi
        start_service "$2" "$3" "$4" "$5" "$6" "$7" "$8" "${9:-}" "${10:-}"
        ;;
    stop)
        stop_service
        ;;
    decoy)
        if [ -z "${2:-}" ] || [ -z "${3:-}" ]; then
            echo -e "${red}Использование: $0 decoy <DOMAIN> <PATH_TO_DECOY_SITE>${NC}"
            exit 1
        fi
        setup_decoy_site "$2" "$3"
        ;;
    stopdecoy)
        stop_decoy_site
        ;;
    xhttp)
        setup_xhttp_route "${2:-}" "${3:-}"
        ;;
    stopxhttp)
        stop_xhttp_route
        ;;
    resetcreds)
        shift
        reset_credentials "$@"
        ;;
    changeexp)
        change_expiration "${2:-}"
        ;;
    changeroot)
        change_root_path "${2:-}"
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
    genconfig)
        update_caddy_file
        ;;
    *)
        echo -e "${red}Использование: $0 {start|stop|decoy|stopdecoy|xhttp|stopxhttp|resetcreds|changeexp|changeroot|changedomain|url|api-token|genconfig}${NC}"
        echo -e "${yellow}start <DOMAIN> <PORT> [ADMIN_USERNAME] [ADMIN_PASSWORD] [EXPIRATION_MINUTES] [DEBUG] [DECOY_PATH] [XHTTP_PATH] [XHTTP_UPSTREAM]${NC}"
        echo -e "${yellow}decoy <DOMAIN> <PATH_TO_DECOY_SITE>${NC}"
        echo -e "${yellow}stopdecoy${NC}"
        echo -e "${yellow}xhttp <XHTTP_PATH(without leading /)> [UPSTREAM default ${DEFAULT_XHTTP_UPSTREAM}]${NC}"
        echo -e "${yellow}stopxhttp${NC}"
        echo -e "${yellow}resetcreds [-u new_username] [-p new_password]${NC}"
        echo -e "${yellow}changeexp <NEW_EXPIRATION_MINUTES>${NC}"
        echo -e "${yellow}changeroot [NEW_ROOT_PATH]${NC}"
        echo -e "${yellow}changedomain [-d new_domain] [-p new_port]${NC}"
        echo -e "${yellow}url${NC}"
        echo -e "${yellow}api-token${NC}"
        echo -e "${yellow}genconfig${NC}"
        exit 1
        ;;
esac
