#!/usr/bin/env python3
"""
Обработчики транспортов для генерации VLESS-ссылок.

Архитектура: каждый транспорт имеет свой handler, который извлекает
параметры из RAW streamSettings и возвращает query-параметры.

Использование:
    handler = TRANSPORT_HANDLERS.get(network)
    if handler:
        query_params = handler(stream_settings, inbound_id)
"""

import logging
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)


# ============================================================================
# TRANSPORT HANDLERS
# ============================================================================

def handle_grpc(stream_settings: Dict[str, Any], inbound_id: int | str) -> Optional[Dict[str, str]]:
    """
    Обработчик gRPC транспорта.
    
    Извлекает:
    - serviceName (обязательный)
    - mode (multi/gun, опциональный)
    - authority (опциональный)
    
    Returns:
        dict с query-параметрами или None если serviceName отсутствует
    """
    logger.debug(f"Inbound {inbound_id}: Handling gRPC transport")
    
    # Извлекаем grpcSettings
    grpc_settings = stream_settings.get('grpcSettings')
    if not grpc_settings or not isinstance(grpc_settings, dict):
        logger.warning(
            f"Inbound {inbound_id}: grpcSettings missing or not a dict for gRPC transport, skipping"
        )
        return None
    
    # serviceName - ОБЯЗАТЕЛЬНЫЙ
    service_name = grpc_settings.get('serviceName')
    if not service_name or not isinstance(service_name, str) or not service_name.strip():
        logger.warning(
            f"Inbound {inbound_id}: serviceName missing or empty in grpcSettings, skipping gRPC link"
        )
        return None
    
    query = {
        'type': 'grpc',
        'serviceName': service_name.strip()
    }
    
    # mode (опциональный)
    multi_mode = grpc_settings.get('multiMode')
    if multi_mode is not None:
        mode_value = 'multi' if multi_mode else 'gun'
        query['mode'] = mode_value
    
    # authority (опциональный)
    authority = grpc_settings.get('authority')
    if authority and isinstance(authority, str) and authority.strip():
        query['authority'] = authority.strip()
    
    logger.debug(f"Inbound {inbound_id}: gRPC params: {query}")
    return query


def handle_xhttp(stream_settings: Dict[str, Any], inbound_id: int | str) -> Optional[Dict[str, str]]:
    """
    Обработчик xHTTP транспорта.
    
    Извлекает:
    - path (обязательный)
    - mode (опциональный, default: auto)
    - host (опциональный)
    
    Returns:
        dict с query-параметрами или None если path отсутствует
    """
    logger.debug(f"Inbound {inbound_id}: Handling xHTTP transport")
    
    # Извлекаем xhttpSettings
    xhttp_settings = stream_settings.get('xhttpSettings')
    if not xhttp_settings or not isinstance(xhttp_settings, dict):
        logger.warning(
            f"Inbound {inbound_id}: xhttpSettings missing or not a dict for xHTTP transport, skipping"
        )
        return None
    
    # path - ОБЯЗАТЕЛЬНЫЙ
    path = xhttp_settings.get('path')
    if not path:
        # Пробуем paths array
        paths = xhttp_settings.get('paths')
        if paths and isinstance(paths, list) and len(paths) > 0:
            path = paths[0]
    
    if not path or not isinstance(path, str) or not path.strip() or path.strip() == '/':
        logger.warning(
            f"Inbound {inbound_id}: path missing, empty or '/' in xhttpSettings, skipping xHTTP link"
        )
        return None
    
    query = {
        'type': 'xhttp',
        'path': path.strip()
    }
    
    # mode (опциональный, default: auto)
    mode = xhttp_settings.get('mode', 'auto')
    if mode and isinstance(mode, str):
        query['mode'] = mode.strip() if mode.strip() else 'auto'
    else:
        query['mode'] = 'auto'
    
    # host (опциональный)
    host = xhttp_settings.get('host')
    if host and isinstance(host, str) and host.strip():
        query['host'] = host.strip()
    
    # Для xHTTP добавляем специфичные параметры
    query['alpn'] = 'h2'
    query['fp'] = 'chrome'
    
    logger.debug(f"Inbound {inbound_id}: xHTTP params: {query}")
    return query


def handle_ws(stream_settings: Dict[str, Any], inbound_id: int | str) -> Optional[Dict[str, str]]:
    """
    Обработчик WebSocket транспорта.
    
    Извлекает:
    - path (опциональный, default: /)
    - host (из headers.Host, опциональный)
    
    Returns:
        dict с query-параметрами
    """
    logger.debug(f"Inbound {inbound_id}: Handling WebSocket transport")
    
    # Извлекаем wsSettings
    ws_settings = stream_settings.get('wsSettings', {})
    if not isinstance(ws_settings, dict):
        ws_settings = {}
    
    query = {
        'type': 'ws'
    }
    
    # path (default: /)
    path = ws_settings.get('path', '/')
    if path and isinstance(path, str):
        query['path'] = path.strip() if path.strip() else '/'
    else:
        query['path'] = '/'
    
    # host (из headers)
    headers = ws_settings.get('headers')
    if isinstance(headers, dict):
        host = headers.get('Host')
        if host and isinstance(host, str) and host.strip():
            query['host'] = host.strip()
    
    logger.debug(f"Inbound {inbound_id}: WebSocket params: {query}")
    return query


def handle_tcp(stream_settings: Dict[str, Any], inbound_id: int | str) -> Optional[Dict[str, str]]:
    """
    Обработчик TCP транспорта.
    
    Извлекает:
    - header.type (none/http)
    - Если http: request.path, request.headers
    
    Returns:
        dict с query-параметрами
    """
    logger.debug(f"Inbound {inbound_id}: Handling TCP transport")
    
    query = {
        'type': 'tcp'
    }
    
    # Извлекаем tcpSettings
    tcp_settings = stream_settings.get('tcpSettings', {})
    if not isinstance(tcp_settings, dict):
        tcp_settings = {}
    
    # header.type
    header = tcp_settings.get('header', {})
    if isinstance(header, dict):
        header_type = header.get('type', 'none')
        if header_type and header_type != 'none':
            query['headerType'] = header_type
            
            # Если http header, можно извлечь дополнительные параметры
            if header_type == 'http':
                request = header.get('request', {})
                if isinstance(request, dict):
                    # path
                    path = request.get('path')
                    if path:
                        if isinstance(path, list) and len(path) > 0:
                            query['path'] = path[0]
                        elif isinstance(path, str):
                            query['path'] = path
                    
                    # host
                    headers = request.get('headers', {})
                    if isinstance(headers, dict):
                        host = headers.get('Host')
                        if host:
                            if isinstance(host, list) and len(host) > 0:
                                query['host'] = host[0]
                            elif isinstance(host, str):
                                query['host'] = host
    
    logger.debug(f"Inbound {inbound_id}: TCP params: {query}")
    return query


def handle_h2(stream_settings: Dict[str, Any], inbound_id: int | str) -> Optional[Dict[str, str]]:
    """
    Обработчик HTTP/2 транспорта.
    
    Извлекает:
    - path (опциональный)
    - host (опциональный)
    
    Returns:
        dict с query-параметрами
    """
    logger.debug(f"Inbound {inbound_id}: Handling HTTP/2 transport")
    
    query = {
        'type': 'h2',
        'alpn': 'h2'  # Для H2 обязательно
    }
    
    # Извлекаем httpSettings (для h2)
    http_settings = stream_settings.get('httpSettings', {})
    if not isinstance(http_settings, dict):
        http_settings = {}
    
    # path
    path = http_settings.get('path', '/')
    if path and isinstance(path, str):
        query['path'] = path.strip() if path.strip() else '/'
    
    # host
    host = http_settings.get('host')
    if host:
        if isinstance(host, list) and len(host) > 0:
            query['host'] = host[0]
        elif isinstance(host, str) and host.strip():
            query['host'] = host.strip()
    
    logger.debug(f"Inbound {inbound_id}: HTTP/2 params: {query}")
    return query


def handle_splithttp(stream_settings: Dict[str, Any], inbound_id: int | str) -> Optional[Dict[str, str]]:
    """
    Обработчик SplitHTTP транспорта.
    
    Извлекает:
    - path (обязательный)
    - mode (опциональный)
    - host (опциональный)
    
    Returns:
        dict с query-параметрами или None если path отсутствует
    """
    logger.debug(f"Inbound {inbound_id}: Handling SplitHTTP transport")
    
    # Извлекаем splithttpSettings или splitHttpSettings
    splithttp_settings = stream_settings.get('splithttpSettings') or stream_settings.get('splitHttpSettings')
    if not splithttp_settings or not isinstance(splithttp_settings, dict):
        logger.warning(
            f"Inbound {inbound_id}: splithttpSettings missing or not a dict for SplitHTTP transport, skipping"
        )
        return None
    
    # path - ОБЯЗАТЕЛЬНЫЙ
    path = splithttp_settings.get('path')
    if not path or not isinstance(path, str) or not path.strip() or path.strip() == '/':
        logger.warning(
            f"Inbound {inbound_id}: path missing, empty or '/' in splithttpSettings, skipping SplitHTTP link"
        )
        return None
    
    query = {
        'type': 'splithttp',
        'path': path.strip()
    }
    
    # mode (опциональный)
    mode = splithttp_settings.get('mode')
    if mode and isinstance(mode, str) and mode.strip():
        query['mode'] = mode.strip()
    
    # host (опциональный)
    host = splithttp_settings.get('host')
    if host and isinstance(host, str) and host.strip():
        query['host'] = host.strip()
    
    logger.debug(f"Inbound {inbound_id}: SplitHTTP params: {query}")
    return query


def handle_httpupgrade(stream_settings: Dict[str, Any], inbound_id: int | str) -> Optional[Dict[str, str]]:
    """
    Обработчик HTTPUpgrade транспорта.
    
    Извлекает:
    - path (опциональный, default: /)
    - host (опциональный)
    
    Returns:
        dict с query-параметрами
    """
    logger.debug(f"Inbound {inbound_id}: Handling HTTPUpgrade transport")
    
    # Извлекаем httpupgradeSettings
    httpupgrade_settings = stream_settings.get('httpupgradeSettings', {})
    if not isinstance(httpupgrade_settings, dict):
        httpupgrade_settings = {}
    
    query = {
        'type': 'httpupgrade'
    }
    
    # path (default: /)
    path = httpupgrade_settings.get('path', '/')
    if path and isinstance(path, str):
        query['path'] = path.strip() if path.strip() else '/'
    else:
        query['path'] = '/'
    
    # host
    host = httpupgrade_settings.get('host')
    if host and isinstance(host, str) and host.strip():
        query['host'] = host.strip()
    
    logger.debug(f"Inbound {inbound_id}: HTTPUpgrade params: {query}")
    return query


def handle_kcp(stream_settings: Dict[str, Any], inbound_id: int | str) -> Optional[Dict[str, str]]:
    """
    Обработчик KCP транспорта.
    
    Извлекает:
    - seed (опциональный)
    - header.type (опциональный)
    
    Returns:
        dict с query-параметрами
    """
    logger.debug(f"Inbound {inbound_id}: Handling KCP transport")
    
    query = {
        'type': 'kcp'
    }
    
    # Извлекаем kcpSettings
    kcp_settings = stream_settings.get('kcpSettings', {})
    if not isinstance(kcp_settings, dict):
        kcp_settings = {}
    
    # seed
    seed = kcp_settings.get('seed')
    if seed and isinstance(seed, str) and seed.strip():
        query['seed'] = seed.strip()
    
    # header.type
    header = kcp_settings.get('header', {})
    if isinstance(header, dict):
        header_type = header.get('type')
        if header_type and isinstance(header_type, str) and header_type.strip():
            query['headerType'] = header_type.strip()
    
    logger.warning(
        f"Inbound {inbound_id}: KCP transport typically not used behind reverse-proxy (TLS:443). "
        f"Link may not work correctly."
    )
    
    logger.debug(f"Inbound {inbound_id}: KCP params: {query}")
    return query


def handle_quic(stream_settings: Dict[str, Any], inbound_id: int | str) -> Optional[Dict[str, str]]:
    """
    Обработчик QUIC транспорта.
    
    Извлекает:
    - security (quic-specific, не путать с TLS)
    - key
    - header.type
    
    Returns:
        dict с query-параметрами
    """
    logger.debug(f"Inbound {inbound_id}: Handling QUIC transport")
    
    query = {
        'type': 'quic'
    }
    
    # Извлекаем quicSettings
    quic_settings = stream_settings.get('quicSettings', {})
    if not isinstance(quic_settings, dict):
        quic_settings = {}
    
    # security (quic-specific)
    quic_security = quic_settings.get('security')
    if quic_security and isinstance(quic_security, str) and quic_security.strip():
        query['quicSecurity'] = quic_security.strip()
    
    # key
    key = quic_settings.get('key')
    if key and isinstance(key, str) and key.strip():
        query['key'] = key.strip()
    
    # header.type
    header = quic_settings.get('header', {})
    if isinstance(header, dict):
        header_type = header.get('type')
        if header_type and isinstance(header_type, str) and header_type.strip():
            query['headerType'] = header_type.strip()
    
    logger.warning(
        f"Inbound {inbound_id}: QUIC transport typically not used behind reverse-proxy (TLS:443). "
        f"Link may not work correctly."
    )
    
    logger.debug(f"Inbound {inbound_id}: QUIC params: {query}")
    return query


# ============================================================================
# TRANSPORT HANDLERS REGISTRY
# ============================================================================

TRANSPORT_HANDLERS: Dict[str, Callable[[Dict[str, Any], int | str], Optional[Dict[str, str]]]] = {
    'grpc': handle_grpc,
    'xhttp': handle_xhttp,
    'ws': handle_ws,
    'tcp': handle_tcp,
    'h2': handle_h2,
    'http': handle_h2,  # Алиас для h2
    'splithttp': handle_splithttp,
    'httpupgrade': handle_httpupgrade,
    'kcp': handle_kcp,
    'quic': handle_quic,
}


def get_transport_handler(network: str) -> Optional[Callable]:
    """
    Получает handler для указанного транспорта.
    
    Args:
        network: Тип транспорта (grpc, xhttp, ws, etc.)
        
    Returns:
        Handler функция или None если транспорт не поддерживается
    """
    return TRANSPORT_HANDLERS.get(network.lower() if network else '')


def is_transport_supported(network: str) -> bool:
    """Проверяет, поддерживается ли указанный транспорт."""
    return network.lower() in TRANSPORT_HANDLERS if network else False
