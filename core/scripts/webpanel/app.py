#!/usr/bin/env python3

import sys
import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from config import CONFIGS
from middleware import AuthMiddleware
from middleware import AfterRequestMiddleware
from dependency import get_session_manager
from openapi import setup_openapi_schema
from exception_handler import setup_exception_handler

HYSTERIA_CORE_DIR = '/etc/hysteria/core/'
sys.path.append(HYSTERIA_CORE_DIR)

import routers


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Запуск фонового опроса 3X-UI при старте приложения."""
    try:
        core_scripts = os.environ.get('HYSTERIA_SCRIPTS_DIR', '/etc/hysteria/core/scripts')
        if core_scripts not in sys.path:
            sys.path.insert(0, core_scripts)
        from xui.config import load_xui_config
        from xui.xui_background_poller import start_background_poller
        from db.database import db

        def _get_mappings():
            if not db:
                return {}
            out = {}
            for u in (db.get_all_users() or []):
                uid = u.get('_id')
                if not uid:
                    continue
                m = db.get_xui_mapping(uid)
                if m:
                    out[uid] = m
            return out

        # Запускаем фоновый опрос
        poller_thread = start_background_poller(load_xui_config, _get_mappings)
        logging.getLogger(__name__).info("XUI background poller started")
        
        # Даем время на первый опрос перед обработкой запросов (неблокирующая задержка)
        # Это помогает избежать таймаутов при первом запросе подписки
        async def wait_for_initial_poll():
            import asyncio
            await asyncio.sleep(2)  # Даем 2 секунды на первый опрос
        
        # Запускаем ожидание в фоне (не блокируем старт приложения)
        try:
            asyncio.create_task(wait_for_initial_poll())
        except RuntimeError:
            # Если event loop еще не запущен, создаем задачу позже
            pass
    except Exception as e:
        logging.getLogger(__name__).warning("XUI background poller not started: %s", e)
    yield
    # shutdown: поллер — daemon-поток, завершится с процессом


def create_app() -> FastAPI:
    '''
    Create FastAPI app.
    '''

    app = FastAPI(
        title='Asgaroth Gate API',
        description='Webpanel for Hysteria2',
        version='0.2.0',
        contact={
            'github': 'https://github.com/Asgaroth-SG/AsgarothGate'
        },
        debug=CONFIGS.DEBUG,
        root_path=f'/{CONFIGS.ROOT_PATH}',
        lifespan=app_lifespan,
    )

    app.mount('/assets', StaticFiles(directory='assets'), name='assets')

    setup_exception_handler(app)

    app.add_middleware(AuthMiddleware, session_manager=get_session_manager(), api_token=CONFIGS.API_TOKEN)
    app.add_middleware(AfterRequestMiddleware)

    app.include_router(routers.basic.router, prefix='', tags=['Web - Basic'])
    app.include_router(routers.login.router, prefix='', tags=['Web - Authentication'])
    app.include_router(routers.settings.router, prefix='/settings', tags=['Web - Settings'])
    app.include_router(routers.user.router, prefix='/users', tags=['Web - User Management'])
    app.include_router(routers.api.v1.api_v1_router, prefix='/api/v1')

    setup_openapi_schema(app)

    return app


app: FastAPI = create_app()


if __name__ == '__main__':
    from hypercorn.config import Config
    from hypercorn.asyncio import serve
    from hypercorn.middleware import ProxyFixMiddleware

    config = Config()
    config.debug = CONFIGS.DEBUG
    config.bind = ['127.0.0.1:28260']
    config.accesslog = '-'
    config.errorlog = '-'

    app = ProxyFixMiddleware(app, 'legacy')
    asyncio.run(serve(app, config))