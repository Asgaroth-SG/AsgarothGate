# X-UI/3X-UI Integration для AsgarothGate

Модуль интеграции с панелью X-UI/3X-UI для автоматической синхронизации VLESS-клиентов.

## Описание

Этот модуль позволяет автоматически синхронизировать пользователей Hysteria2 с X-UI/3X-UI панелью:
- При создании пользователя в Hysteria2 автоматически создается VLESS-клиент в X-UI
- При обновлении пользователя (лимиты, expiry) обновляется клиент в X-UI
- При удалении пользователя удаляется клиент из X-UI
- В ответе `/api/v1/users/{username}/uri` возвращаются персональные VLESS-ссылки для каждого пользователя

## Конфигурация

### Способ 1: JSON файл (рекомендуется)

Создайте файл `/etc/hysteria/xui_config.json`:

#### Вариант A: Авторизация через API токен

```json
{
  "enabled": true,
  "mode": "multi-xui",
  "xui_servers": [
    {
      "host": "https://gateway.asgaroth.ru:5560",
      "base_path": "/vpn",
      "api_token": "your_api_token_here",
      "auth_type": "token",
      "timeout": 10,
      "max_retries": 3,
      "plans": ["standard", "premium"],
      "inbound_filter": {
        "protocol": "vless"
      }
    }
  ],
  "inbound_filter": {
    "protocol": "vless"
  }
}
```

#### Вариант B: Авторизация через login endpoint

```json
{
  "enabled": true,
  "mode": "multi-xui",
  "xui_servers": [
    {
      "host": "https://gateway.asgaroth.ru:5560",
      "base_path": "/vpn",
      "username": "admin",
      "password": "your_password",
      "auth_type": "login",
      "plans": ["standard", "premium"]
    }
  ]
}
```

#### Вариант C: Basic Auth

```json
{
  "enabled": true,
  "mode": "multi-xui",
  "xui_servers": [
    {
      "host": "https://gateway.asgaroth.ru:5560",
      "base_path": "/vpn",
      "username": "admin",
      "password": "your_password",
      "auth_type": "basic",
      "plans": ["standard", "premium"]
    }
  ]
}
```

### Способ 2: Переменные окружения

Создайте файл `/etc/hysteria/.xui.env`:

```bash
XUI_ENABLED=true
XUI_MODE=multi-xui
XUI_HOST=https://gateway.asgaroth.ru:5560
XUI_BASE_PATH=/vpn
XUI_API_TOKEN=your_api_token_here
XUI_AUTH_TYPE=token
XUI_TIMEOUT=10
XUI_MAX_RETRIES=3
XUI_INBOUND_PROTOCOL=vless
```

Или для login авторизации:
```bash
XUI_ENABLED=true
XUI_MODE=multi-xui
XUI_HOST=https://gateway.asgaroth.ru:5560
XUI_BASE_PATH=/vpn
XUI_USERNAME=admin
XUI_PASSWORD=your_password
XUI_AUTH_TYPE=login
```

### Параметры конфигурации

- `enabled` (bool): Включить/выключить синхронизацию
- `mode` (str): Режим работы:
  - `single-xui`: Один сервер X-UI (устаревший, используйте `multi-xui`)
  - `multi-xui`: Несколько серверов X-UI (рекомендуется)
- `xui_servers` (list): Список серверов X-UI:
  - `host` (str): Адрес сервера (http://host:port или https://host:port)
  - `base_path` (str): Базовый путь панели (по умолчанию "/", например "/vpn")
  - `api_token` (str, опционально): API токен для авторизации без login
  - `username` (str, опционально): Имя пользователя X-UI (для login/Basic Auth)
  - `password` (str, опционально): Пароль X-UI (для login/Basic Auth)
  - `auth_type` (str): Тип авторизации: "auto", "token", "login", "basic" (по умолчанию "auto")
  - `timeout` (int): Таймаут запросов в секундах (по умолчанию 10)
  - `max_retries` (int): Максимальное количество попыток (по умолчанию 3)
  - `plans` (list): Список планов для этого сервера: ["standard"], ["premium"], ["standard", "premium"]
  - `inbound_filter` (dict, опционально): Фильтр inbounds для этого сервера
- `inbound_filter` (dict): Глобальный фильтр inbounds:
  - `protocol` (str): Протокол (например, "vless")
  - `tag` (str): Тег inbound
  - `remark` (str): Замечание/название inbound

### Multi-XUI режим с поддержкой планов

Для работы с несколькими серверами X-UI и разделения по планам (Premium/Standard):

```json
{
  "enabled": true,
  "mode": "multi-xui",
  "xui_servers": [
    {
      "host": "http://standard-server.example.com:54321",
      "username": "admin",
      "password": "password1",
      "base_path": "/",
      "plans": ["standard"],
      "inbound_filter": {
        "protocol": "vless",
        "remark": "VLESS-Standard"
      }
    },
    {
      "host": "http://premium-server.example.com:54321",
      "username": "admin",
      "password": "password2",
      "base_path": "/",
      "plans": ["premium"],
      "inbound_filter": {
        "protocol": "vless",
        "remark": "VLESS-Premium"
      }
    }
  ],
  "inbound_filter": {
    "protocol": "vless"
  }
}
```

**Параметр `plans`**:
- `["standard"]` - сервер только для Standard пользователей
- `["premium"]` - сервер только для Premium пользователей  
- `["standard", "premium"]` - сервер для всех пользователей (по умолчанию)
- Если не указано - сервер доступен для всех планов

Подробнее см. `PLANS_CONFIGURATION.md`

## Как это работает

### Создание пользователя

1. Пользователь создается в Hysteria2 через API или CLI с указанием плана (standard/premium)
2. Автоматически генерируется UUID для X-UI (детерминированный на основе имени пользователя)
3. Клиент добавляется во все подходящие inbounds на серверах X-UI, доступных для плана пользователя
4. Маппинг сохраняется в MongoDB (коллекция `xui_user_mapping`)

**Важно**: Если у пользователя план "standard", клиент добавляется только на серверы с `plans: ["standard"]` или `plans: ["standard", "premium"]`. Аналогично для "premium".

### Обновление пользователя

1. При обновлении лимитов/expiry в Hysteria2
2. Автоматически обновляется клиент в X-UI на всех серверах
3. Маппинг обновляется в БД

### Удаление пользователя

1. При удалении пользователя из Hysteria2
2. Клиент удаляется из всех inbounds на всех серверах X-UI
3. Маппинг удаляется из БД

### Получение VLESS URIs

При запросе `/api/v1/users/{username}/uri`:
1. Определяется план пользователя из БД
2. Проверяется наличие маппинга в БД
3. Для каждого сервера X-UI, доступного для плана пользователя, получаются inbounds
4. Для каждого inbound собирается VLESS URI из параметров
5. Возвращается список VLESS-ссылок в поле `vless_nodes` (только с серверов для плана пользователя)

## Структура ответа API

```json
{
  "username": "user1",
  "ipv4": "hy2://...",
  "ipv6": null,
  "nodes": [
    {
      "name": "Node1",
      "uri": "hy2://..."
    }
  ],
  "normal_sub": "https://...",
  "vless_nodes": [
    {
      "name": "Server1:VLESS",
      "uri": "vless://uuid@host:port?params#remark"
    },
    {
      "name": "Server2:VLESS",
      "uri": "vless://uuid@host:port?params#remark"
    }
  ]
}
```

## Обработка ошибок

- Если X-UI недоступен при создании пользователя, пользователь все равно создается в Hysteria2, но статус синхронизации помечается как `failed`
- При ошибках синхронизации в логах появляются предупреждения, но операции с пользователями не блокируются
- Маппинг сохраняется даже при частичных ошибках (например, клиент добавлен на один сервер, но не на другой)

## Безопасность

- Пароли X-UI не логируются
- Используются таймауты и ретраи для надежности
- Сессии X-UI кэшируются на 1 час
- При ошибках аутентификации выполняется повторный логин

## Отладка

Логи синхронизации можно найти в логах приложения. Для включения детального логирования установите уровень логирования на `DEBUG`.

## Требования

- Python 3.8+
- requests
- python-dotenv
- pymongo
- X-UI/3X-UI панель с доступным HTTP API

## Поддержка

При возникновении проблем проверьте:
1. Доступность X-UI панели
2. Корректность учетных данных
3. Наличие подходящих inbounds (VLESS протокол)
4. Логи приложения на наличие ошибок
