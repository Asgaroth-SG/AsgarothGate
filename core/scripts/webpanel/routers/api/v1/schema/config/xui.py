from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal, Dict, Any


class XUIServerConfig(BaseModel):
    """Конфигурация одного сервера X-UI"""
    name: str = Field(..., description="Имя/алиас сервера")
    host: str = Field(..., description="Адрес сервера 3X-UI (http:// или https://)")
    base_path: str = Field("/", description="Базовый путь панели")
    timeout: int = Field(10, ge=1, le=60, description="Таймаут запросов в секундах")
    max_retries: int = Field(3, ge=1, le=10, description="Максимальное количество попыток")
    verify_tls: bool = Field(True, description="Проверять TLS сертификат")
    plans: List[Literal["standard", "premium"]] = Field(
        ["standard", "premium"],
        description="Список планов для этого сервера"
    )
    inbound_filter: Optional[Dict[str, Any]] = Field(
        None,
        description="Фильтр inbounds для этого сервера"
    )
    enabled: bool = Field(True, description="Включен ли сервер")
    
    # Авторизация через username/password ИЛИ token (взаимоисключающие)
    auth_type: Literal["username", "token"] = Field("username", description="Тип авторизации")
    username: Optional[str] = Field(None, description="Имя пользователя (если auth_type=username)")
    password: Optional[str] = Field(None, description="Пароль или token")
    
    # Публичные параметры для переписывания ссылок в normal sub
    public_host: Optional[str] = Field(
        None,
        description="Публичный домен reverse proxy для ссылок (если отличается от host)"
    )
    public_port: int = Field(
        443,
        ge=1,
        le=65535,
        description="Публичный порт reverse proxy (по умолчанию 443)"
    )
    link_host_rewrite_from: Optional[str] = Field(
        "127.0.0.1",
        description="Внутренний хост для переписывания (по умолчанию 127.0.0.1)"
    )
    
    @field_validator('host')
    @classmethod
    def validate_host(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('Host must start with http:// or https://')
        return v
    
    @field_validator('plans')
    @classmethod
    def validate_plans(cls, v):
        if not v:
            raise ValueError('Plans list cannot be empty')
        return v


class XUIConfigInputBody(BaseModel):
    """Тело запроса для обновления конфигурации X-UI"""
    enabled: bool = Field(..., description="Включить/выключить синхронизацию")
    mode: Literal["single-xui", "multi-xui"] = Field(
        "multi-xui",
        description="Режим работы"
    )
    xui_servers: List[XUIServerConfig] = Field(
        default_factory=list,
        description="Список серверов X-UI"
    )
    inbound_filter: Optional[Dict[str, Any]] = Field(
        None,
        description="Глобальный фильтр inbounds"
    )
    sync_interval: Optional[int] = Field(
        60,
        ge=1,
        description="Интервал синхронизации в минутах"
    )
    
    @field_validator('xui_servers')
    @classmethod
    def validate_servers(cls, v):
        # Разрешаем пустой список серверов (для сохранения только настроек синхронизации)
        if not v:
            return v
        # Валидируем каждый сервер, если список не пустой
        for server in v:
            # Проверяем авторизацию в зависимости от auth_type
            if server.auth_type == "username":
                if not server.username or not server.password:
                    raise ValueError(
                        f'Server {server.host}: Username and password are required when auth_type=username'
                    )
            elif server.auth_type == "token":
                if not server.password:
                    raise ValueError(
                        f'Server {server.host}: Token (password) is required when auth_type=token'
                    )
        return v
    
    @field_validator('sync_interval')
    @classmethod
    def validate_sync_interval(cls, v, info):
        # sync_interval опционален, но если передан - должен быть >= 1
        if v is not None and v < 1:
            raise ValueError('sync_interval must be at least 1 minute')
        return v


class XUIConfigResponse(BaseModel):
    """Ответ с текущей конфигурацией X-UI"""
    enabled: bool
    mode: str
    xui_servers: List[Dict[str, Any]]
    inbound_filter: Optional[Dict[str, Any]] = None
    sync_interval: Optional[int] = None


class XUITestConnectionBody(BaseModel):
    """Тело запроса для тестирования подключения"""
    host: str
    base_path: str = "/"
    username: str = Field(..., description="Имя пользователя")
    password: str = Field(..., description="Пароль")


class XUITestConnectionResponse(BaseModel):
    """Ответ теста подключения"""
    success: bool
    message: str
    inbounds_count: Optional[int] = None
    inbounds: Optional[List[Dict[str, Any]]] = None


class XUISyncStatusResponse(BaseModel):
    """Статус синхронизации пользователей"""
    total_users: int
    synced_users: int
    failed_users: int
    sync_statuses: Dict[str, str]  # username -> status
    last_sync_time: Optional[str] = None  # ISO format datetime
    last_sync_status: Optional[str] = None  # success, failed, unknown
    last_sync_stats: Optional[Dict[str, int]] = None  # {synced: int, failed: int}


class XUISyncUserBody(BaseModel):
    """Тело запроса для синхронизации пользователя"""
    username: str


class XUIServerHealthResponse(BaseModel):
    """Ответ проверки здоровья сервера"""
    healthy: bool
    message: str
    inbounds_count: Optional[int] = None
