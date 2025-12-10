#!/bin/bash

source /etc/hysteria/core/scripts/path.sh

SERVICE_NAME="hysteria-ip-limit.service"
DB_NAME="asgaroth_panel"
CONNECTIONS_COLLECTION="active_connections"

if [ -f "$CONFIG_ENV" ]; then
  source "$CONFIG_ENV"
  BLOCK_DURATION="${BLOCK_DURATION:-60}"
  GLOBAL_MAX_IPS="${MAX_IPS:-1}"
  
  grep -q "^BLOCK_DURATION=" "$CONFIG_ENV" || echo -e "\nBLOCK_DURATION=$BLOCK_DURATION" >> "$CONFIG_ENV"
  grep -q "^MAX_IPS=" "$CONFIG_ENV" || echo "MAX_IPS=$GLOBAL_MAX_IPS" >> "$CONFIG_ENV"
else
  BLOCK_DURATION=240
  GLOBAL_MAX_IPS=5
  echo -e "BLOCK_DURATION=240\nMAX_IPS=5" > "$CONFIG_ENV"
fi

[ ! -f "$BLOCK_LIST" ] && touch "$BLOCK_LIST"

log_message() {
    local level="$1"
    local message="$2"
    echo "[$(date +"%Y-%m-%d %H:%M:%S")] [$level] $message"
}

add_ip_to_db() {
    local username="$1"
    local ip_address="$2"
    
    mongosh "$DB_NAME" --quiet --eval "
        db.getCollection('$CONNECTIONS_COLLECTION').updateOne(
            { _id: '$username' },
            { \$addToSet: { ips: '$ip_address' } },
            { upsert: true }
        );
    "
    log_message "INFO" "Обновление БД: Добавлен $ip_address для пользователя $username"
}

remove_ip_from_db() {
    local username="$1"
    local ip_address="$2"
    
    mongosh "$DB_NAME" --quiet --eval "
        db.getCollection('$CONNECTIONS_COLLECTION').updateOne(
            { _id: '$username' },
            { \$pull: { ips: '$ip_address' } }
        );
        db.getCollection('$CONNECTIONS_COLLECTION').deleteMany(
            { _id: '$username', ips: { \$size: 0 } }
        );
    "
    log_message "INFO" "Обновление БД: Удален $ip_address для пользователя $username"
}

block_ip() {
    local ip_address="$1"
    local username="$2"
    local unblock_time=$(( $(date +%s) + BLOCK_DURATION ))

    if iptables -C INPUT -s "$ip_address" -j DROP 2>/dev/null; then
        return
    fi

    iptables -I INPUT -s "$ip_address" -j DROP
    echo "$ip_address,$username,$unblock_time" >> "$BLOCK_LIST"
    log_message "WARN" "Заблокирован IP $ip_address пользователя $username на $BLOCK_DURATION секунд"
}

unblock_ip() {
    local ip_address="$1"

    if iptables -C INPUT -s "$ip_address" -j DROP 2>/dev/null; then
        iptables -D INPUT -s "$ip_address" -j DROP
        log_message "INFO" "Разблокирован IP $ip_address"
    fi
    sed -i "/^$ip_address,/d" "$BLOCK_LIST"
}

block_all_user_ips() {
    local username="$1"
    
    local ips_json
    ips_json=$(mongosh "$DB_NAME" --quiet --eval "
        JSON.stringify(db.getCollection('$CONNECTIONS_COLLECTION').findOne({_id: '$username'}, {_id: 0, ips: 1}))
    ")

    if [[ -z "$ips_json" || "$ips_json" == "null" ]]; then
        return
    fi
    
    local ips
    readarray -t ips < <(echo "$ips_json" | jq -r '.ips[]')
    
    for ip in "${ips[@]}"; do
        if [[ -n "$ip" ]]; then
            block_ip "$ip" "$username"
        fi
    done

    log_message "WARN" "Пользователь $username полностью заблокирован на $BLOCK_DURATION секунд"
}

check_expired_blocks() {
    local current_time=$(date +%s)
    local ip username expiry

    while IFS=, read -r ip username expiry || [ -n "$ip" ]; do
        if [[ -n "$ip" && -n "$expiry" ]]; then
            if (( current_time >= expiry )); then
                unblock_ip "$ip"
                log_message "INFO" "Авто-разблокировка IP $ip для пользователя $username"
            fi
        fi
    done < "$BLOCK_LIST"
}

check_ip_limit() {
    local username="$1"
    
    local user_data_json
    user_data_json=$(mongosh "$DB_NAME" --quiet --eval "
        var active = db.getCollection('$CONNECTIONS_COLLECTION').findOne({_id: '$username'});
        var user = db.users.findOne({_id: '$username'}, {unlimited_user: 1, max_ips: 1});
        
        JSON.stringify({
            current_count: active ? (active.ips ? active.ips.length : 0) : 0,
            is_unlimited: user ? (user.unlimited_user || false) : false,
            personal_limit: user ? (user.max_ips || 0) : 0
        })
    ")

    local current_count=$(echo "$user_data_json" | jq -r '.current_count')
    local is_unlimited=$(echo "$user_data_json" | jq -r '.is_unlimited')
    local personal_limit=$(echo "$user_data_json" | jq -r '.personal_limit')

    if [[ "$is_unlimited" == "true" ]]; then
        return
    fi

    local effective_limit=$GLOBAL_MAX_IPS
    if [[ "$personal_limit" -gt 0 ]]; then
        effective_limit=$personal_limit
    fi

    if (( current_count > effective_limit )); then
        log_message "WARN" "У пользователя $username $current_count IP (Лимит: $effective_limit) - блокировка."
        block_all_user_ips "$username"
    fi
}

clean_all() {
    log_message "WARN" "Запуск очистки..."
    if [ -s "$BLOCK_LIST" ]; then
        while IFS=, read -r ip _; do
            if [[ -n "$ip" ]]; then unblock_ip "$ip"; fi
        done < "$BLOCK_LIST"
    fi
    > "$BLOCK_LIST"
    mongosh "$DB_NAME" --quiet --eval "db.getCollection('$CONNECTIONS_COLLECTION').drop();"
    log_message "INFO" "Очистка завершена."
}

parse_log_line() {
    local log_line="$1"
    local ip_address
    local username

    ip_address=$(echo "$log_line" | grep -oP '"addr": "([^:]+)' | cut -d'"' -f4)
    username=$(echo "$log_line" | grep -oP '"id": "([^">]+)' | cut -d'"' -f4)

    if [[ -n "$username" && -n "$ip_address" ]]; then
        if echo "$log_line" | grep -q "client connected"; then
            if grep -q "^$ip_address," "$BLOCK_LIST"; then
                if ! iptables -C INPUT -s "$ip_address" -j DROP 2>/dev/null; then
                    iptables -I INPUT -s "$ip_address" -j DROP
                fi
            else
                add_ip_to_db "$username" "$ip_address"
                check_ip_limit "$username"
            fi
        elif echo "$log_line" | grep -q "client disconnected"; then
            remove_ip_from_db "$username" "$ip_address"
        fi
    fi
}

install_service() {
    cat <<EOF > /etc/systemd/system/${SERVICE_NAME}
[Unit]
Description=Limit IP для Hysteria
After=network.target hysteria-server.service mongod.service
Requires=hysteria-server.service mongod.service

[Service]
Type=simple
ExecStart=/bin/bash ${SCRIPT_PATH} run
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable ${SERVICE_NAME}
    systemctl start ${SERVICE_NAME}
    log_message "INFO" "Служба Limit IP запущена"
}

uninstall_service() {
    systemctl stop ${SERVICE_NAME} 2>/dev/null
    systemctl disable ${SERVICE_NAME} 2>/dev/null
    rm -f /etc/systemd/system/${SERVICE_NAME}
    systemctl daemon-reload
}

change_config() {
    local new_block_duration="$1"
    local new_max_ips="$2"

    if [[ -n "$new_block_duration" ]]; then
      if ! [[ "$new_block_duration" =~ ^[0-9]+$ ]]; then
        return 1
      fi
      sed -i "s/^BLOCK_DURATION=.*/BLOCK_DURATION=$new_block_duration/" "$CONFIG_ENV"
      BLOCK_DURATION=$new_block_duration
    fi

    if [[ -n "$new_max_ips" ]]; then
      if ! [[ "$new_max_ips" =~ ^[0-9]+$ ]]; then
        return 1
      fi
      sed -i "s/^MAX_IPS=.*/MAX_IPS=$new_max_ips/" "$CONFIG_ENV"
      GLOBAL_MAX_IPS=$new_max_ips
    fi

    if systemctl is-active --quiet ${SERVICE_NAME}; then
      systemctl restart ${SERVICE_NAME}
    fi
}

if [[ $EUID -ne 0 ]]; then
    echo "Ошибка: Этот скрипт должен быть запущен от root."
    exit 1
fi

case "$1" in
    start) install_service ;;
    stop) uninstall_service ;;
    config) change_config "$2" "$3" ;;
    clean) clean_all ;;
    run)
        log_message "INFO" "Мониторинг подключений Hysteria. Глобальный макс. IP: $GLOBAL_MAX_IPS"
        ( while true; do check_expired_blocks; sleep 10; done ) &
        CHECKER_PID=$!
        cleanup() { kill $CHECKER_PID 2>/dev/null; exit 0; }
        trap cleanup SIGINT SIGTERM
        journalctl -u hysteria-server.service -f | while read -r line; do
            if echo "$line" | grep -q "client connected\|client disconnected"; then
                parse_log_line "$line"
            fi
        done
        ;;
    *) echo "Использование: $0 {start|stop|config|run|clean}"; exit 1 ;;
esac
exit 0