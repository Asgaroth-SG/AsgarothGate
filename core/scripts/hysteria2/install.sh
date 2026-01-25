#!/bin/bash

source /etc/hysteria/core/scripts/path.sh
source /etc/hysteria/core/scripts/utils.sh
source /etc/hysteria/core/scripts/scheduler.sh
define_colors


install_hysteria() {
    local port=$1
    local sni=$2

    # Проверка обязательных параметров
    if [[ -z "$port" ]]; then
        echo -e "${red}Ошибка:${NC} Порт не указан."
        exit 1
    fi
    
    if [[ -z "$sni" ]]; then
        echo -e "${red}Ошибка:${NC} SNI не указан."
        exit 1
    fi

    # Создаем пользователя hysteria заранее, если его нет
    if ! id -u hysteria &> /dev/null; then
        echo "Создание пользователя hysteria..."
        useradd -r -s /usr/sbin/nologin hysteria || {
            echo -e "${red}Ошибка:${NC} Не удалось создать пользователя hysteria."
            exit 1
        }
    fi
    
    mkdir -p /etc/hysteria && cd /etc/hysteria/
    
    echo "Установка Hysteria..."
    # Пытаемся установить Hysteria с несколькими попытками и увеличенным таймаутом
    install_success=false
    curl_error=""
    for attempt in 1 2 3; do
        curl_output=$(timeout 120 bash <(curl -fsSL --max-time 60 --connect-timeout 10 https://get.hy2.sh/) 2>&1)
        curl_exit_code=$?
        
        if [[ $curl_exit_code -eq 0 ]]; then
            install_success=true
            break
        else
            # Сохраняем последнюю ошибку
            curl_error="$curl_output"
            if [[ $attempt -lt 3 ]]; then
                echo "Попытка $attempt не удалась. Повторная попытка через 5 секунд..."
                sleep 5
            fi
        fi
    done
    
    if [[ "$install_success" == false ]]; then
        echo -e "${red}Ошибка:${NC} Не удалось загрузить и установить Hysteria после 3 попыток."
        echo "Проверьте подключение к интернету и доступность https://get.hy2.sh/"
        if [[ -n "$curl_error" ]]; then
            echo "Детали ошибки:"
            echo "$curl_error" | head -5
        fi
        exit 1
    fi
    
    # Проверяем, что Hysteria действительно установлен
    if ! command -v hysteria &> /dev/null; then
        echo -e "${red}Ошибка:${NC} Hysteria не был установлен. Проверьте логи выше."
        exit 1
    fi

    echo "Генерация ключа CA и сертификата..."
    if ! openssl ecparam -genkey -name prime256v1 -out ca.key >/dev/null 2>&1; then
        echo -e "${red}Ошибка:${NC} Не удалось сгенерировать ключ CA."
        exit 1
    fi
    
    if ! openssl req -new -x509 -days 36500 -key ca.key -out ca.crt -subj "/CN=$sni" >/dev/null 2>&1; then
        echo -e "${red}Ошибка:${NC} Не удалось сгенерировать сертификат CA."
        exit 1
    fi
    
    echo "Загрузка гео-данных..."
    if ! timeout 60 wget --timeout=30 -O /etc/hysteria/geosite.dat https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/release/geosite.dat >/dev/null 2>&1; then
        echo -e "${yellow}Предупреждение:${NC} Не удалось загрузить geosite.dat. Продолжаем установку..."
    fi
    
    if ! timeout 60 wget --timeout=30 -O /etc/hysteria/geoip.dat https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/release/geoip.dat >/dev/null 2>&1; then
        echo -e "${yellow}Предупреждение:${NC} Не удалось загрузить geoip.dat. Продолжаем установку..."
    fi
        
    echo "Генерация SHA-256 отпечатка (base64)..."
    
    if [[ ! -f ca.crt ]]; then
        echo -e "${red}Ошибка:${NC} Файл сертификата ca.crt не найден."
        exit 1
    fi
    
    sha256=$(openssl x509 -noout -fingerprint -sha256 -inform pem -in ca.crt 2>/dev/null | sed 's/.*=//;s/://g' | tr '[:upper:]' '[:lower:]')
    
    if [[ -z "$sha256" ]]; then
        echo -e "${red}Ошибка:${NC} Не удалось извлечь SHA-256 отпечаток из сертификата."
        exit 1
    fi
    
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
    if command -v pwgen &> /dev/null; then
        obfspassword=$(pwgen -s 32 1)
    else
        # Альтернативная генерация пароля, если pwgen не установлен
        obfspassword=$(openssl rand -base64 24 | tr -d "=+/" | cut -c1-32)
    fi
    UUID=$(cat /proc/sys/kernel/random/uuid)
    
    # Устанавливаем права на файлы (пользователь hysteria уже должен существовать)
    chown hysteria:hysteria /etc/hysteria/ca.key /etc/hysteria/ca.crt 2>/dev/null || {
        echo -e "${yellow}Предупреждение:${NC} Не удалось установить владельца файлов на hysteria. Продолжаем..."
    }
    chmod 640 /etc/hysteria/ca.key /etc/hysteria/ca.crt
    
    networkdef=$(ip route | grep "^default" | awk '{print $5}')
    
    echo "Настройка config.json..."
    # Создаем базовый config.json, если его нет
    if [[ ! -f "$CONFIG_FILE" ]]; then
        echo "Создание базового config.json..."
        cat > "$CONFIG_FILE" << 'EOF'
{
  "listen": ":443",
  "tls": {
    "cert": "/etc/hysteria/ca.crt",
    "key": "/etc/hysteria/ca.key",
    "insecure": true,
    "pinSHA256": ""
  },
  "obfs": {
    "type": "salamander",
    "salamander": {
      "password": ""
    }
  },
  "auth": {
    "type": "http",
    "http": {
      "url": "http://127.0.0.1:28262/auth"
    }
  },
  "quic": {
    "initStreamReceiveWindow": 4194304,
    "maxStreamReceiveWindow": 4194304,
    "initConnReceiveWindow": 10485760,
    "maxConnReceiveWindow": 10485760,
    "maxIdleTimeout": "15s",
    "maxIncomingStreams": 128,
    "disablePathMTUDiscovery": true
  },
  "bandwidth": {
    "up": "100 mbps",
    "down": "100 mbps"
  },
  "ignoreClientBandwidth": false,
  "disableUDP": false,
  "speedTest": false,
  "udpIdleTimeout": "20s",
  "resolver": {
    "type": "udp",
    "udp": {
      "addr": "94.140.14.14:53",
      "timeout": "4s"
    }
  },
  "outbounds": [
    {
      "name": "v4",
      "type": "direct",
      "direct": {
        "mode": 4,
        "bindDevice": ""
      }
    }
  ],
  "acl": {
    "inline": [
      "reject(geoip:private)",
      "reject(geoip:phishing)",
      "reject(geoip:malware)",
      "reject(geosite:category-ads-all)",
      "reject(geosite:google@ads)",
      "reject(geosite:malware)",
      "reject(geosite:phishing)",
      "reject(geosite:cryptominers)",
      "reject(10.0.0.0/8)",
      "reject(172.16.0.0/12)",
      "reject(192.168.0.0/16)",
      "reject(fc00::/7)"
    ],
    "geoip": "/etc/hysteria/geoip.dat",
    "geosite": "/etc/hysteria/geosite.dat"
  },
  "trafficStats": {
    "listen": "127.0.0.1:25413",
    "secret": ""
  }
}
EOF
        chown hysteria:hysteria "$CONFIG_FILE" 2>/dev/null || true
        chmod 640 "$CONFIG_FILE"
    fi
    
    if ! command -v jq &> /dev/null; then
        echo -e "${red}Ошибка:${NC} jq не установлен. Установите jq для продолжения."
        exit 1
    fi
    
    if ! jq --arg port "$port" \
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
        .outbounds[0].direct.bindDevice = $networkdef' "$CONFIG_FILE" > "${CONFIG_FILE}.temp" 2>/dev/null; then
        echo -e "${red}Ошибка:${NC} Не удалось обновить config.json."
        rm -f "${CONFIG_FILE}.temp"
        exit 1
    fi
    
    mv "${CONFIG_FILE}.temp" "$CONFIG_FILE"
    
    echo "Обновление hysteria-server.service для использования конфига Blitz Panel..."
    if [[ -f /etc/systemd/system/hysteria-server.service ]]; then
        sed -i 's|(config.yaml)|(Blitz Panel)|' /etc/systemd/system/hysteria-server.service 2>/dev/null || true
        sed -i "s|/etc/hysteria/config.yaml|$CONFIG_FILE|" /etc/systemd/system/hysteria-server.service 2>/dev/null || true
    else
        echo -e "${yellow}Предупреждение:${NC} Файл /etc/systemd/system/hysteria-server.service не найден."
        echo "Возможно, установщик Hysteria не создал файл сервиса. Проверьте установку Hysteria."
    fi
    
    # Удаляем старый config.yaml, если он существует
    if [[ -f /etc/hysteria/config.yaml ]]; then
        rm -f /etc/hysteria/config.yaml 2>/dev/null || true
    fi
    
    sleep 1
    
    # Проверяем наличие файла сервиса перед попыткой запуска
    if [[ ! -f /etc/systemd/system/hysteria-server.service ]]; then
        echo -e "${red}Ошибка:${NC} Файл сервиса /etc/systemd/system/hysteria-server.service не найден."
        echo "Установщик Hysteria не создал файл сервиса. Установка не может быть завершена."
        exit 1
    fi
    
    echo "Запуск и включение службы Hysteria..."
    systemctl daemon-reload >/dev/null 2>&1 || {
        echo -e "${yellow}Предупреждение:${NC} Не удалось перезагрузить systemd daemon."
    }
    
    systemctl enable hysteria-server.service >/dev/null 2>&1 || {
        echo -e "${yellow}Предупреждение:${NC} Не удалось включить автозапуск сервиса."
    }
    
    systemctl start hysteria-server.service >/dev/null 2>&1 || {
        echo -e "${red}Ошибка:${NC} Не удалось запустить hysteria-server.service."
        echo "Проверьте логи: journalctl -u hysteria-server.service"
        exit 1
    }
    
    # Даем сервису время на запуск
    sleep 2
    
    if systemctl is-active --quiet hysteria-server.service; then
        echo -e "${cyan}Hysteria${NC} была успешно установлена."
    else
        echo -e "${red}Ошибка:${NC} hysteria-server.service не активна."
        echo "Проверьте логи: journalctl -u hysteria-server.service -n 50"
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
        echo -e "${red}Ошибка:${NC} hysteria-auth.service не активна."
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
    install_hysteria "$1" "$2"
    echo -e "\n"

    if systemctl is-active --quiet hysteria-server.service; then
        echo "Установка и конфигурация завершены."
        python3 $CLI_PATH add-user --username default --traffic-limit 30 --expiration-days 30
    else
        echo -e "${red}Ошибка:${NC} Служба Hysteria не активна. Проверьте логи для подробностей."
    fi
fi