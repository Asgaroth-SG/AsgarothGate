import re
from typing import Optional, List
from pydantic import BaseModel, RootModel, Field, field_validator


class UserInfoResponse(BaseModel):
    username: str
    password: str
    max_download_bytes: int
    expiration_days: int
    account_creation_date: Optional[str] = None
    blocked: bool
    unlimited_ip: bool = Field(False, alias='unlimited_user')
    max_ips: Optional[int] = Field(0, description="Personal IP limit (0 = global)")
    note: Optional[str] = None
    status: Optional[str] = None
    upload_bytes: Optional[int] = None
    download_bytes: Optional[int] = None
    online_count: int = 0
    plan: Optional[str] = Field(
        "standard",
        description="User plan/tier (standard or premium)",
    )


class UserListResponse(RootModel):
    root: List[UserInfoResponse]


class UsernamesRequest(BaseModel):
    usernames: List[str]


class AddUserInputBody(BaseModel):
    username: str
    traffic_limit: int
    expiration_days: int
    password: Optional[str] = None
    creation_date: Optional[str] = None
    unlimited: bool = False
    note: Optional[str] = None
    max_ips: Optional[int] = Field(0, description="Personal IP limit (0 = global default)")
    plan: Optional[str] = Field(
        "standard",
        description="User plan/tier (standard or premium). Default: standard",
    )

    @field_validator('username')
    def validate_username(cls, v):
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError('Username can only contain letters, numbers, and underscores.')
        return v

    @field_validator('plan')
    def validate_plan(cls, v):
        if v is None:
            return "standard"
        v = v.lower()
        if v not in ("standard", "premium"):
            raise ValueError("plan must be 'standard' or 'premium'.")
        return v


class AddBulkUsersInputBody(BaseModel):
    traffic_gb: float
    expiration_days: int
    count: int
    prefix: str
    start_number: int = 1
    unlimited: bool = False
    max_ips: Optional[int] = Field(0, description="Personal IP limit for all users (0 = global default)")
    plan: Optional[str] = Field(
        "standard",
        description="User plan/tier for all created users (standard or premium). Default: standard",
    )

    @field_validator('prefix')
    def validate_prefix(cls, v):
        if not re.match(r"^[a-zA-Z0-9_]*$", v):
            raise ValueError('Prefix can only contain letters, numbers, and underscores.')
        return v

    @field_validator('plan')
    def validate_plan(cls, v):
        if v is None:
            return "standard"
        v = v.lower()
        if v not in ("standard", "premium"):
            raise ValueError("plan must be 'standard' or 'premium'.")
        return v


class EditUserInputBody(BaseModel):
    new_username: Optional[str] = Field(None, description="The new username for the user.")
    new_password: Optional[str] = Field(None, description="The new password. Leave empty to keep current.")
    new_traffic_limit: Optional[int] = Field(None, description="The new traffic limit in GB.")
    new_expiration_days: Optional[int] = Field(None, description="The new expiration in days.")
    renew_password: bool = Field(False, description="Whether to renew the user's password.")
    renew_creation_date: bool = Field(False, description="Whether to renew the user's creation date.")
    blocked: Optional[bool] = Field(None, description="Block status.")
    unlimited_ip: Optional[bool] = Field(None, description="Unlimited IP status.")
    max_ips: Optional[int] = Field(None, description="Personal IP limit.")
    note: Optional[str] = Field(None, description="A note for the user.")
    plan: Optional[str] = Field(
        None,
        description="User plan/tier (standard or premium).",
    )

    @field_validator('new_username')
    def validate_new_username(cls, v):
        if v and not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError('Username can only contain letters, numbers, and underscores.')
        return v

    @field_validator('plan')
    def validate_plan(cls, v):
        if v is None:
            return v
        v = v.lower()
        if v not in ("standard", "premium"):
            raise ValueError("plan must be 'standard' or 'premium'.")
        return v


class NodeUri(BaseModel):
    name: str
    uri: str


class UserUriResponse(BaseModel):
    username: str
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None
    nodes: Optional[List[NodeUri]] = []
    normal_sub: Optional[str] = None
    error: Optional[str] = None
