#!/bin/bash

source /etc/hysteria/core/scripts/path.sh
source /etc/hysteria/core/scripts/utils.sh
source /etc/hysteria/core/scripts/scheduler.sh
define_colors


install_hysteria() {
    local port=$1
    local sni=$2

    # Создаем пользователя hysteria заранее, если его нет
    if ! id -u hysteria &> /dev/null; then
        useradd -r -s /usr/sbin/nologin hysteria
    fi

    echo "Установка Hysteria..."
    # Пробуем стандартный установщик, если не получается - используем GitHub
    if ! bash <(curl -fsSL --max-time 60 https://get.hy2.sh/) >/dev/null 2>&1; then
        echo "Стандартный установщик недоступен, используем GitHub..."
        local arch=$(uname -m)
        case $arch in
            x86_64|amd64) arch="amd64" ;;
            aarch64|arm64) arch="arm64" ;;
            *) arch="amd64" ;;
        esac
        
        local latest_version="v2.4.3"
        local download_url="https://github.com/apernet/hysteria/releases/download/${latest_version}/hysteria-linux-${arch}"
        local binary_path="/usr/local/bin/hysteria"
        
        if curl -fsSL --max-time 300 -o "$binary_path" "$download_url" 2>/dev/null; then
            chmod +x "$binary_path"
            cat > /etc/systemd/system/hysteria-server.service << EOFSERVICE
[Unit]
Description=Hysteria2 Server Service (Blitz Panel)
After=network.target

[Service]
Type=simple
User=hysteria
Group=hysteria
ExecStart=/usr/local/bin/hysteria server -c $CONFIG_FILE
Restart=on-failure
RestartSec=5s
LimitNOFILE=infinity

[Install]
WantedBy=multi-user.target
EOFSERVICE
            systemctl daemon-reload
        else
            echo -e "${red}Ошибка:${NC} Не удалось установить Hysteria."
            exit 1
        fi
    fi
    
    mkdir -p /etc/hysteria && cd /etc/hysteria/

    echo "Генерация ключа CA и сертификата..."
    openssl ecparam -genkey -name prime256v1 -out ca.key >/dev/null 2>&1
    openssl req -new -x509 -days 36500 -key ca.key -out ca.crt -subj "/CN=$sni" >/dev/null 2>&1
    echo "Загрузка гео-данных..."
    wget -O /etc/hysteria/geosite.dat https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/release/geosite.dat >/dev/null 2>&1 || true
    wget -O /etc/hysteria/geoip.dat https://raw.githubusercontent.com/Chocolate4U/Iran-v2ray-rules/release/geoip.dat >/dev/null 2>&1 || true
        
    echo "Генерация SHA-256 отпечатка..."

    sha256=$(openssl x509 -noout -fingerprint -sha256 -inform pem -in ca.crt | sed 's/.*=//' | tr '[:lower:]' '[:upper:]')
    
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
        obfspassword=$(openssl rand -base64 24 | tr -d "=+/" | cut -c1-32)
    fi
    UUID=$(cat /proc/sys/kernel/random/uuid)
    
    chown hysteria:hysteria /etc/hysteria/ca.key /etc/hysteria/ca.crt 2>/dev/null || true
    chmod 640 /etc/hysteria/ca.key /etc/hysteria/ca.crt
    
    networkdef=$(ip route | grep "^default" | awk '{print $5}')
    
    echo "Настройка config.json..."
    # Создаем базовый config.json, если его нет
    if [[ ! -f "$CONFIG_FILE" ]]; then
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
    if [[ -f /etc/systemd/system/hysteria-server.service ]]; then
        sed -i 's|(config.yaml)|(Blitz Panel)|' /etc/systemd/system/hysteria-server.service 2>/dev/null || true
        sed -i "s|/etc/hysteria/config.yaml|$CONFIG_FILE|" /etc/systemd/system/hysteria-server.service 2>/dev/null || true
        
        # Исправляем WorkingDirectory - убираем если директория не существует
        if grep -q "^WorkingDirectory=" /etc/systemd/system/hysteria-server.service 2>/dev/null; then
            local work_dir=$(grep "^WorkingDirectory=" /etc/systemd/system/hysteria-server.service | cut -d'=' -f2)
            if [[ -n "$work_dir" ]] && [[ ! -d "$work_dir" ]]; then
                sed -i '/^WorkingDirectory=/d' /etc/systemd/system/hysteria-server.service
            fi
        fi
    fi
    
    rm -f /etc/hysteria/config.yaml 2>/dev/null || true
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
