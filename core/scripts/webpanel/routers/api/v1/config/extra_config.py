from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
import json

from ..schema.response import DetailResponse

from ..schema.config.extra_config import (
    AddExtraConfigBody,
    DeleteExtraConfigBody,
    ExtraConfigListResponse,
)

import cli_api

router = APIRouter()

class EditExtraConfigBody(BaseModel):
    old_name: str = Field(..., description="Текущее имя конфигурации")
    new_name: str = Field(..., description="Новое имя конфигурации")
    uri: str = Field(..., description="Новая ссылка (URI)")
    plan: Literal["standard", "premium"] = "standard"

class MoveExtraConfigBody(BaseModel):
    name: str = Field(..., description="Имя конфигурации для перемещения")
    direction: Literal["up", "down"] = Field(..., description="Направление: up или down")

@router.get(
    "/list",
    response_model=ExtraConfigListResponse,
    summary="Get All Extra Configs",
    name="get_all_extra_configs"
)
async def get_all_extra_configs():
    """
    Retrieves the list of all configured extra proxy configurations.
    """
    try:
        configs_str = cli_api.list_extra_configs()
        if not configs_str:
            return []

        data = json.loads(configs_str)

        normalized = []
        for item in data:
            if not isinstance(item, dict):
                continue
            normalized.append({
                "name": item.get("name"),
                "uri": item.get("uri"),
                "plan": item.get("plan", "standard")
            })

        return normalized

    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse extra configs list: {e}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve extra configs: {str(e)}"
        )


@router.post(
    "/add",
    response_model=DetailResponse,
    summary="Add Extra Config",
    name="add_extra_config"
)
async def add_extra_config(body: AddExtraConfigBody):
    """
    Adds a new extra proxy configuration.
    """
    try:
        cli_api.add_extra_config(
            name=body.name,
            uri=body.uri,
            plan=body.plan
        )

        return DetailResponse(
            detail=f"Extra config '{body.name}' added successfully ({body.plan})."
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/delete",
    response_model=DetailResponse,
    summary="Delete Extra Config",
    name="delete_extra_config"
)
async def delete_extra_config(body: DeleteExtraConfigBody):
    """
    Deletes an extra proxy configuration by its name.
    """
    try:
        cli_api.delete_extra_config(body.name)
        return DetailResponse(
            detail=f"Extra config '{body.name}' deleted successfully."
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/edit",
    response_model=DetailResponse,
    summary="Edit Extra Config",
    name="edit_extra_config" 
)
async def edit_extra_config(body: EditExtraConfigBody):
    """
    Редактирует существующую конфигурацию.
    """
    try:
        cli_api.edit_extra_config(
            old_name=body.old_name,
            new_name=body.new_name,
            uri=body.uri,
            plan=body.plan
        )
        return DetailResponse(detail=f"Конфигурация '{body.old_name}' успешно обновлена.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/move",
    response_model=DetailResponse,
    summary="Move Extra Config",
    name="move_extra_config"
)
async def move_extra_config(body: MoveExtraConfigBody):
    """
    Перемещает конфигурацию вверх или вниз.
    """
    try:
        cli_api.move_extra_config(
            name=body.name,
            direction=body.direction
        )
        return DetailResponse(detail=f"Конфигурация '{body.name}' успешно перемещена.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
