# Логирование X-UI интеграции

## Расположение логов

Все логи X-UI интеграции записываются в файл:

```
/var/log/hysteria_xui.log
```

## Что логируется

### Уровни логирования

- **DEBUG** - Детальная диагностическая информация (подключения, запросы, ответы)
- **INFO** - Важные события (успешные операции, инициализация)
- **WARNING** - Предупреждения (некритичные ошибки, отсутствие данных)
- **ERROR** - Ошибки (критичные проблемы, исключения)

### Что логируется

#### xui_client.py
- Инициализация клиента
- Авторизация (успешная и неуспешная)
- Получение списка inbounds
- Добавление/обновление/удаление клиентов
- Получение share links
- Ошибки подключения и API запросов

#### xui_sync.py
- Инициализация менеджера синхронизации
- Синхронизация пользователей (создание, обновление, удаление)
- Получение серверов для планов
- Генерация UUID для клиентов
- Получение VLESS URIs
- Ошибки синхронизации

#### sync_helper.py
- Вызовы синхронизации из CLI скриптов
- Результаты синхронизации
- Ошибки синхронизации

#### config.py
- Загрузка конфигурации
- Создание менеджера синхронизации
- Ошибки конфигурации

#### API endpoints (xui.py)
- Запросы к API (получение/обновление конфигурации)
- Тестирование подключений
- Синхронизация пользователей через API
- Ошибки API запросов

## Просмотр логов

### Просмотр всех логов X-UI
```bash
tail -f /var/log/hysteria_xui.log
```

### Просмотр последних 100 строк
```bash
tail -n 100 /var/log/hysteria_xui.log
```

### Поиск по логам
```bash
# Поиск ошибок
grep ERROR /var/log/hysteria_xui.log

# Поиск по имени пользователя
grep "username" /var/log/hysteria_xui.log

# Поиск по серверу
grep "gateway.asgaroth.ru" /var/log/hysteria_xui.log
```

### Просмотр логов в реальном времени с фильтрацией
```bash
# Только ошибки и предупреждения
tail -f /var/log/hysteria_xui.log | grep -E "(ERROR|WARNING)"

# Только операции синхронизации
tail -f /var/log/hysteria_xui.log | grep "sync"
```

## Логи веб-панели

Логи веб-панели (включая API endpoints) также доступны через systemd journal:

```bash
# Все логи веб-панели
journalctl -u hysteria-webpanel.service -f

# Последние 100 строк
journalctl -u hysteria-webpanel.service -n 100

# Логи за сегодня
journalctl -u hysteria-webpanel.service --since today
```

## Ротация логов

Рекомендуется настроить ротацию логов для предотвращения переполнения диска.

Создайте файл `/etc/logrotate.d/hysteria-xui`:

```
/var/log/hysteria_xui.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
```

Это будет:
- Ротировать логи ежедневно
- Хранить 7 последних файлов
- Сжимать старые логи
- Создавать новый файл с правами 0644

## Уровень логирования

По умолчанию используется уровень `DEBUG` для максимальной диагностики.

Если нужно уменьшить объем логов, можно изменить уровень в `core/scripts/xui/logging_config.py`:

```python
xui_logger.setLevel(logging.INFO)  # Только INFO и выше
```

## Примеры логов

### Успешная авторизация
```
2024-01-15 10:30:45 - xui.xui_client - INFO - Successfully authorized via py3xui on https://gateway.asgaroth.ru:5560/vpn
```

### Успешная синхронизация
```
2024-01-15 10:31:12 - xui.xui_sync - INFO - Added client abc123... to inbound 1 on server https://gateway.asgaroth.ru:5560
```

### Ошибка подключения
```
2024-01-15 10:32:00 - xui.xui_client - ERROR - Failed to list inbounds: Connection timeout
```

### Ошибка синхронизации
```
2024-01-15 10:33:15 - xui.xui_sync - ERROR - Failed to add client to inbound 1 on https://gateway.asgaroth.ru:5560: Client already exists
```
