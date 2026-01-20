#!/usr/bin/env python3
"""
LinkRewriter - универсальный переписчик ссылок для reverse proxy контуров.

Применяется только при выдаче normal sub для преобразования внутренних адресов
(127.0.0.1) в публичные (public_host:public_port) с сохранением всех параметров.
"""
import base64
import json
import logging
from typing import Dict, Any, Optional, Tuple
from urllib.parse import (
    urlparse, urlunparse, parse_qs, urlencode, quote, unquote,
    parse_qsl, urlunsplit, urlsplit
)

logger = logging.getLogger(__name__)


class XuiServerConfig:
    """Конфигурация сервера X-UI для переписывания ссылок"""
    def __init__(
        self,
        server_id: str,
        public_host: str,
        public_port: int = 443,
        link_host_rewrite_from: str = "127.0.0.1"
    ):
        self.server_id = server_id
        self.public_host = public_host
        self.public_port = public_port
        self.link_host_rewrite_from = link_host_rewrite_from


def is_reverse_proxy_host(host: str, server_cfg: XuiServerConfig) -> bool:
    """Проверяет, является ли хост внутренним адресом для переписывания"""
    return host in (server_cfg.link_host_rewrite_from, "127.0.0.1", "localhost")


def safe_b64_decode(data: str) -> Optional[bytes]:
    """Безопасное декодирование base64 с поддержкой URL-safe и padding"""
    try:
        # Добавляем padding если нужно
        missing_padding = len(data) % 4
        if missing_padding:
            data += '=' * (4 - missing_padding)
        
        # Пробуем стандартное декодирование
        try:
            return base64.b64decode(data)
        except Exception:
            # Пробуем URL-safe
            return base64.urlsafe_b64decode(data)
    except Exception as e:
        logger.warning(f"Failed to decode base64: {e}")
        return None


def safe_b64_encode(data: bytes) -> str:
    """Безопасное кодирование в base64 (стандартное, не URL-safe для совместимости)"""
    return base64.b64encode(data).decode('ascii').rstrip('=')


def upsert_query_param(
    params: Dict[str, str],
    key: str,
    value: str,
    preserve_if_exists: bool = False
) -> None:
    """
    Добавляет или обновляет query параметр.
    
    Args:
        params: Словарь параметров
        key: Ключ параметра
        value: Значение
        preserve_if_exists: Если True и параметр уже есть и не пустой - не перезаписывать
    """
    key_lower = key.lower()
    
    # Проверяем, есть ли уже такой ключ (case-insensitive)
    existing_key = None
    for k in params.keys():
        if k.lower() == key_lower:
            existing_key = k
            break
    
    if existing_key and preserve_if_exists:
        existing_value = params[existing_key]
        if existing_value and existing_value.strip():
            # Сохраняем существующее значение
            return
    
    # Удаляем старый ключ если был
    if existing_key:
        del params[existing_key]
    
    # Добавляем новый
    params[key] = value


def rewrite_vless(link: str, server_cfg: XuiServerConfig) -> str:
    """Переписывает VLESS ссылку"""
    try:
        parsed = urlparse(link)
        
        # Извлекаем UUID и host:port
        auth_part = parsed.netloc
        if '@' not in auth_part:
            return link
        
        uuid, host_port = auth_part.split('@', 1)
        if ':' in host_port:
            host, port_str = host_port.rsplit(':', 1)
            port = int(port_str) if port_str.isdigit() else 443
        else:
            host = host_port
            port = 443
        
        # Проверяем, нужно ли переписывать
        if not is_reverse_proxy_host(host, server_cfg):
            return link
        
        # Парсим query параметры
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        
        # Сохраняем security и sni если они уже есть
        has_security = 'security' in query_params and query_params['security'].strip()
        has_sni = 'sni' in query_params and query_params['sni'].strip()
        
        # Заменяем host и port
        new_netloc = f"{uuid}@{server_cfg.public_host}:{server_cfg.public_port}"
        
        # Добавляем security и sni если их нет
        if not has_security:
            upsert_query_param(query_params, 'security', 'tls')
        if not has_sni:
            upsert_query_param(query_params, 'sni', server_cfg.public_host)
        
        # Специфичные правила для xhttp
        link_type = query_params.get('type', '').lower()
        if link_type == 'xhttp':
            upsert_query_param(query_params, 'mode', 'auto', preserve_if_exists=True)
            upsert_query_param(query_params, 'alpn', 'h2', preserve_if_exists=True)
            upsert_query_param(query_params, 'fp', 'chrome', preserve_if_exists=True)
            # Удаляем пустые host и authority
            if 'host' in query_params and not query_params['host'].strip():
                del query_params['host']
            if 'authority' in query_params and not query_params['authority'].strip():
                del query_params['authority']
        
        # Собираем новую ссылку
        new_query = urlencode(query_params, doseq=False)
        new_link = f"vless://{new_netloc}?{new_query}"
        if parsed.fragment:
            new_link += f"#{parsed.fragment}"
        
        logger.debug(
            f"Rewrite link proto=vless server={server_cfg.server_id} "
            f"{host}:{port} -> {server_cfg.public_host}:{server_cfg.public_port} "
            f"(security/sni {'preserved' if (has_security or has_sni) else 'added'})"
        )
        
        return new_link
    
    except Exception as e:
        logger.warning(f"Failed to rewrite VLESS link: {e}")
        return link


def rewrite_trojan(link: str, server_cfg: XuiServerConfig) -> str:
    """Переписывает Trojan ссылку"""
    try:
        parsed = urlparse(link)
        
        # Trojan формат: trojan://password@host:port?...#name
        auth_part = parsed.netloc
        if '@' not in auth_part:
            return link
        
        password, host_port = auth_part.split('@', 1)
        if ':' in host_port:
            host, port_str = host_port.rsplit(':', 1)
            port = int(port_str) if port_str.isdigit() else 443
        else:
            host = host_port
            port = 443
        
        # Проверяем, нужно ли переписывать
        if not is_reverse_proxy_host(host, server_cfg):
            return link
        
        # Парсим query параметры
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        
        # Сохраняем security и sni если они уже есть
        has_security = 'security' in query_params and query_params['security'].strip()
        has_sni = 'sni' in query_params and query_params['sni'].strip()
        
        # Заменяем host и port
        new_netloc = f"{password}@{server_cfg.public_host}:{server_cfg.public_port}"
        
        # Добавляем security и sni если их нет
        if not has_security:
            upsert_query_param(query_params, 'security', 'tls')
        if not has_sni:
            upsert_query_param(query_params, 'sni', server_cfg.public_host)
        
        # Собираем новую ссылку
        new_query = urlencode(query_params, doseq=False) if query_params else ''
        new_link = f"trojan://{new_netloc}"
        if new_query:
            new_link += f"?{new_query}"
        if parsed.fragment:
            new_link += f"#{parsed.fragment}"
        
        logger.debug(
            f"Rewrite link proto=trojan server={server_cfg.server_id} "
            f"{host}:{port} -> {server_cfg.public_host}:{server_cfg.public_port} "
            f"(security/sni {'preserved' if (has_security or has_sni) else 'added'})"
        )
        
        return new_link
    
    except Exception as e:
        logger.warning(f"Failed to rewrite Trojan link: {e}")
        return link


def rewrite_ss(link: str, server_cfg: XuiServerConfig) -> str:
    """Переписывает Shadowsocks ссылку"""
    try:
        # SS может быть в разных форматах:
        # a) ss://BASE64(method:password)@host:port#name
        # b) ss://BASE64(method:password@host:port)#name
        # c) ss://method:password@host:port#name
        
        parsed = urlparse(link)
        
        # Пробуем формат с @
        if '@' in parsed.netloc:
            # Формат: ss://BASE64(method:password)@host:port или ss://method:password@host:port
            auth_part = parsed.netloc
            userinfo, host_port = auth_part.split('@', 1)
            
            if ':' in host_port:
                host, port_str = host_port.rsplit(':', 1)
                port = int(port_str) if port_str.isdigit() else 443
            else:
                host = host_port
                port = 443
            
            # Проверяем, нужно ли переписывать
            if not is_reverse_proxy_host(host, server_cfg):
                return link
            
            # Заменяем host и port
            new_netloc = f"{userinfo}@{server_cfg.public_host}:{server_cfg.public_port}"
            
            # Парсим query (обычно plugin=...)
            query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            
            # Для SS security/sni обычно не нужны, но если есть - сохраняем
            has_security = 'security' in query_params and query_params['security'].strip()
            has_sni = 'sni' in query_params and query_params['sni'].strip()
            
            if not has_security and not has_sni:
                # Добавляем только если в query есть другие параметры
                pass
            
            # Собираем новую ссылку
            new_query = urlencode(query_params, doseq=False) if query_params else ''
            new_link = f"ss://{new_netloc}"
            if new_query:
                new_link += f"?{new_query}"
            if parsed.fragment:
                new_link += f"#{parsed.fragment}"
            
            logger.debug(
                f"Rewrite link proto=ss server={server_cfg.server_id} "
                f"{host}:{port} -> {server_cfg.public_host}:{server_cfg.public_port}"
            )
            
            return new_link
        
        else:
            # Формат: ss://BASE64(method:password@host:port)#name
            # Нужно декодировать base64 часть
            base64_part = parsed.netloc
            
            decoded = safe_b64_decode(base64_part)
            if not decoded:
                return link
            
            try:
                decoded_str = decoded.decode('utf-8')
            except UnicodeDecodeError:
                return link
            
            # Формат: method:password@host:port
            if '@' not in decoded_str:
                return link
            
            userinfo, host_port = decoded_str.split('@', 1)
            if ':' in host_port:
                host, port_str = host_port.rsplit(':', 1)
                port = int(port_str) if port_str.isdigit() else 443
            else:
                host = host_port
                port = 443
            
            # Проверяем, нужно ли переписывать
            if not is_reverse_proxy_host(host, server_cfg):
                return link
            
            # Заменяем host и port
            new_decoded_str = f"{userinfo}@{server_cfg.public_host}:{server_cfg.public_port}"
            new_base64 = safe_b64_encode(new_decoded_str.encode('utf-8'))
            
            # Собираем новую ссылку
            new_link = f"ss://{new_base64}"
            if parsed.fragment:
                new_link += f"#{parsed.fragment}"
            
            logger.debug(
                f"Rewrite link proto=ss server={server_cfg.server_id} "
                f"{host}:{port} -> {server_cfg.public_host}:{server_cfg.public_port}"
            )
            
            return new_link
    
    except Exception as e:
        logger.warning(f"Failed to rewrite SS link: {e}")
        return link


def rewrite_vmess(link: str, server_cfg: XuiServerConfig) -> str:
    """Переписывает VMESS ссылку"""
    try:
        # VMESS формат: vmess://BASE64(JSON)
        if not link.startswith('vmess://'):
            return link
        
        base64_part = link[8:]  # Убираем "vmess://"
        
        # Декодируем base64
        decoded = safe_b64_decode(base64_part)
        if not decoded:
            return link
        
        try:
            vmess_json = json.loads(decoded.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Failed to parse VMESS JSON: {e}")
            return link
        
        # Проверяем, нужно ли переписывать
        add = vmess_json.get('add', '')
        if not is_reverse_proxy_host(add, server_cfg):
            return link
        
        # Сохраняем tls и sni если они уже есть
        has_tls = 'tls' in vmess_json and vmess_json['tls'] and vmess_json['tls'] not in ('none', '')
        has_sni = 'sni' in vmess_json and vmess_json['sni'] and vmess_json['sni'].strip()
        
        # Заменяем add и port
        vmess_json['add'] = server_cfg.public_host
        vmess_json['port'] = server_cfg.public_port
        
        # Добавляем tls и sni если их нет
        if not has_tls:
            vmess_json['tls'] = 'tls'
        if not has_sni:
            vmess_json['sni'] = server_cfg.public_host
        
        # Кодируем обратно в base64
        new_json_str = json.dumps(vmess_json, separators=(',', ':'), ensure_ascii=False)
        new_base64 = safe_b64_encode(new_json_str.encode('utf-8'))
        
        new_link = f"vmess://{new_base64}"
        
        logger.debug(
            f"Rewrite link proto=vmess server={server_cfg.server_id} "
            f"{add}:{vmess_json.get('port', '?')} -> {server_cfg.public_host}:{server_cfg.public_port} "
            f"(tls/sni {'preserved' if (has_tls or has_sni) else 'added'})"
        )
        
        return new_link
    
    except Exception as e:
        logger.warning(f"Failed to rewrite VMESS link: {e}")
        return link


def rewrite_proxy_links(link: str, server_cfg: XuiServerConfig) -> str:
    """
    Главная функция переписывания ссылок для reverse proxy контуров.
    
    Определяет протокол и вызывает соответствующую функцию переписывания.
    
    Args:
        link: Ссылка для переписывания
        server_cfg: Конфигурация сервера X-UI с публичными параметрами
    
    Returns:
        Переписанная ссылка или исходная, если переписывание не требуется
    """
    if not link or not server_cfg or not server_cfg.public_host:
        return link
    
    link_lower = link.lower()
    
    if link_lower.startswith('vless://'):
        return rewrite_vless(link, server_cfg)
    elif link_lower.startswith('trojan://'):
        return rewrite_trojan(link, server_cfg)
    elif link_lower.startswith('ss://'):
        return rewrite_ss(link, server_cfg)
    elif link_lower.startswith('vmess://'):
        return rewrite_vmess(link, server_cfg)
    else:
        # Неизвестный протокол - возвращаем как есть
        return link
