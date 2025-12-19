#!/bin/bash

source /etc/hysteria/core/scripts/utils.sh
source /etc/hysteria/core/scripts/path.sh
source /etc/hysteria/core/scripts/services_status.sh >/dev/null 2>&1

# --- TTY safety ---
# Prevent 100% CPU spin when script is launched without an interactive stdin.
if [[ ! -t 0 ]]; then
    if [[ -r /dev/tty ]]; then
        exec </dev/tty
    else
        echo "Ошибка: menu.sh запущен без TTY (stdin не терминал). Завершаю работу, чтобы не грузить CPU."
        exit 1
    fi
fi
# --- /TTY safety ---


check_services() {
    for service in "${services[@]}"; do
        service_base_name=$(basename "$service" .service)

        display_name=$(echo "$service_base_name" | sed -E 's/([^-]+)-?/\u\1/g') 

        if systemctl is-active --quiet "$service"; then
            echo -e "${NC}${display_name}:${green} Активен${NC}"
        else
            echo -e "${NC}${display_name}:${red} Неактивен${NC}"
        fi
    done
}

hysteria2_install_handler() {
    if systemctl is-active --quiet hysteria-server.service; then
        echo "Сервис hysteria-server.service в данный момент активен."
        echo "Если вам нужно обновить ядро, используйте опцию 'Обновить ядро Hysteria'."
        return
    fi

    while true; do
        read -p "Введите SNI (по умолчанию: bts.com): " sni
        sni=${sni:-bts.com}
        
        read -p "Введите номер порта, который хотите использовать: " port
        if ! [[ "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
            echo "Неверный номер порта. Пожалуйста, введите число от 1 до 65535."
        else
            break
        fi
    done

    
    python3 $CLI_PATH install-hysteria2 --port "$port" --sni "$sni"

    cat <<EOF > /etc/hysteria/.configs.env
SNI=$sni
EOF
    python3 $CLI_PATH ip-address
}

hysteria2_add_user_handler() {
    while true; do
        read -p "Введите имя пользователя: " username

        if [[ "$username" =~ ^[a-zA-Z0-9]+$ ]]; then
            if [[ -n $(python3 $CLI_PATH get-user -u "$username" 2>/dev/null) ]]; then
                echo -e "${red}Ошибка:${NC} Имя пользователя уже существует. Пожалуйста, выберите другое."
            else
                break
            fi
        else
            echo -e "${red}Ошибка:${NC} Имя пользователя может содержать только буквы и цифры."
        fi
    done

    read -p "Введите лимит трафика (в ГБ): " traffic_limit_GB

    read -p "Введите срок действия (в днях): " expiration_days
    
    local unlimited_arg=""
    while true; do
        read -p "Освободить пользователя от проверки лимита IP (безлимитные IP)? (y/n) [n]: " unlimited_choice
        case "$unlimited_choice" in
            y|Y) unlimited_arg="--unlimited"; break ;;
            n|N|"") break ;;
            *) echo -e "${red}Ошибка:${NC} Пожалуйста, ответьте 'y' или 'n'." ;;
        esac
    done
    
    password=$(pwgen -s 32 1)
    creation_date=$(date +%Y-%m-%d)

    python3 $CLI_PATH add-user --username "$username" --traffic-limit "$traffic_limit_GB" --expiration-days "$expiration_days" --password "$password" --creation-date "$creation_date" $unlimited_arg
}

hysteria2_edit_user_handler() {
    prompt_for_input() {
        local prompt_message="$1"
        local validation_regex="$2"
        local default_value="$3"
        local input_variable_name="$4"

        while true; do
            read -p "$prompt_message" input
            if [[ -z "$input" ]]; then
                input="$default_value"
            fi
            if [[ "$input" =~ $validation_regex ]]; then
                eval "$input_variable_name='$input'"
                break
            else
                echo -e "${red}Ошибка:${NC} Неверный ввод. Пожалуйста, попробуйте снова."
            fi
        done
    }

    prompt_for_input "Введите имя пользователя, которого хотите отредактировать: " '^[a-zA-Z0-9]+$' '' username

    user_exists_output=$(python3 $CLI_PATH get-user -u "$username" 2>&1)
    if [[ -z "$user_exists_output" ]]; then
        echo -e "${red}Ошибка:${NC} Пользователь '$username' не найден или произошла ошибка."
        return 1
    fi

    prompt_for_input "Введите новое имя пользователя (оставьте пустым, чтобы сохранить текущее): " '^[a-zA-Z0-9]*$' '' new_username

    prompt_for_input "Введите новый лимит трафика (в ГБ) (оставьте пустым, чтобы сохранить текущий): " '^[0-9]*$' '' new_traffic_limit_GB

    prompt_for_input "Введите новый срок действия в днях (оставьте пустым, чтобы сохранить текущий): " '^[0-9]*$' '' new_expiration_days

    while true; do
        read -p "Хотите сгенерировать новый пароль? (y/n) [n]: " renew_password
        case "$renew_password" in
            y|Y) renew_password=true; break ;;
            n|N|"") renew_password=false; break ;;
            *) echo -e "${red}Ошибка:${NC} Пожалуйста, ответьте 'y' или 'n'." ;;
        esac
    done

    while true; do
        read -p "Хотите обновить дату создания? (y/n) [n]: " renew_creation_date
        case "$renew_creation_date" in
            y|Y) renew_creation_date=true; break ;;
            n|N|"") renew_creation_date=false; break ;;
            *) echo -e "${red}Ошибка:${NC} Пожалуйста, ответьте 'y' или 'n'." ;;
        esac
    done

    local blocked_arg=""
    while true; do
        read -p "Изменить статус блокировки? ([b]лок/[u]разблок/[s]пропустить) [s]: " block_user
        case "$block_user" in
            b|B) blocked_arg="--blocked"; break ;;
            u|U) blocked_arg="--unblocked"; break ;;
            s|S|"") break ;;
            *) echo -e "${red}Ошибка:${NC} Пожалуйста, ответьте 'b', 'u' или 's'." ;;
        esac
    done

    local ip_limit_arg=""
    while true; do
        read -p "Изменить статус лимита IP? ([u]безлимит/[l]имит/[s]пропустить) [s]: " ip_limit_status
        case "$ip_limit_status" in
            u|U) ip_limit_arg="--unlimited-ip"; break ;;
            l|L) ip_limit_arg="--limited-ip"; break ;;
            s|S|"") break ;;
            *) echo -e "${red}Ошибка:${NC} Пожалуйста, ответьте 'u', 'l' или 's'." ;;
        esac
    done

    args=()
    if [[ -n "$new_username" ]]; then args+=("--new-username" "$new_username"); fi
    if [[ -n "$new_traffic_limit_GB" ]]; then args+=("--new-traffic-limit" "$new_traffic_limit_GB"); fi
    if [[ -n "$new_expiration_days" ]]; then args+=("--new-expiration-days" "$new_expiration_days"); fi
    if [[ "$renew_password" == "true" ]]; then args+=("--renew-password"); fi
    if [[ "$renew_creation_date" == "true" ]]; then args+=("--renew-creation-date"); fi
    if [[ -n "$blocked_arg" ]]; then args+=("$blocked_arg"); fi
    if [[ -n "$ip_limit_arg" ]]; then args+=("$ip_limit_arg"); fi

    python3 $CLI_PATH edit-user --username "$username" "${args[@]}"
}

hysteria2_remove_user_handler() {
    while true; do
        read -p "Введите имя пользователя: " username

        if [[ "$username" =~ ^[a-zA-Z0-9]+$ ]]; then
            break
        else
            echo -e "${red}Ошибка:${NC} Имя пользователя может содержать только буквы и цифры."
        fi
    done
    python3 "$CLI_PATH" remove-user "$username"
}

hysteria2_get_user_handler() {
    while true; do
        read -p "Введите имя пользователя: " username
        if [[ "$username" =~ ^[a-zA-Z0-9]+$ ]]; then
            break
        else
            echo -e "${red}Ошибка:${NC} Имя пользователя может содержать только буквы и цифры."
        fi
    done

    user_data=$(python3 "$CLI_PATH" get-user -u "$username" 2>/dev/null)
    exit_code=$?

    if [[ $exit_code -ne 0 || -z "$user_data" ]]; then
        echo -e "${red}Ошибка:${NC} Пользователь '$username' не найден или получен неверный ответ."
        return 1
    fi

    password=$(echo "$user_data" | jq -r '.password // "N/A"')
    max_download_bytes=$(echo "$user_data" | jq -r '.max_download_bytes // 0')
    upload_bytes=$(echo "$user_data" | jq -r '.upload_bytes // 0')
    download_bytes=$(echo "$user_data" | jq -r '.download_bytes // 0')
    account_creation_date=$(echo "$user_data" | jq -r '.account_creation_date // "N/A"')
    expiration_days=$(echo "$user_data" | jq -r '.expiration_days // 0')
    blocked=$(echo "$user_data" | jq -r '.blocked // false')
    status=$(echo "$user_data" | jq -r '.status // "N/A"')
    total_usage=$((upload_bytes + download_bytes))
    max_download_gb=$(echo "scale=2; $max_download_bytes / 1073741824" | bc)
    upload_gb=$(echo "scale=2; $upload_bytes / 1073741824" | bc)
    download_gb=$(echo "scale=2; $download_bytes / 1073741824" | bc)
    total_usage_gb=$(echo "scale=2; $total_usage / 1073741824" | bc)
    expiration_date=$(date -d "$account_creation_date + $expiration_days days" +"%Y-%m-%d")
    current_date=$(date +"%Y-%m-%d")
    used_days=$(( ( $(date -d "$current_date" +%s) - $(date -d "$account_creation_date" +%s) ) / 86400 ))

    if [[ $used_days -gt $expiration_days ]]; then
        used_days=$expiration_days
    fi

    echo -e "${green}Детали пользователя:${NC}"
    echo -e "Имя:              $username"
    echo -e "Пароль:           $password"
    echo -e "Всего трафика:    $max_download_gb GB"
    echo -e "Использовано:     $total_usage_gb GB"
    echo -e "Истекает:         $expiration_date ($used_days/$expiration_days дней)"
    echo -e "Заблокирован:     $blocked"
    echo -e "Статус:           $status"
}

hysteria2_list_users_handler() {
    users_json=$(python3 $CLI_PATH list-users 2>/dev/null)
    
    if [ $? -ne 0 ] || [ -z "$users_json" ]; then
        echo -e "${red}Ошибка:${NC} Не удалось получить список пользователей."
        return 1
    fi
    
    user_count=$(echo "$users_json" | jq 'length')
    
    if [ "$user_count" -eq 0 ]; then
        echo -e "${red}Ошибка:${NC} Пользователи не найдены."
        return 1
    fi
    
    printf "%-20s %-20s %-15s %-20s %-30s %-10s %-15s %-15s %-15s %-10s\n" \
        "Пользователь" "Трафик(ГБ)" "Срок(Дни)" "Создан" "Пароль" "Блок" "Статус" "Скач(МБ)" "Загр(МБ)" "Online"
    
    echo "$users_json" | jq -r '.[] | 
        [.username, 
         (if .max_download_bytes == 0 then "Безлимит" else (.max_download_bytes / 1073741824 | tostring) end),
         (if .expiration_days == 0 then "Никогда" else (.expiration_days | tostring) end),
         (.account_creation_date // "N/A"),
         .password,
         .blocked,
         .status,
         ((.download_bytes // 0) / 1048576 | floor),
         ((.upload_bytes // 0) / 1048576 | floor),
         .online_count] | 
        @tsv' | \
    while IFS=$'\t' read -r username traffic expiry created password blocked status down up online; do
        printf "%-20s %-20s %-15s %-20s %-30s %-10s %-15s %-15s %-15s %-10s\n" \
            "$username" "$traffic" "$expiry" "$created" "$password" "$blocked" "$status" "$down" "$up" "${online:-0}"
    done
}

hysteria2_reset_user_handler() {
    while true; do
        read -p "Введите имя пользователя: " username

        if [[ "$username" =~ ^[a-zA-Z0-9]+$ ]]; then
            break
        else
            echo -e "${red}Ошибка:${NC} Имя пользователя может содержать только буквы и цифры."
        fi
    done
    python3 $CLI_PATH reset-user --username "$username"
}

hysteria2_show_user_uri_handler() {
    check_service_active() {
        systemctl is-active --quiet "$1"
    }

    while true; do
        read -p "Введите имя пользователя: " username
        if [[ "$username" =~ ^[a-zA-Z0-9]+$ ]]; then
            break
        else
            echo -e "${red}Ошибка:${NC} Имя пользователя может содержать только буквы и цифры."
        fi
    done

    flags=""
    
    if check_service_active "hysteria-singbox.service"; then
        flags+=" -s"
    fi

    if check_service_active "hysteria-normal-sub.service"; then
        flags+=" -n"
    fi

    if [[ -n "$flags" ]]; then
        python3 $CLI_PATH show-user-uri -u "$username" -a -qr $flags
    else
        python3 $CLI_PATH show-user-uri -u "$username" -a -qr
    fi
}


hysteria2_change_port_handler() {
    while true; do
        read -p "Введите новый номер порта, который хотите использовать: " port
        if ! [[ "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
            echo "Неверный номер порта. Пожалуйста, введите число от 1 до 65535."
        else
            break
        fi
    done
    python3 $CLI_PATH change-hysteria2-port --port "$port"
}

hysteria2_change_sni_handler() {
    while true; do
        read -p "Введите новый SNI (например, example.com): " sni

        if [[ "$sni" =~ ^[a-zA-Z0-9.]+$ ]]; then
            break
        else
            echo -e "${red}Ошибка:${NC} SNI может содержать только буквы, цифры и точки."
        fi
    done

    python3 $CLI_PATH change-hysteria2-sni --sni "$sni"

    if systemctl is-active --quiet hysteria-singbox.service; then
        systemctl restart hysteria-singbox.service
    fi
}

edit_ips() {
    while true; do
        echo "======================================"
        echo "    Управление IP/Доменными адресами  "
        echo "======================================"
        echo "1. Изменить IPv4 или Домен"
        echo "2. Изменить IPv6 или Домен"
        echo "0. Назад"
        echo "======================================"
        read -p "Выберите опцию [0-2]: " choice

        case $choice in
            1)
                read -p "Введите новый IPv4 адрес или домен: " new_ip4_or_domain
                if [[ $new_ip4_or_domain =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
                    if ! echo "$new_ip4_or_domain" | awk -F. '{for (i=1;i<=NF;i++) if ($i>255) exit 1}'; then
                        echo "Ошибка: Неверный IPv4 адрес. Значения должны быть от 0 до 255."
                    else
                        python3 "$CLI_PATH" ip-address --edit -4 "$new_ip4_or_domain"
                        echo "IPv4 адрес был обновлен на $new_ip4_or_domain."
                    fi
                elif [[ $new_ip4_or_domain =~ ^[a-zA-Z0-9.-]+$ ]] && [[ ! $new_ip4_or_domain =~ [/:] ]]; then
                    python3 "$CLI_PATH" ip-address --edit -4 "$new_ip4_or_domain"
                    echo "Домен был обновлен на $new_ip4_or_domain."
                else
                    echo "Ошибка: Неверный формат IPv4 или домена."
                fi
                break
                ;;
            2)
                read -p "Введите новый IPv6 адрес или домен: " new_ip6_or_domain
                if [[ $new_ip6_or_domain =~ ^(([0-9a-fA-F]{1,4}:){7}([0-9a-fA-F]{1,4}|:)|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))$ ]]; then
                    python3 "$CLI_PATH" ip-address --edit -6 "$new_ip6_or_domain"
                    echo "IPv6 адрес был обновлен на $new_ip6_or_domain."
                elif [[ $new_ip6_or_domain =~ ^[a-zA-Z0-9.-]+$ ]] && [[ ! $new_ip6_or_domain =~ [/:] ]]; then
                    python3 "$CLI_PATH" ip-address --edit -6 "$new_ip6_or_domain"
                    echo "Домен был обновлен на $new_ip6_or_domain."
                else
                    echo "Ошибка: Неверный формат IPv6 или домена."
                fi
                break
                ;;
            0)
                break
                ;;
            *)
                echo "Неверная опция. Пожалуйста, попробуйте снова."
                break
                ;;
        esac
        echo "======================================"
        read -p "Нажмите Enter, чтобы продолжить..."
    done
}

hysteria_upgrade(){
    bash <(curl https://raw.githubusercontent.com/Asgaroth-SG/AsgarothGate/main/upgrade.sh)
}

warp_configure_handler() {
    local service_name="wg-quick@wgcf.service"

    if systemctl is-active --quiet "$service_name"; then
        echo -e "${cyan}=== Статус WARP ===${NC}"
        status_json=$(python3 $CLI_PATH warp-status)
        
        all_traffic=$(echo "$status_json" | grep -o '"all_traffic_via_warp": *[^,}]*' | cut -d':' -f2 | tr -d ' "')
        popular_sites=$(echo "$status_json" | grep -o '"popular_sites_via_warp": *[^,}]*' | cut -d':' -f2 | tr -d ' "')
        domestic_sites_via_warp=$(echo "$status_json" | grep -o '"domestic_sites_via_warp": *[^,}]*' | cut -d':' -f2 | tr -d ' "')
        block_adult=$(echo "$status_json" | grep -o '"block_adult_content": *[^,}]*' | cut -d':' -f2 | tr -d ' "')
        
        display_status() {
            local label="$1"
            local status_val="$2"
            if [ "$status_val" = "true" ]; then
                echo -e "  ${green}✓${NC} $label: ${green}Включено${NC}"
            else
                echo -e "  ${red}✗${NC} $label: ${red}Отключено${NC}"
            fi
        }
        
        display_status "Весь трафик через WARP" "$all_traffic"
        display_status "Популярные сайты через WARP" "$popular_sites"
        display_status "Локальные сайты (WARP/Сброс)" "$domestic_sites_via_warp"
        display_status "Блокировка контента 18+" "$block_adult"
        
        echo -e "${cyan}==================${NC}"
        echo
        
        echo "Настройка параметров WARP (Переключатели):"
        echo "1. Весь трафик через WARP"
        echo "2. Популярные сайты через WARP"
        echo "3. Локальные сайты (WARP/Reject)"
        echo "4. Блокировка контента 18+"
        echo "5. Профиль статуса WARP (IP и т.д.)"
        echo "6. Изменить IP адрес WARP"
        echo "7. Переключиться на WARP Plus"
        echo "8. Переключиться на WARP"
        echo "0. Отмена"

        read -p "Выберите опцию для переключения: " option

        case $option in
            1) 
                target_state=$([ "$all_traffic" = "true" ] && echo "off" || echo "on")
                python3 $CLI_PATH configure-warp --set-all "$target_state" ;;
            2) 
                target_state=$([ "$popular_sites" = "true" ] && echo "off" || echo "on")
                python3 $CLI_PATH configure-warp --set-popular-sites "$target_state" ;;
            3) 
                target_state=$([ "$domestic_sites_via_warp" = "true" ] && echo "off" || echo "on")
                python3 $CLI_PATH configure-warp --set-domestic-sites "$target_state" ;;
            4) 
                target_state=$([ "$block_adult" = "true" ] && echo "off" || echo "on")
                python3 $CLI_PATH configure-warp --set-block-adult-sites "$target_state" ;;
            5) 
                current_ip=$(python3 $CLI_PATH warp-status | grep -o '"ip": *"[^"]*"' | cut -d':' -f2- | tr -d '" ')
                if [ -z "$current_ip" ]; then 
                    current_ip=$(curl -s --interface wgcf --connect-timeout 1 http://v4.ident.me || echo "N/A")
                fi
                cd /etc/warp/ && wgcf status
                echo
                echo -e "${yellow}IP адрес WARP:${NC} ${cyan}${current_ip}${NC}" 
                ;;
            6)
                old_ip=$(curl -s --interface wgcf --connect-timeout 1 http://v4.ident.me || echo "N/A")
                echo -e "${yellow}Текущий IP:${NC} ${cyan}$old_ip${NC}"
                echo "Перезапуск $service_name для попытки смены IP..."
                systemctl restart "$service_name"
                
                echo -n "Ожидание перезапуска сервиса"
                for i in {1..5}; do
                    echo -n "."
                    sleep 1
                done
                echo
                
                new_ip=$(curl -s --interface wgcf --connect-timeout 1 http://v4.ident.me || echo "N/A")
                echo -e "${yellow}Новый IP:${NC} ${green}$new_ip${NC}"
                
                if [ "$old_ip" != "N/A" ] && [ "$new_ip" != "N/A" ] && [ "$old_ip" != "$new_ip" ]; then
                    echo -e "${green}✓ IP адрес успешно изменен${NC}"
                elif [ "$old_ip" = "$new_ip" ] && [ "$old_ip" != "N/A" ]; then
                    echo -e "${yellow}⚠ IP адрес остался прежним${NC}"
                else
                    echo -e "${red}✗ Не удалось проверить смену IP.${NC}"
                fi
                ;;
            7)
                echo -e "${yellow}Переключение на WARP Plus...${NC}"
                read -p "Введите ваш лицензионный ключ WARP Plus: " warp_key
                
                if [ -z "$warp_key" ]; then
                    echo -e "${red}Ошибка: Требуется ключ WARP Plus.${NC}"
                else
                    echo "Остановка сервиса WARP..."
                    systemctl stop "$service_name" 2>/dev/null
                    
                    cd /etc/warp/ || { echo -e "${red}Не удалось перейти в директорию /etc/warp/${NC}"; return 1; }
                    
                    echo "Обновление конфигурации WARP Plus..."
                    WGCF_LICENSE_KEY="$warp_key" wgcf update
                    
                    if [ $? -eq 0 ]; then
                        echo "Запуск сервиса WARP..."
                        systemctl start "$service_name"
                        echo -e "${green}✓ Успешное переключение на WARP Plus${NC}"
                        python3 "$CLI_PATH" restart-hysteria2 > /dev/null 2>&1
                    else
                        echo -e "${red}✗ Не удалось обновить конфигурацию WARP Plus${NC}"
                        systemctl start "$service_name"
                    fi
                fi
                ;;
            8)
                echo -e "${yellow}Переключение на WARP...${NC}"
                echo "Будет создан новый аккаунт WARP. Продолжить? (y/N)"
                read -p "" confirm
                
                if [[ "$confirm" =~ ^[Yy]$ ]]; then
                    echo "Остановка сервиса WARP..."
                    systemctl stop "$service_name" 2>/dev/null
                    
                    cd /etc/warp/ || { echo -e "${red}Не удалось перейти в директорию /etc/warp/${NC}"; return 1; }
                    
                    echo "Создание нового аккаунта WARP..."
                    rm -f wgcf-account.toml
                    yes | wgcf register
                    
                    if [ $? -eq 0 ]; then
                        echo "Запуск сервиса WARP..."
                        systemctl start "$service_name"
                        echo -e "${green}✓ Успешное переключение на WARP с новым аккаунтом${NC}"
                        python3 "$CLI_PATH" restart-hysteria2 > /dev/null 2>&1
                    else
                        echo -e "${red}✗ Не удалось зарегистрировать новый аккаунт WARP${NC}"
                        systemctl start "$service_name"
                    fi
                else
                    echo -e "${yellow}Операция отменена${NC}"
                fi
                ;;
            0) echo "Настройка WARP отменена." ;;
            *) echo -e "${red}Неверная опция. Пожалуйста, попробуйте снова.${NC}" ;;
        esac

    else
        echo -e "${red}$service_name не активен. Пожалуйста, запустите сервис перед настройкой WARP.${NC}"
    fi
}

telegram_bot_handler() {
    while true; do
        echo -e "${cyan}1.${NC} Запустить сервис Telegram бота"
        echo -e "${red}2.${NC} Остановить сервис Telegram бота"
        echo "0. Назад"
        read -p "Выберите опцию: " option

        case $option in
            1)
                if systemctl is-active --quiet hysteria-telegram-bot.service; then
                    echo "Сервис hysteria-telegram-bot.service уже активен."
                else
                    while true; do
                        read -e -p "Введите токен Telegram бота: " token
                        if [ -z "$token" ]; then
                            echo "Токен не может быть пустым. Попробуйте снова."
                        else
                            break
                        fi
                    done

                    while true; do
                        read -e -p "Введите ID админов (через запятую): " admin_ids
                        if [[ ! "$admin_ids" =~ ^[0-9,]+$ ]]; then
                            echo "ID админов могут содержать только цифры и запятые. Попробуйте снова."
                        elif [ -z "$admin_ids" ]; then
                            echo "ID админов не могут быть пустыми. Попробуйте снова."
                        else
                            break
                        fi
                    done

                    python3 $CLI_PATH telegram -a start -t "$token" -aid "$admin_ids"
                fi
                ;;
            2)
                python3 $CLI_PATH telegram -a stop
                ;;
            0)
                break
                ;;
            *)
                echo "Неверная опция. Пожалуйста, попробуйте снова."
                ;;
        esac
    done
}

singbox_handler() {
    echo -e "${red} Устарело (Deprecated)${NC}"
}

normalsub_handler() {
    while true; do
        echo -e "${cyan}1.${NC} Запустить сервис Подписок"
        echo -e "${red}2.${NC} Остановить сервис Подписок"
        echo -e "${yellow}3.${NC} Изменить SUBPATH"
        echo "0. Назад"
        read -p "Выберите опцию: " option

        case $option in
            1)
                if systemctl is-active --quiet hysteria-normal-sub.service; then
                    echo "Сервис hysteria-normal-sub.service уже активен."
                else
                    while true; do
                        read -e -p "Введите доменное имя для SSL сертификата: " domain
                        if [ -z "$domain" ]; then
                            echo "Доменное имя не может быть пустым. Попробуйте снова."
                        else
                            break
                        fi
                    done

                    while true; do
                        read -e -p "Введите номер порта для сервиса: " port
                        if [ -z "$port" ]; then
                            echo "Номер порта не может быть пустым. Попробуйте снова."
                        elif ! [[ "$port" =~ ^[0-9]+$ ]]; then
                            echo "Порт должен быть числом. Попробуйте снова."
                        else
                            break
                        fi
                    done

                    python3 $CLI_PATH normal-sub -a start -d "$domain" -p "$port"
                fi
                ;;
            2)
                if ! systemctl is-active --quiet hysteria-normal-sub.service; then
                    echo "Сервис hysteria-normal-sub.service уже неактивен."
                else
                    python3 $CLI_PATH normal-sub -a stop
                fi
                ;;
            3)
                if ! systemctl is-active --quiet hysteria-normal-sub.service; then
                    echo "Ошибка: Сервис hysteria-normal-sub.service не активен. Сначала запустите сервис."
                    continue
                fi

                while true; do
                    read -e -p "Введите новый SUBPATH (должен содержать заглавные, строчные буквы и цифры): " subpath
                    if [[ -z "$subpath" ]]; then
                        echo "Ошибка: SUBPATH не может быть пустым. Попробуйте снова."
                    elif ! [[ "$subpath" =~ [A-Z] ]] || ! [[ "$subpath" =~ [a-z] ]] || ! [[ "$subpath" =~ [0-9] ]]; then
                        echo "Ошибка: SUBPATH должен содержать хотя бы одну заглавную букву, одну строчную букву и одну цифру."
                    else
                        python3 $CLI_PATH normal-sub -a edit_subpath -sp "$subpath"
                        # echo "SUBPATH Успешно обновлен!"
                        break
                    fi
                done
                ;;
            0)
                break
                ;;
            *)
                echo "Неверная опция. Пожалуйста, попробуйте снова."
                ;;
        esac
    done
}

webpanel_handler() {
    service_status=$(python3 "$CLI_PATH" get-webpanel-services-status)
    echo -e "${cyan}Статус сервисов:${NC}"
    echo "$service_status"
    echo ""

    while true; do
        echo -e "${cyan}1.${NC} Запустить сервис WebPanel"
        echo -e "${red}2.${NC} Остановить сервис WebPanel"
        echo -e "${cyan}3.${NC} Получить URL WebPanel"
        echo -e "${cyan}4.${NC} Показать API токен"
        echo -e "${yellow}5.${NC} Сбросить учетные данные WebPanel"
        echo -e "${yellow}6.${NC} Изменить Домен/Порт"
        echo -e "${yellow}7.${NC} Изменить корневой путь (Root Path)"
        echo -e "${yellow}8.${NC} Изменить время жизни сессии"
        echo "0. Назад"
        read -p "Выберите опцию: " option

        case $option in
            1)
                if systemctl is-active --quiet hysteria-webpanel.service; then
                    echo "Сервис hysteria-webpanel.service уже активен."
                else
                    while true; do
                        read -e -p "Введите доменное имя для SSL сертификата: " domain
                        if [ -z "$domain" ]; then
                            echo "Доменное имя не может быть пустым. Попробуйте снова."
                        else
                            break
                        fi
                    done

                    while true; do
                        read -e -p "Введите номер порта для сервиса: " port
                        if [ -z "$port" ]; then
                            echo "Номер порта не может быть пустым. Попробуйте снова."
                        elif ! [[ "$port" =~ ^[0-9]+$ ]]; then
                            echo "Порт должен быть числом. Попробуйте снова."
                        else
                            break
                        fi
                    done

                    while true; do
                        read -e -p "Введите имя администратора: " admin_username
                        if [ -z "$admin_username" ]; then
                            echo "Имя администратора не может быть пустым. Попробуйте снова."
                        else
                            break
                        fi
                    done

                    while true; do
                        read -e -p "Введите пароль администратора: " admin_password
                        if [ -z "$admin_password" ]; then
                            echo "Пароль администратора не может быть пустым. Попробуйте снова."
                        else
                            break
                        fi
                    done

                    python3 $CLI_PATH webpanel -a start -d "$domain" -p "$port" -au "$admin_username" -ap "$admin_password"
                fi
                ;;
            2)
                if ! systemctl is-active --quiet hysteria-webpanel.service; then
                    echo "Сервис hysteria-webpanel.service уже неактивен."
                else
                    python3 $CLI_PATH webpanel -a stop
                fi
                ;;
            3)
                url=$(python3 $CLI_PATH get-webpanel-url)
                echo "-------------------------------"
                echo "$url"
                echo "-------------------------------"
                ;;
            4)
                api_token=$(python3 $CLI_PATH get-webpanel-api-token)
                echo "-------------------------------"
                echo "$api_token"
                echo "-------------------------------"
                ;;
            5)
                if ! systemctl is-active --quiet hysteria-webpanel.service; then
                     echo -e "${red}Сервис WebPanel не запущен. Невозможно сбросить учетные данные.${NC}"
                else
                    read -e -p "Введите новое имя админа (оставьте пустым, чтобы оставить текущее): " new_username
                    read -e -p "Введите новый пароль (оставьте пустым, чтобы оставить текущий): " new_password
                    echo

                    if [ -z "$new_username" ] && [ -z "$new_password" ]; then
                        echo -e "${yellow}Изменения не указаны. Прерывание.${NC}"
                    else
                        local cmd_args=("-u" "$new_username")
                        if [ -n "$new_password" ]; then
                             cmd_args+=("-p" "$new_password")
                        fi
                        
                        if [ -z "$new_username" ]; then
                             cmd_args=()
                             if [ -n "$new_password" ]; then
                                cmd_args+=("-p" "$new_password")
                             fi
                        fi
                        
                        echo "Попытка сброса учетных данных..."
                        python3 "$CLI_PATH" reset-webpanel-creds "${cmd_args[@]}"
                    fi
                fi
                ;;
            6) 
                if ! systemctl is-active --quiet hysteria-webpanel.service; then
                     echo -e "${red}Сервис WebPanel не запущен. Невозможно выполнить это действие.${NC}"
                else
                    read -e -p "Введите новый домен (оставьте пустым, чтобы оставить текущий): " new_domain
                    read -e -p "Введите новый порт (оставьте пустым, чтобы оставить текущий): " new_port

                    if [ -z "$new_domain" ] && [ -z "$new_port" ]; then
                        echo -e "${yellow}Изменения не указаны. Прерывание.${NC}"
                    else
                        local cmd_args=()
                        if [ -n "$new_domain" ]; then
                             cmd_args+=("--domain" "$new_domain")
                        fi
                        if [ -n "$new_port" ]; then
                             cmd_args+=("--port" "$new_port")
                        fi
                        echo "Попытка изменения домена/порта..."
                        python3 "$CLI_PATH" change-webpanel-domain-port "${cmd_args[@]}"
                    fi
                fi
                ;;
            7) 
                if ! systemctl is-active --quiet hysteria-webpanel.service; then
                     echo -e "${red}Сервис WebPanel не запущен. Невозможно выполнить это действие.${NC}"
                else
                    read -e -p "Введите новый корневой путь (оставьте пустым для случайного): " new_root_path
                    local cmd_args=()
                    if [ -n "$new_root_path" ]; then
                        cmd_args+=("--path" "$new_root_path")
                    fi
                    echo "Попытка изменения корневого пути..."
                    python3 "$CLI_PATH" change-webpanel-root "${cmd_args[@]}"
                fi
                ;;
            8) 
                if ! systemctl is-active --quiet hysteria-webpanel.service; then
                     echo -e "${red}Сервис WebPanel не запущен. Невозможно выполнить это действие.${NC}"
                else
                    while true; do
                        read -e -p "Введите новое время жизни сессии в минутах: " new_minutes
                        if [[ "$new_minutes" =~ ^[0-9]+$ ]]; then
                            break
                        else
                            echo -e "${red}Ошибка:${NC} Пожалуйста, введите корректное число."
                        fi
                    done
                    echo "Попытка изменения времени жизни сессии..."
                    python3 "$CLI_PATH" change-webpanel-exp --minutes "$new_minutes"
                fi
                ;;
            0)
                break
                ;;
            *)
                echo "Неверная опция. Пожалуйста, попробуйте снова."
                ;;
        esac
    done
}


obfs_handler() {
    while true; do
        echo -e "${cyan}1.${NC} Удалить обфускацию (Obfs)"
        echo -e "${red}2.${NC} Сгенерировать новую обфускацию (Obfs)"
        echo "0. Назад"
        read -p "Выберите опцию: " option

        case $option in
            1)
            python3 $CLI_PATH manage_obfs -r
                ;;
            2)
            python3 $CLI_PATH manage_obfs -g
                ;;
            0)
                break
                ;;
            *)
                echo "Неверная опция. Пожалуйста, попробуйте снова."
                ;;
        esac
    done
}

geo_update_handler() {
    echo "Настройка обновления Geo:"
    echo "1. Обновить Geo файлы для Ирана"
    echo "2. Обновить Geo файлы для Китая"
    echo "3. Обновить Geo файлы для России"
    echo "4. Проверить текущие Geo файлы"
    echo "0. Отмена"

    read -p "Выберите опцию: " option

    case $option in
        1)
            echo "Обновление Geo файлов для Ирана..."
            python3 $CLI_PATH update-geo --country iran
            ;;
        2)
            echo "Обновление Geo файлов для Китая..."
            python3 $CLI_PATH update-geo --country china
            ;;
        3)
            echo "Обновление Geo файлов для России..."
            python3 $CLI_PATH update-geo --country russia
            ;;
        4)
            echo "Информация о текущих Geo файлах:"
            echo "--------------------------"
            if [ -f "/etc/hysteria/geosite.dat" ]; then
                echo "Файл GeoSite:"
                ls -lh /etc/hysteria/geosite.dat
                echo "Последнее изменение: $(stat -c %y /etc/hysteria/geosite.dat)"
            else
                echo "Файл GeoSite не найден!"
            fi
            echo
            if [ -f "/etc/hysteria/geoip.dat" ]; then
                echo "Файл GeoIP:"
                ls -lh /etc/hysteria/geoip.dat
                echo "Последнее изменение: $(stat -c %y /etc/hysteria/geoip.dat)"
            else
                echo "Файл GeoIP не найден!"
            fi
            ;;
        0)
            echo "Настройка обновления Geo отменена."
            ;;
        *)
            echo "Неверная опция. Пожалуйста, попробуйте снова."
            ;;
    esac
}

masquerade_handler() {
    while true; do
        echo -e "${cyan}1.${NC} Включить маскировку (Masquerade)"
        echo -e "${red}2.${NC} Удалить маскировку (Masquerade)"
        echo "0. Назад"
        read -p "Выберите опцию: " option

        case $option in
            1)
                if systemctl is-active --quiet hysteria-webpanel.service; then
                    echo -e "${red}Ошибка:${NC} Маскировка не может быть включена, так как работает hysteria-webpanel.service."
                else
                    read -p "Введите URL для rewriteHost: " url
                    if [ -z "$url" ]; then
                        echo "Ошибка: URL не может быть пустым. Попробуйте снова."
                    else
                        python3 $CLI_PATH masquerade -e "$url"
                    fi
                fi
                ;;
            2)
                python3 $CLI_PATH masquerade -r
                ;;
            0)
                break
                ;;
            *)
                echo "Неверная опция. Пожалуйста, попробуйте снова."
                ;;
        esac
    done
}

ip_limit_handler() {
    while true; do
        echo -e "${cyan}1.${NC} Запустить сервис Limit IP"
        echo -e "${red}2.${NC} Остановить сервис Limit IP"
        echo -e "${yellow}3.${NC} Изменить конфигурацию Limit IP"
        echo "0. Назад"
        read -p "Выберите опцию: " option

        case $option in
            1)
                if systemctl is-active --quiet hysteria-ip-limit.service; then
                    echo "Сервис hysteria-ip-limit.service уже активен."
                else
                    while true; do
                        read -e -p "Введите длительность блокировки (сек, по умолчанию: 60): " block_duration
                        block_duration=${block_duration:-60}
                        if ! [[ "$block_duration" =~ ^[0-9]+$ ]]; then
                            echo "Неверная длительность блокировки. Пожалуйста, введите число."
                        else
                            break
                        fi
                    done

                    while true; do
                        read -e -p "Введите макс. кол-во IP на пользователя (по умолчанию: 1): " max_ips
                        max_ips=${max_ips:-1} 
                        if ! [[ "$max_ips" =~ ^[0-9]+$ ]]; then
                            echo "Неверное макс. кол-во IP. Пожалуйста, введите число."
                        else
                            break
                        fi
                    done
                    python3 $CLI_PATH config-ip-limit --block-duration "$block_duration" --max-ips "$max_ips"
                    python3 $CLI_PATH start-ip-limit
                fi
                ;;
            2)
                if ! systemctl is-active --quiet hysteria-ip-limit.service; then
                    echo "Сервис hysteria-ip-limit.service уже неактивен."
                else
                    python3 $CLI_PATH stop-ip-limit
                fi
                ;;
            3)
                block_duration=""
                max_ips=""
                updated=false

                while true; do
                    read -e -p "Введите новую длительность блокировки (сек, сейчас: $(grep '^BLOCK_DURATION=' /etc/hysteria/.configs.env | cut -d'=' -f2), оставьте пустым, чтобы сохранить): " input_block_duration
                    if [[ -n "$input_block_duration" ]] && ! [[ "$input_block_duration" =~ ^[0-9]+$ ]]; then
                        echo "Неверная длительность блокировки. Пожалуйста, введите число или оставьте пустым."
                    else
                        if [[ -n "$input_block_duration" ]]; then
                            block_duration="$input_block_duration"
                            updated=true
                        fi
                        break
                    fi
                done

                while true; do
                    read -e -p "Введите новое макс. кол-во IP на пользователя (сейчас: $(grep '^MAX_IPS=' /etc/hysteria/.configs.env | cut -d'=' -f2), оставьте пустым, чтобы сохранить): " input_max_ips
                    if [[ -n "$input_max_ips" ]] && ! [[ "$input_max_ips" =~ ^[0-9]+$ ]]; then
                        echo "Неверное макс. кол-во IP. Пожалуйста, введите число или оставьте пустым."
                    else
                        if [[ -n "$input_max_ips" ]]; then
                            max_ips="$input_max_ips"
                            updated=true
                        fi
                        break
                    fi
                done

                if [[ "$updated" == "true" ]]; then
                    python3 $CLI_PATH config-ip-limit --block-duration "$block_duration" --max-ips "$max_ips"
                else
                    echo "Изменения в конфигурацию Limit IP не внесены."
                fi
                ;;
            0)
                break
                ;;
            *)
                echo "Неверная опция. Пожалуйста, попробуйте снова."
                ;;
        esac
    done
}

display_main_menu() {
    clear
    tput setaf 7 ; tput setab 4 ; tput bold
    echo -e "◇─────────────── Добро пожаловать в Asgaroth Gate ──────────────◇"
    tput sgr0
    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"

    printf "\033[0;32m• ОС:  \033[0m%-25s \033[0;32m• АРХ:   \033[0m%-25s\n" "$OS" "$ARCH"
    printf "\033[0;32m• ISP: \033[0m%-25s \033[0;32m• ЦП:    \033[0m%-25s\n" "$ISP" "$CPU"
    printf "\033[0;32m• IP:  \033[0m%-25s \033[0;32m• ОЗУ:   \033[0m%-25s\n" "$IP" "$RAM"

    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"
        check_core_version
        check_version
    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"
    echo -e "${yellow}                   ☼ Статус Сервисов ☼                   ${NC}"
    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"

        check_services
        
    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"
    echo -e "${yellow}                   ☼ Главное Меню ☼                   ${NC}"

    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"
    echo -e "${green}[1] ${NC}↝ Меню Hysteria"
    echo -e "${cyan}[2] ${NC}↝ Расширенное Меню"
    echo -e "${cyan}[3] ${NC}↝ Обновить Панель"
    echo -e "${red}[0] ${NC}↝ Выход"
    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"
    echo -ne "${yellow}➜ Введите опцию: ${NC}"
}

main_menu() {
    clear
    local choice
    while true; do
        get_system_info
        display_main_menu
        if ! read -r choice; then
            echo "Ввод недоступен. Выход."
            exit 1
        fi
        case $choice in
            1) hysteria2_menu ;;
            2) advance_menu ;;
            3) hysteria_upgrade ;;
            0) exit 0 ;;
            *) echo "Неверная опция. Пожалуйста, попробуйте снова." ;;
        esac
        echo
        if ! read -rp "Нажмите Enter, чтобы продолжить..."; then
            exit 1
        fi
    done
}


display_hysteria2_menu() {
    clear
    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"

    echo -e "${yellow}                   ☼ Меню ☼                   ${NC}"

    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"

    echo -e "${green}[1] ${NC}↝ Установить и настроить Hysteria"
    echo -e "${cyan}[2] ${NC}↝ Добавить пользователя"
    echo -e "${cyan}[3] ${NC}↝ Редактировать пользователя"
    echo -e "${cyan}[4] ${NC}↝ Сбросить пользователя"
    echo -e "${cyan}[5] ${NC}↝ Удалить пользователя"
    echo -e "${cyan}[6] ${NC}↝ Получить данные пользователя"
    echo -e "${cyan}[7] ${NC}↝ Список пользователей"
    echo -e "${cyan}[8] ${NC}↝ Проверить статус трафика"
    echo -e "${cyan}[9] ${NC}↝ Показать URI пользователя"

    echo -e "${red}[0] ${NC}↝ Назад в главное меню"

    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"

    echo -ne "${yellow}➜ Введите опцию: ${NC}"
}

hysteria2_menu() {
    clear
    local choice
    while true; do
        get_system_info
        display_hysteria2_menu
        if ! read -r choice; then
            echo "Ввод недоступен. Выход."
            exit 1
        fi
        case $choice in
            1) hysteria2_install_handler ;;
            2) hysteria2_add_user_handler ;;
            3) hysteria2_edit_user_handler ;;
            4) hysteria2_reset_user_handler ;;
            5) hysteria2_remove_user_handler  ;;
            6) hysteria2_get_user_handler ;;
            7) hysteria2_list_users_handler ;;
            8) python3 $CLI_PATH traffic-status ;;
            9) hysteria2_show_user_uri_handler ;;
            0) return ;;
            *) echo "Неверная опция. Пожалуйста, попробуйте снова." ;;
        esac
        echo
        if ! read -rp "Нажмите Enter, чтобы продолжить..."; then
            exit 1
        fi
    done
}

display_advance_menu() {
    clear
    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"
    echo -e "${yellow}                   ☼ Расширенное Меню ☼                   ${NC}"
    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"
    echo -e "${green}[1] ${NC}↝ Установить TCP Brutal"
    echo -e "${green}[2] ${NC}↝ Установить WARP"
    echo -e "${cyan}[3] ${NC}↝ Настроить WARP"
    echo -e "${red}[4] ${NC}↝ Удалить WARP"
    echo -e "${green}[5] ${NC}↝ Telegram Бот"
    echo -e "${green}[6] ${NC}↝ SingBox Подписка(${red}Устарело${NC})"
    echo -e "${green}[7] ${NC}↝ Подписки"
    echo -e "${green}[8] ${NC}↝ Web Panel"
    echo -e "${cyan}[9] ${NC}↝ Изменить порт Hysteria"
    echo -e "${cyan}[10] ${NC}↝ Изменить SNI Hysteria"
    echo -e "${cyan}[11] ${NC}↝ Управление OBFS"
    echo -e "${cyan}[12] ${NC}↝ Изменить IP"
    echo -e "${cyan}[13] ${NC}↝ Обновить Geo-файлы"
    echo -e "${cyan}[14] ${NC}↝ Управление маскировкой (Masquerade)"
    echo -e "${cyan}[15] ${NC}↝ Перезапустить Hysteria"
    echo -e "${cyan}[16] ${NC}↝ Обновить ядро Hysteria"
    echo -e "${cyan}[17] ${NC}↝ Limit IP"
	echo -e "${green}[18] ${NC}↝ Cloudflare SSL"
    echo -e "${red}[19] ${NC}↝ Удалить Hysteria"
	echo -e "${red}[20] ${NC}↝ Полное удаление"
    echo -e "${red}[0] ${NC}↝ Назад в главное меню"
    echo -e "${LPurple}◇──────────────────────────────────────────────────────────────────────◇${NC}"
    echo -ne "${yellow}➜ Введите опцию: ${NC}"
}

advance_menu() {
    clear
    local choice
    while true; do
        display_advance_menu
        if ! read -r choice; then
            echo "Ввод недоступен. Выход."
            exit 1
        fi
        case $choice in
            1) python3 $CLI_PATH install-tcp-brutal ;;
            2) python3 $CLI_PATH install-warp ;;
            3) warp_configure_handler ;;
            4) python3 $CLI_PATH uninstall-warp ;;
            5) telegram_bot_handler ;;
            6) singbox_handler ;;
            7) normalsub_handler ;;
            8) webpanel_handler ;;
            9) hysteria2_change_port_handler ;;
            10) hysteria2_change_sni_handler ;;
            11) obfs_handler ;;
            12) edit_ips ;;
            13) geo_update_handler ;;
            14) masquerade_handler ;;
            15) python3 $CLI_PATH restart-hysteria2 ;;
            16) python3 $CLI_PATH update-hysteria2 ;;
            17) ip_limit_handler ;;
			18) bash /etc/hysteria/core/scripts/cloudflare_setup.sh ;;
            19) python3 $CLI_PATH uninstall-hysteria2 ;;
			20) bash /etc/hysteria/core/scripts/cleanup.sh 
			exit 0 ;;
            0) return ;;
            *) echo "Неверная опция. Пожалуйста, попробуйте снова." ;;
        esac
        echo
        if ! read -rp "Нажмите Enter, чтобы продолжить..."; then
            exit 1
        fi
    done
}

define_colors
main_menu