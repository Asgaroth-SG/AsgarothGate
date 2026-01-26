#!/usr/bin/env python3
"""
Обработчики параметров безопасности (TLS/Reality/None) для VLESS-ссылок.

Применяется после обработки транспорта для добавления параметров безопасности.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def apply_tls_security(
    query: Dict[str, str],
    stream_settings: Dict[str, Any],
    server_config: Any,
    inbound_id: int | str
) -> Dict[str, str]:
    """
    Применяет параметры TLS безопасности.
    
    Args:
        query: Текущие query-параметры
        stream_settings: Сырой dict streamSettings из API
        server_config: Конфигурация сервера (public_host, sni, etc.)
        inbound_id: ID inbound для логирования
        
    Returns:
        Обновленный dict query-параметров
    """
    logger.debug(f"Inbound {inbound_id}: Applying TLS security")
    
    query['security'] = 'tls'
    
    # SNI - используем из конфигурации сервера
    sni = getattr(server_config, 'sni', None) or getattr(server_config, 'public_host', None)
    if sni:
        query['sni'] = sni
    
    # Извлекаем tlsSettings (опционально)
    tls_settings = stream_settings.get('tlsSettings', {})
    if isinstance(tls_settings, dict):
        # serverName (если указан явно, переопределяет server.sni)
        server_name = tls_settings.get('serverName')
        if server_name and isinstance(server_name, str) and server_name.strip():
            query['sni'] = server_name.strip()
        
        # ALPN
        alpn = tls_settings.get('alpn')
        if alpn and isinstance(alpn, list) and len(alpn) > 0:
            # ALPN уже может быть установлен транспортом (xhttp/h2), не перезаписываем
            if 'alpn' not in query:
                query['alpn'] = ','.join(alpn)
        
        # Fingerprint
        fp = tls_settings.get('fingerprint')
        if fp and isinstance(fp, str) and fp.strip():
            # FP уже может быть установлен транспортом (xhttp), не перезаписываем
            if 'fp' not in query:
                query['fp'] = fp.strip()
        
        # allowInsecure (обычно false, редко используется)
        allow_insecure = tls_settings.get('allowInsecure')
        if allow_insecure is True:
            query['allowInsecure'] = '1'
    
    logger.debug(f"Inbound {inbound_id}: TLS params applied: sni={query.get('sni')}")
    return query


def apply_reality_security(
    query: Dict[str, str],
    stream_settings: Dict[str, Any],
    server_config: Any,
    inbound_id: int | str
) -> Dict[str, str]:
    """
    Применяет параметры Reality безопасности.
    
    Args:
        query: Текущие query-параметры
        stream_settings: Сырой dict streamSettings из API
        server_config: Конфигурация сервера
        inbound_id: ID inbound для логирования
        
    Returns:
        Обновленный dict query-параметров
    """
    logger.debug(f"Inbound {inbound_id}: Applying Reality security")
    
    query['security'] = 'reality'
    
    # Извлекаем realitySettings
    reality_settings = stream_settings.get('realitySettings', {})
    if not isinstance(reality_settings, dict):
        logger.warning(
            f"Inbound {inbound_id}: realitySettings missing or not a dict for Reality security"
        )
        reality_settings = {}
    
    # publicKey - ОБЯЗАТЕЛЬНЫЙ для Reality
    pbk = reality_settings.get('publicKey')
    if pbk and isinstance(pbk, str) and pbk.strip():
        query['pbk'] = pbk.strip()
    else:
        logger.warning(
            f"Inbound {inbound_id}: publicKey missing in realitySettings, Reality link may not work"
        )
    
    # shortIds
    short_ids = reality_settings.get('shortIds')
    if short_ids and isinstance(short_ids, list) and len(short_ids) > 0:
        # Берем первый shortId
        sid = short_ids[0]
        if sid and isinstance(sid, str):
            query['sid'] = sid.strip() if sid.strip() else ''
    else:
        # shortId может быть пустым
        query['sid'] = ''
    
    # serverNames (SNI для Reality)
    server_names = reality_settings.get('serverNames')
    if server_names and isinstance(server_names, list) and len(server_names) > 0:
        sni = server_names[0]
        if sni and isinstance(sni, str) and sni.strip():
            query['sni'] = sni.strip()
    else:
        # Fallback к server.sni
        sni = getattr(server_config, 'sni', None) or getattr(server_config, 'public_host', None)
        if sni:
            query['sni'] = sni
    
    # fingerprint (для Reality обычно chrome/firefox/safari)
    fp = reality_settings.get('fingerprint', 'chrome')
    if fp and isinstance(fp, str) and fp.strip():
        query['fp'] = fp.strip()
    else:
        query['fp'] = 'chrome'
    
    # spiderX (опциональный)
    spider_x = reality_settings.get('spiderX')
    if spider_x and isinstance(spider_x, str) and spider_x.strip():
        query['spx'] = spider_x.strip()
    
    logger.debug(
        f"Inbound {inbound_id}: Reality params applied: "
        f"pbk={query.get('pbk', 'N/A')[:20]}..., sni={query.get('sni')}"
    )
    return query


def apply_security(
    query: Dict[str, str],
    stream_settings: Dict[str, Any],
    server_config: Any,
    inbound_id: int | str
) -> Dict[str, str]:
    """
    Применяет параметры безопасности в зависимости от security в streamSettings.
    
    Args:
        query: Текущие query-параметры (от transport handler)
        stream_settings: Сырой dict streamSettings из API
        server_config: Конфигурация сервера
        inbound_id: ID inbound для логирования
        
    Returns:
        Обновленный dict query-параметров с параметрами безопасности
    """
    # Определяем тип безопасности
    security = (stream_settings.get('security') or '').lower()
    
    if not security:
        # Если за reverse-proxy Caddy на 443, по умолчанию TLS
        security = 'tls'
        logger.debug(
            f"Inbound {inbound_id}: security not specified, defaulting to TLS (reverse-proxy mode)"
        )
    
    if security == 'tls':
        return apply_tls_security(query, stream_settings, server_config, inbound_id)
    elif security == 'reality':
        return apply_reality_security(query, stream_settings, server_config, inbound_id)
    elif security == 'none':
        query['security'] = 'none'
        logger.debug(f"Inbound {inbound_id}: No security (security=none)")
        return query
    else:
        # Неизвестный тип безопасности, используем TLS как fallback
        logger.warning(
            f"Inbound {inbound_id}: Unknown security type '{security}', defaulting to TLS"
        )
        return apply_tls_security(query, stream_settings, server_config, inbound_id)
