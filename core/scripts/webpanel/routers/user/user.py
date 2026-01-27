from fastapi import APIRouter, HTTPException, Request, Depends, Query, Path, Cookie
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_302_FOUND
import math
import time
import threading
from typing import Optional, Dict, Any, Tuple

from dependency import get_templates
from .viewmodel import User
import cli_api


router = APIRouter()

# Кэш для списка пользователей (TTL: 5 секунд)
_users_list_cache: Optional[Tuple[float, list]] = None
_users_list_cache_lock = threading.Lock()
_users_list_cache_ttl = 5  # 5 секунд


async def get_users_page(
    request: Request,
    templates: Jinja2Templates,
    page: int,
    limit: int
):
    try:
        # Оптимизация: используем пагинацию на уровне БД вместо загрузки всех пользователей
        # Это критично для производительности при большом количестве пользователей
        import sys
        from pathlib import Path
        core_scripts_path = '/etc/hysteria/core/scripts'
        if core_scripts_path not in sys.path:
            sys.path.insert(0, core_scripts_path)
        
        db_instance = None
        try:
            from db.database import db
            db_instance = db
            if db:
                # Используем пагинацию на уровне БД
                start_index = (page - 1) * limit
                users_list, total_users = db.get_users_paginated(skip=start_index, limit=limit)
                
                # Преобразуем формат (добавляем username из _id)
                for user in users_list:
                    if '_id' in user:
                        user['username'] = user.pop('_id')
            else:
                # Fallback к старому методу если БД недоступна
                users_list = cli_api.list_users() or []
                total_users = len(users_list)
                start_index = (page - 1) * limit
                end_index = start_index + limit
                users_list = users_list[start_index:end_index]
        except Exception as e:
            # Fallback к старому методу при ошибке (с кэшированием)
            db_instance = None
            now = time.time()
            cached = None
            
            with _users_list_cache_lock:
                if _users_list_cache:
                    cached_at, cached_list = _users_list_cache
                    age = now - cached_at
                    if age < _users_list_cache_ttl:
                        cached = cached_list
            
            if cached is None:
                users_list = cli_api.list_users() or []
                with _users_list_cache_lock:
                    _users_list_cache = (now, users_list)
            else:
                users_list = cached
            
            total_users = len(users_list)
            start_index = (page - 1) * limit
            end_index = start_index + limit
            users_list = users_list[start_index:end_index]
        
        total_pages = math.ceil(total_users / limit) if limit > 0 else 1

        if page > total_pages and total_pages > 0:
            return RedirectResponse(url=f"/users/{total_pages}", status_code=HTTP_302_FOUND)
        if page < 1:
            return RedirectResponse(url=f"/users/1", status_code=HTTP_302_FOUND)

        # Батчинг маппингов для оптимизации запросов к БД
        usernames = [user_data.get('username', '') for user_data in users_list if user_data.get('username')]
        mappings_dict = {}
        if usernames and db_instance:
            try:
                mappings_dict = db_instance.get_users_mappings_batch(usernames)
            except Exception:
                mappings_dict = {}

        users: list[User] = [
            User.from_dict_with_mapping(
                user_data.get('username', ''), 
                user_data,
                mappings_dict.get(user_data.get('username', '').lower())
            ) 
            for user_data in users_list
        ]

        return templates.TemplateResponse(
            'users.html',
            {
                'users': users,
                'request': request,
                'current_page': page,
                'total_pages': total_pages,
                'limit': limit,
                'total_users': total_users,
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Error: {str(e)}')


@router.get('/{page}', name="users_paginated")
async def users_paginated(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    page: int = Path(..., ge=1),
    limit: int = Cookie(default=50, ge=1)
):
    return await get_users_page(request, templates, page, limit)


@router.get('/', name="users")
async def users_root(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    limit: int = Cookie(default=50, ge=1)
):
    return await get_users_page(request, templates, 1, limit)

@router.get("/search/", name="search_users")
async def search_users(
    request: Request,
    q: str = Query(""),
    templates: Jinja2Templates = Depends(get_templates)
):
    try:
        if not q:
            all_users_data = []
        else:
            # Используем кэш для поиска
            now = time.time()
            cached = None
            
            with _users_list_cache_lock:
                if _users_list_cache:
                    cached_at, cached_list = _users_list_cache
                    age = now - cached_at
                    if age < _users_list_cache_ttl:
                        cached = cached_list
            
            if cached is None:
                all_users_data = cli_api.list_users() or []
                with _users_list_cache_lock:
                    _users_list_cache = (now, all_users_data)
            else:
                all_users_data = cached
        
        query = q.lower()
        
        filtered_users_data = [
            user_data for user_data in all_users_data
            if query in user_data.get('username', '').lower() or query in user_data.get('note', '').lower()
        ]

        users: list[User] = [User.from_dict(user_data.get('username', ''), user_data) for user_data in filtered_users_data]

        return templates.TemplateResponse(
            'users_rows.html',
            {'request': request, 'users': users}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))