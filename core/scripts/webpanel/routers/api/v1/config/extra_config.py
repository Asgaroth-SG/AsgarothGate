from fastapi import APIRouter, HTTPException
from ..schema.response import DetailResponse
import json

from ..schema.config.extra_config import (
    AddExtraConfigBody,
    DeleteExtraConfigBody,
    ExtraConfigListResponse,
)

import cli_api

router = APIRouter()


@router.get(
    "/list",
    response_model=ExtraConfigListResponse,
    summary="Get All Extra Configs"
)
async def get_all_extra_configs():
    """
    Retrieves the list of all configured extra proxy configurations.

    Each item contains:
    - name
    - uri
    - plan (standard | premium)
    """
    try:
        configs_str = cli_api.list_extra_configs()
        if not configs_str:
            return []

        data = json.loads(configs_str)

        # Обратная совместимость: если plan отсутствует — считаем standard
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
    summary="Add Extra Config"
)
async def add_extra_config(body: AddExtraConfigBody):
    """
    Adds a new extra proxy configuration.

    Args:
        body.name: config name
        body.uri: proxy URI
        body.plan: standard | premium
    """
    try:
        # Передаём plan в CLI
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
    summary="Delete Extra Config"
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
