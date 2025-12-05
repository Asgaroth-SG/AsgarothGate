#!/bin/bash

source /etc/hysteria/core/scripts/path.sh
source /etc/hysteria/core/scripts/utils.sh
source /etc/hysteria/core/scripts/scheduler.sh
define_colors


install_hysteria() {
    local port=$1

    echo "Установка Hysteria..."

    echo
    echo " Настройка названия ноды Hysteria"
    read -rp "Отображаемое название ноды (например: 🇩🇪 Германия) [по умолчанию Default]: " node_label
    if [ -z "$node_label" ]; then
        node_label="Default"
    fi

    local config_env="${CONFIG_ENV:-/etc/hysteria/.configs.env}"

    mkdir -p /etc/hysteria

    if [ -f "$config_env" ]; then
        grep -v '^MAIN_NODE_LABEL=' "$config_env" > "${config_env}.tmp" || true
        mv "${config_env}.tmp" "$config_env"
    else
        touch "$config_env"
    fi
    echo "MAIN_NODE_LABEL=$node_label" >> "$config_env"

    echo "$node_label" > /etc/hysteria/.main_node_label

    echo "Название ноды установлено: $node_label"
    echo "Сохранено в: $config_env и /etc/hysteria/.main_node_label"
    echo

    bash <(curl -fsSL https://get.hy2.sh/) >/dev/null 2>&1
    
    cd /etc/hysteria/ || {
        echo -e "${red}Не удалось перейти в /etc/hysteria${NC}"
        exit 1
    }

    echo "Генерация ключа CA и сертификата..."
    openssl ecparam -genkey -name prime256v1 -out ca.key >/dev/null 2>&1
    openssl req -new -x509 -days 36500 -key ca.key -out ca.crt -subj "/CN=$sni" >/dev/null 2>&1
    echo "Загрузка гео-данных..."
    wget -O /etc/hysteria/geosite.dat https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/release/geosite.dat >/dev/null 2>&1
    wget -O /etc/hysteria/geoip.dat https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/release/geoip.dat >/dev/null 2>&1
        
    echo "Генерация SHA-256 отпечатка (base64)..."

    sha256=$(openssl x509 -noout -fingerprint -sha256 -inform pem -in ca.crt | sed 's/.*=//;s///g')
    
    if [[ $port =~ ^[0-9]+$ ]] && (( port >= 1 && port <= 65535 )); then
        if ss -tuln | grep -q ":$port\b"; then
            echo -e "${red}Порт $port уже используется. Пожалуйста, выберите другой порт.${NC}"
            exit 1
        fi
    else
        echo "Неверный номер порта. Пожалуйста, введите число от 1 до 65535."
        exit 1
    fi
    
    echo "Генерация паролей и UUID..."
    obfspassword=$(pwgen -s 32 1)
    UUID=$(cat /proc/sys/kernel/random/uuid)
    
    chown hysteria:hysteria /etc/hysteria/ca.key /etc/hysteria/ca.crt
    chmod 640 /etc/hysteria/ca.key /etc/hysteria/ca.crt
    
    if ! id -u hysteria &> /dev/null; then
        useradd -r -s /usr/sbin/nologin hysteria
    fi
    
    networkdef=$(ip route | grep "^default" | awk '{print $5}')
    
    echo "Настройка config.json..."
    jq --arg port "$port" \
       --arg sha256 "$sha256" \
       --arg obfspassword "$obfspassword" \
       --arg UUID "$UUID" \
       --arg networkdef "$networkdef" \
       '.listen = ":\($port)" |
        .tls.cert = "/etc/hysteria/ca.crt" |
        .tls.key = "/etc/hysteria/ca.key" |
        .tls.pinSHA256 = $sha256 |
        .obfs.salamander.password = $obfspassword |
        .trafficStats.secret = $UUID |
        .outbounds[0].direct.bindDevice = $networkdef' "$CONFIG_FILE" > "${CONFIG_FILE}.temp" && mv "${CONFIG_FILE}.temp" "$CONFIG_FILE"
    
    echo "Обновление hysteria-server.service для использования конфига Blitz Panel..."
    sed -i 's|(config.yaml)|(Blitz Panel)|' /etc/systemd/system/hysteria-server.service
    sed -i "s|/etc/hysteria/config.yaml|$CONFIG_FILE|" /etc/systemd/system/hysteria-server.service
    rm /etc/hysteria/config.yaml
    sleep 1
    
    echo "Запуск и включение службы Hysteria..."
    systemctl daemon-reload >/dev/null 2>&1
    systemctl start hysteria-server.service >/dev/null 2>&1
    systemctl enable hysteria-server.service >/dev/null 2>&1
    systemctl restart hysteria-server.service >/dev/null 2>&1
    
    if systemctl is-active --quiet hysteria-server.service; then
        echo -e "${cyan}Hysteria${NC} была успешно установлена."
    else
        echo -e "${red}Ошибка:${NC} hysteria-server.service не активна."
        exit 1
    fi
    
    chmod +x /etc/hysteria/core/scripts/hysteria2/kick.py

    if ! check_auth_server_service; then
        echo "Настройка сервера аутентификации Hysteria..."
        setup_hysteria_auth_server
    fi

    if systemctl is-active --quiet hysteria-auth.service; then
        echo -e "${cyan}Сервер аутентификации Hysteria${NC} успешно запущен."
    else
        echo -е "${red}Ошибка:${NC} hysteria-auth.service не активна."
        exit 1
    fi

    if ! check_scheduler_service; then
        setup_hysteria_scheduler
    fi
}

if systemctl is-active --quiet hysteria-server.service; then
    echo -e "${red}Ошибка:${NC} Hysteria уже установлена и запущена."
    echo
    echo "Если вам нужно обновить ядро, используйте опцию 'Update Core'."
else
    echo "Установка и настройка Hysteria..."
    install_hysteria "$1"
    echo -e "\n"

    if systemctl is-active --quiet hysteria-server.service; then
        echo "Установка и конфигурация завершены."
        python3 $CLI_PATH add-user --username default --traffic-limit 30 --expiration-days 30
    else
        echo -e "${red}Ошибка:${NC} Служба Hysteria не активна. Проверьте логи для подробностей."
    fi
fi
