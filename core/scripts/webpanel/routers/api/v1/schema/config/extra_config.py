from pydantic import BaseModel, field_validator, Field
from typing import Literal

VALID_PROTOCOLS = ("vmess://", "vless://", "ss://", "trojan://")
VALID_PLANS = ("standard", "premium")


class ExtraConfigBase(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        description="Unique name for the extra proxy configuration."
    )
    uri: str = Field(
        ...,
        description="Proxy URI (vmess, vless, ss, trojan)."
    )
    plan: Literal["standard", "premium"] = Field(
        "standard",
        description="Access level for this config: standard or premium."
    )

    @field_validator("uri")
    @classmethod
    def validate_uri_protocol(cls, v: str) -> str:
        if not any(v.startswith(protocol) for protocol in VALID_PROTOCOLS):
            raise ValueError(
                f"Invalid URI. Must start with one of: {', '.join(VALID_PROTOCOLS)}"
            )
        return v

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v: str) -> str:
        v = v.lower()
        if v not in VALID_PLANS:
            raise ValueError("plan must be either 'standard' or 'premium'")
        return v


class AddExtraConfigBody(ExtraConfigBase):
    """
    Body for adding a new extra proxy config.
    If plan is not provided, defaults to 'standard'.
    """
    pass


class DeleteExtraConfigBody(BaseModel):
    name: str = Field(
        ...,
        min_length=1,
        description="Name of the extra config to delete."
    )


class ExtraConfigResponse(ExtraConfigBase):
    """
    Response model for extra proxy configs.
    """
    pass


ExtraConfigListResponse = list[ExtraConfigResponse]
