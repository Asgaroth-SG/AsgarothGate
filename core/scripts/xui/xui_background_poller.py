#!/usr/bin/env python3
"""
Асинхронный опрос серверов 3X-UI (asyncio + aiohttp).

Фоновые задачи выполняют все запросы к внешним серверам 3X-UI.
Результаты кэшируются; трафик, веб-панель и генерация VLESS читают только из кэша.
"""

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

# Глобальный кэш (один писатель — поллер; читатели — traffic, webpanel, VLESS)
_cache: Dict[str, Any] = {"by_host": {}, "last_full_poll": 0}
_cache_lock = threading.Lock()

# Интервал опроса (секунды)
# Уменьшен до 30 секунд для более точного отслеживания статусов онлайн
POLL_INTERVAL = 30
# Таймаут одного запроса
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5)


def _extract_obj(data: dict) -> Any:
    for key in ("obj", "data", "result"):
        if key in data:
            return data[key]
    return data


def _build_url(base_url: str, path: str) -> str:
    path = path.lstrip("/")
    return f"{base_url.rstrip('/')}/{path}"


async def _poll_server(
    session: aiohttp.ClientSession,
    host: str,
    server_config: Dict[str, Any],
    mappings: Dict[str, Dict],
) -> Optional[Dict[str, Any]]:
    """Опрос одного сервера 3X-UI через aiohttp."""
    base_url = host if "://" in host else f"https://{host}"
    parsed = urlparse(base_url)
    if not parsed.scheme:
        base_url = f"https://{base_url}"
    base_path = (server_config.get("base_path") or "/").strip().rstrip("/")
    if base_path and base_path != "/":
        base_url = f"{base_url.rstrip('/')}/{base_path.lstrip('/')}"
    else:
        base_url = base_url.rstrip("/")

    auth_type = server_config.get("auth_type", "username")
    username = "admin" if auth_type == "token" else (server_config.get("username") or "")
    password = server_config.get("password") or ""

    if not password:
        logger.warning(f"Server {host}: skip, no password")
        return None

    out = {
        "online": False,
        "last_check": 0,
        "server_id": server_config.get("name") or (urlparse(host).hostname or host),
        "inbounds": {},
        "online_clients": [],
        "client_traffics": {},
    }
    cookies: Optional[aiohttp.CookieJar] = None

    try:
        login_url = _build_url(base_url, "login/")
        async with session.post(
            login_url,
            json={"username": username, "password": password},
            timeout=REQUEST_TIMEOUT,
            ssl=False,
        ) as resp:
            if resp.status != 200:
                logger.warning(f"Server {host}: login failed {resp.status}")
                return out
            cookies = resp.cookies
    except asyncio.TimeoutError:
        logger.warning(f"Server {host}: login timeout")
        return out
    except Exception as e:
        logger.warning(f"Server {host}: login error {e}")
        return out

    out["online"] = True
    out["last_check"] = time.time()

    # Список inbounds
    try:
        url = _build_url(base_url, "panel/api/inbounds/list")
        async with session.get(url, cookies=cookies, timeout=REQUEST_TIMEOUT, ssl=False) as r:
            if r.status != 200:
                return out
            data = await r.json()
            inbounds_list = _extract_obj(data)
            if not isinstance(inbounds_list, list):
                inbounds_list = []
    except Exception as e:
        logger.debug(f"Server {host}: inbounds list error {e}")
        return out

    # Фильтр VLESS и загрузка деталей по каждому inbound
    inbound_filter = server_config.get("inbound_filter") or {}
    protocol_filter = (inbound_filter.get("protocol") or "vless").lower()
    for ib in inbounds_list:
        if ib.get("protocol", "").lower() != protocol_filter:
            continue
        iid = ib.get("id")
        if iid is None:
            continue
        try:
            u = _build_url(base_url, f"panel/api/inbounds/get/{iid}")
            async with session.get(u, cookies=cookies, timeout=REQUEST_TIMEOUT, ssl=False) as r:
                if r.status == 200:
                    data = await r.json()
                    obj = _extract_obj(data)
                    if isinstance(obj, dict):
                        out["inbounds"][iid] = obj
        except Exception as e:
            logger.debug(f"Server {host}: get inbound {iid} error {e}")

    # Онлайн-клиенты: onlines
    try:
        url = _build_url(base_url, "panel/api/inbounds/onlines")
        async with session.post(url, cookies=cookies, timeout=REQUEST_TIMEOUT, ssl=False) as r:
            if r.status != 200:
                return out
            data = await r.json()
            obj = _extract_obj(data)
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                out["online_clients"] = obj
            elif isinstance(obj, list) and obj and isinstance(obj[0], str):
                # Строки — детализацию через client ips не делаем в поллере
                out["online_clients"] = []
            elif isinstance(obj, dict):
                out["online_clients"] = obj.get("clients") or obj.get("onlines") or []
    except Exception as e:
        logger.debug(f"Server {host}: onlines error {e}")

    # Если onlines вернул только строки — собираем детали по клиентам из inbounds
    if not out["online_clients"] and out["inbounds"]:
        by_uuid = {m.get("xui_client_uuid"): (u, m.get("xui_host")) for u, m in (mappings or {}).items() if m}
        seen = set()
        for ib in out["inbounds"].values():
            settings = ib.get("settings") or {}
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except Exception:
                    continue
            for cl in settings.get("clients", []):
                cid = cl.get("id") or cl.get("email") or ""
                if not cid or cid in seen:
                    continue
                seen.add(cid)
                try:
                    u = _build_url(base_url, f"panel/api/clients/{cid}/ips")
                    async with session.get(u, cookies=cookies, timeout=REQUEST_TIMEOUT, ssl=False) as ri:
                        if ri.status != 200:
                            continue
                        d = await ri.json()
                        ips = _extract_obj(d)
                        ips_list = None
                        if isinstance(ips, list) and ips:
                            ips_list = ips
                        elif isinstance(ips, dict) and ips.get("ips"):
                            ips_list = ips["ips"]
                        
                        # Добавляем клиента даже если IP пустые (для определения онлайна)
                        # Но логируем предупреждение для отладки проблем с реверс-прокси
                        if ips_list:
                            out["online_clients"].append({"id": cl.get("id"), "email": cl.get("email", ""), "ips": ips_list})
                        else:
                            # Если IP пустые, но клиент в списке онлайн, добавляем с пустым списком IP
                            # Это может быть проблемой с реверс-прокси (Caddy не передает реальные IP)
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.debug(f"Client {cid} is online but has no IPs (possible reverse proxy issue)")
                            out["online_clients"].append({"id": cl.get("id"), "email": cl.get("email", ""), "ips": []})
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.debug(f"Error getting IPs for client {cid}: {e}")
                    continue

    # Трафик по UUID для известных пользователей
    uuids_for_host = []
    for username, m in mappings.items():
        if m.get("xui_host") and m.get("xui_host") != host:
            continue
        uuid_val = m.get("xui_client_uuid")
        if uuid_val:
            uuids_for_host.append(uuid_val)
    for uuid_val in set(uuids_for_host):
        try:
            url = _build_url(base_url, f"panel/api/inbounds/getClientTrafficsById/{uuid_val}")
            async with session.get(url, cookies=cookies, timeout=REQUEST_TIMEOUT, ssl=False) as r:
                if r.status != 200:
                    continue
                data = await r.json()
                obj = _extract_obj(data)
                items = obj if isinstance(obj, list) else (obj.get("data") or obj.get("traffics") or [])
                if not isinstance(items, list):
                    continue
                up, down = 0, 0
                for t in items:
                    up += int(t.get("up") or 0)
                    down += int(t.get("down") or 0)
                if up or down:
                    out["client_traffics"][uuid_val] = {"up": up, "down": down}
        except Exception as e:
            logger.debug(f"Server {host}: traffic {uuid_val} error {e}")

    return out


async def _poll_all_servers(
    config: Dict[str, Any],
    get_mappings_fn: Optional[Callable[[], Dict[str, Dict]]],
) -> None:
    """Параллельный опрос всех серверов 3X-UI."""
    servers = [
        s for s in (config.get("xui_servers") or [])
        if s.get("enabled", True) and s.get("host") and s.get("password")
    ]
    if not servers:
        return

    mappings = (get_mappings_fn() or {}) if get_mappings_fn else {}

    async with aiohttp.ClientSession() as session:
        tasks = [
            _poll_server(session, s["host"], s, mappings)
            for s in servers
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        with _cache_lock:
            _cache["by_host"].clear()
            for s, res in zip(servers, results):
                host = s["host"]
                if isinstance(res, Exception):
                    logger.warning(f"Poll {host} failed: {res}")
                    _cache["by_host"][host] = {"online": False, "last_check": 0, "inbounds": {}, "online_clients": [], "client_traffics": {}, "server_id": s.get("name") or host}
                elif res:
                    _cache["by_host"][host] = res
            _cache["last_full_poll"] = time.time()


async def _run_loop(config_fn, get_mappings_fn, interval: float = POLL_INTERVAL):
    """Бесконечный цикл опроса."""
    # Первый опрос выполняется сразу при старте (без задержки)
    first_run = True
    
    while True:
        try:
            config = config_fn() if callable(config_fn) else (config_fn or {})
            if config.get("enabled") and (config.get("xui_servers")):
                await _poll_all_servers(config, get_mappings_fn)
                if first_run:
                    logger.info("Initial XUI background poll completed")
                    first_run = False
        except Exception as e:
            logger.exception(f"XUI background poll error: {e}")
        
        # После первого запуска используем интервал
        if not first_run:
            await asyncio.sleep(interval)
        else:
            first_run = False


def get_cache() -> Dict[str, Any]:
    """Возвращает текущий кэш (by_host и last_full_poll)."""
    with _cache_lock:
        return {"by_host": dict(_cache["by_host"]), "last_full_poll": _cache["last_full_poll"]}


def get_inbounds_cache() -> Dict[str, Dict[int, Dict]]:
    """Кэш inbounds по хосту: {host: {inbound_id: inbound_dict}}."""
    with _cache_lock:
        return {h: dict(data.get("inbounds", {})) for h, data in _cache["by_host"].items()}


def get_online_and_traffic_for_mappings(
    mappings: Dict[str, Dict],
    servers_config: List[Dict],
) -> tuple:
    """
    По кэшу и маппингам возвращает (online_users, traffic_by_user).
    online_users: {username: count}; traffic_by_user: {username: {upload_bytes, download_bytes}}.
    """
    with _cache_lock:
        by_host = dict(_cache["by_host"])
    online_users = {}
    traffic_by_user = {}
    host_to_plan = {}
    for s in servers_config or []:
        if s.get("host"):
            host_to_plan[s["host"]] = s

    for username, m in (mappings or {}).items():
        uuid_val = m.get("xui_client_uuid")
        xui_host = m.get("xui_host")
        if not uuid_val:
            continue
        for host, data in by_host.items():
            if xui_host and host != xui_host:
                continue
            if not data.get("online"):
                continue
            for cl in data.get("online_clients") or []:
                cid = cl.get("id") or cl.get("email") or ""
                if cid != uuid_val and cid != username:
                    email = cl.get("email", "")
                    if email != f"{username}_" and not email.startswith(f"{username}_"):
                        continue
                if cid == uuid_val or (isinstance(cl.get("email"), str) and cl.get("email", "").startswith(f"{username}_")):
                    cnt = len(cl.get("ips") or [1])
                    online_users[username] = max(online_users.get(username, 0), cnt)
                    break
            tr = (data.get("client_traffics") or {}).get(uuid_val)
            if tr:
                cur = traffic_by_user.setdefault(username, {"upload_bytes": 0, "download_bytes": 0})
                cur["upload_bytes"] += int(tr.get("up") or 0)
                cur["download_bytes"] += int(tr.get("down") or 0)

    return online_users, traffic_by_user


def start_background_poller(
    config_fn: Callable[[], Dict[str, Any]],
    get_mappings_fn: Optional[Callable[[], Dict[str, Dict]]] = None,
    interval: float = POLL_INTERVAL,
    loop: Optional[asyncio.AbstractEventLoop] = None,
):
    """
    Запускает фоновый опрос в отдельном потоке.
    config_fn() / get_mappings_fn() вызываются при каждом цикле.
    """
    def run():
        nonlocal loop
        if loop is None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_loop(config_fn, get_mappings_fn, interval))

    t = threading.Thread(target=run, daemon=True)
    t.start()
    logger.info("XUI background poller started")
    return t
