from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal, Dict, Any


class XUIServerConfig(BaseModel):
    """Конфигурация одного сервера X-UI"""
    host: str = Field(..., description="Адрес сервера 3X-UI (http:// или https://)")
    base_path: str = Field("/", description="Базовый путь панели")
    timeout: int = Field(10, ge=1, le=60, description="Таймаут запросов в секундах")
    max_retries: int = Field(3, ge=1, le=10, description="Максимальное количество попыток")
    plans: List[Literal["standard", "premium"]] = Field(
        ["standard", "premium"],
        description="Список планов для этого сервера"
    )
    inbound_filter: Optional[Dict[str, Any]] = Field(
        None,
        description="Фильтр inbounds для этого сервера"
    )
    
    # Авторизация (один из способов)
    api_token: Optional[str] = Field(None, description="API токен для авторизации")
    username: Optional[str] = Field(None, description="Имя пользователя (для login/Basic Auth)")
    password: Optional[str] = Field(None, description="Пароль (для login/Basic Auth)")
    auth_type: Literal["auto", "token", "login", "basic"] = Field(
        "auto",
        description="Тип авторизации"
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
        ...,
        min_length=1,
        description="Список серверов X-UI"
    )
    inbound_filter: Optional[Dict[str, Any]] = Field(
        None,
        description="Глобальный фильтр inbounds"
    )
    
    @field_validator('xui_servers')
    @classmethod
    def validate_servers(cls, v):
        if not v:
            raise ValueError('At least one X-UI server must be configured')
        for server in v:
            # Проверяем, что указан способ авторизации
            if not server.api_token and not (server.username and server.password):
                raise ValueError(
                    f'Server {server.host}: Either api_token or username+password must be provided'
                )
        return v


class XUIConfigResponse(BaseModel):
    """Ответ с текущей конфигурацией X-UI"""
    enabled: bool
    mode: str
    xui_servers: List[Dict[str, Any]]
    inbound_filter: Optional[Dict[str, Any]] = None


class XUITestConnectionBody(BaseModel):
    """Тело запроса для тестирования подключения"""
    host: str
    base_path: str = "/"
    api_token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    auth_type: Literal["auto", "token", "login", "basic"] = "auto"


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


class XUISyncUserBody(BaseModel):
    """Тело запроса для синхронизации пользователя"""
    username: str
