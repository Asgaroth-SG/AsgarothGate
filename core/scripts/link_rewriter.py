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
        link_host_rewrite_from: str = "127.0.0.1",
        sni: Optional[str] = None,
        xhttp_alpn: Optional[str] = "h2",
        xhttp_fp: Optional[str] = "chrome",
        xhttp_mode: Optional[str] = "auto",
        grpc_authority: Optional[str] = None
    ):
        self.server_id = server_id
        self.public_host = public_host
        self.public_port = public_port
        self.link_host_rewrite_from = link_host_rewrite_from
        self.sni = sni
        self.xhttp_alpn = xhttp_alpn if xhttp_alpn is not None else "h2"
        self.xhttp_fp = xhttp_fp if xhttp_fp is not None else "chrome"
        self.xhttp_mode = xhttp_mode if xhttp_mode is not None else "auto"
        self.grpc_authority = grpc_authority


def _normalize_host_list(value: Any) -> Tuple[str, ...]:
    """Нормализует список хостов для сравнения"""
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        text_value = str(value)
        raw_values = text_value.split(',') if ',' in text_value else [text_value]
    result = []
    for item in raw_values:
        if item is None:
            continue
        normalized = str(item).strip().lower()
        if normalized:
            result.append(normalized)
    return tuple(result)


def is_reverse_proxy_host(host: str, server_cfg: XuiServerConfig) -> bool:
    """Проверяет, является ли хост внутренним адресом для переписывания"""
    if not host:
        return False
    host_normalized = host.strip().lower()
    rewrite_hosts = _normalize_host_list(server_cfg.link_host_rewrite_from)
    return host_normalized in rewrite_hosts or host_normalized in ("127.0.0.1", "localhost")


def is_public_gateway_host(host: str, server_cfg: XuiServerConfig) -> bool:
    """Проверяет, является ли хост публичным gateway сервера"""
    if not host or not server_cfg.public_host:
        return False
    return host.strip().lower() == server_cfg.public_host.strip().lower()


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
    """
    Переписывает VLESS ссылку для reverse proxy контуров.
    
    Правила:
    - Переписывает только если host == 127.0.0.1 (или link_host_rewrite_from)
    - Сохраняет security/sni если они уже заданы и не пустые
    - Добавляет security=tls и sni=public_host (или sni из конфига) если их нет
    - Для type=xhttp добавляет mode/alpn/fp из конфига если их нет
    - Для type=grpc может переопределять authority из конфига (включая пустое)
    - Если authority совпадает с serviceName и override не задан, очищает authority
    - Удаляет пустые параметры (host=, authority=) если не требуется сохранить пустой authority
    - Сохраняет fragment (#name) как есть
    """
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
        
        # Проверяем, нужно ли переписывать (внутренний хост или уже публичный)
        if not (is_reverse_proxy_host(host, server_cfg) or is_public_gateway_host(host, server_cfg)):
            return link
        
        # Сохраняем оригинальные закодированные значения всех параметров до декодирования
        # Это нужно для сохранения точного формата (особенно для path и serviceName)
        original_encoded_params = {}  # key_lower -> (original_key, encoded_value)
        original_key_mapping = {}  # key_lower -> original_key (для сохранения регистра)
        if parsed.query:
            for part in parsed.query.split('&'):
                if '=' in part:
                    key, value = part.split('=', 1)
                    key_lower = key.lower()
                    # Сохраняем оригинальный ключ для всех параметров
                    original_key_mapping[key_lower] = key
                    # Сохраняем оригинальное закодированное значение для важных параметров
                    # НЕ сохраняем пустые host и authority (они будут удалены)
                    if key_lower in ('path', 'servicename'):
                        # Всегда сохраняем path и serviceName
                        original_encoded_params[key_lower] = (key, value)  # (original_key, encoded_value)
                    elif key_lower == 'authority':
                        # Сохраняем authority только если он не пустой
                        if value and value.strip():
                            original_encoded_params[key_lower] = (key, value)
        
        # Парсим query параметры (parse_qsl декодирует значения)
        # Используем case-sensitive парсинг для сохранения регистра ключей
        query_params_list = parse_qsl(parsed.query, keep_blank_values=True)
        query_params = {}
        for key, value in query_params_list:
            key_lower = key.lower()
            # Используем оригинальный ключ если он был сохранен
            original_key = original_key_mapping.get(key_lower, key)
            query_params[original_key] = value
        
        # Вспомогательная функция для получения значения с учетом регистра
        def get_param_case_insensitive(key: str, default: str = '') -> str:
            key_lower = key.lower()
            for k, v in query_params.items():
                if k.lower() == key_lower:
                    return v
            return default
        
        # Проверяем security - если none или пустой, будем менять на tls
        current_security = get_param_case_insensitive('security', '').strip().lower()
        has_valid_security = current_security and current_security not in ('none', '')
        
        # Проверяем sni
        current_sni = get_param_case_insensitive('sni', '').strip()
        has_valid_sni = bool(current_sni)
        sni_value = (server_cfg.sni or server_cfg.public_host or '').strip()
        
        # Заменяем host и port
        new_netloc = f"{uuid}@{server_cfg.public_host}:{server_cfg.public_port}"
        
        # Определяем тип сети
        link_type = get_param_case_insensitive('type', '').lower()
        
        # Специфичные правила для xhttp
        if link_type == 'xhttp':
            # Добавляем mode если нет или пустой
            mode_value = get_param_case_insensitive('mode', '')
            mode_setting = (server_cfg.xhttp_mode or '').strip()
            if mode_setting and (not mode_value or not mode_value.strip()):
                mode_key = original_key_mapping.get('mode', 'mode')
                query_params[mode_key] = mode_setting
            # Добавляем alpn если нет или пустой
            alpn_value = get_param_case_insensitive('alpn', '')
            alpn_setting = (server_cfg.xhttp_alpn or '').strip()
            if alpn_setting and (not alpn_value or not alpn_value.strip()):
                alpn_key = original_key_mapping.get('alpn', 'alpn')
                query_params[alpn_key] = alpn_setting
            # Добавляем fp если нет или пустой
            fp_value = get_param_case_insensitive('fp', '')
            fp_setting = (server_cfg.xhttp_fp or '').strip()
            if fp_setting and (not fp_value or not fp_value.strip()):
                fp_key = original_key_mapping.get('fp', 'fp')
                query_params[fp_key] = fp_setting
        
        # Специфичные правила для grpc
        keep_empty_authority = False
        if link_type == 'grpc':
            authority_value = get_param_case_insensitive('authority', '')
            service_name_value = get_param_case_insensitive('serviceName', '')
            authority_key = original_key_mapping.get('authority', 'authority')
            if server_cfg.grpc_authority is not None:
                # Явная настройка authority из конфига (включая пустое)
                keep_empty_authority = True
                authority_setting = str(server_cfg.grpc_authority).strip()
                if (
                    authority_setting
                    and service_name_value
                    and authority_setting.strip() == service_name_value.strip()
                ):
                    # authority совпадает с serviceName - очищаем как избыточный
                    query_params[authority_key] = ''
                else:
                    query_params[authority_key] = authority_setting
                # Не используем оригинально закодированное authority, если оно было
                original_encoded_params.pop('authority', None)
            elif (
                authority_value
                and service_name_value
                and authority_value.strip() == service_name_value.strip()
            ):
                # authority совпадает с serviceName - очищаем как избыточный
                keep_empty_authority = True
                query_params[authority_key] = ''
                original_encoded_params.pop('authority', None)
            else:
                authority_setting = (server_cfg.grpc_authority or '').strip()
                if authority_setting and (not authority_value or not authority_value.strip()):
                    query_params[authority_key] = authority_setting
        
        # Устанавливаем security=tls если не было валидного значения (НЕ перетираем существующее)
        if not has_valid_security:
            security_key = original_key_mapping.get('security', 'security')
            upsert_query_param(query_params, security_key, 'tls', preserve_if_exists=False)
        
        # Устанавливаем sni если не было (НЕ перетираем существующее)
        if not has_valid_sni and sni_value:
            sni_key = original_key_mapping.get('sni', 'sni')
            upsert_query_param(query_params, sni_key, sni_value, preserve_if_exists=False)
        
        # Удаляем пустые/бесполезные параметры (host=, authority=)
        keys_to_remove = []
        for key, value in query_params.items():
            key_lower = key.lower()
            if key_lower == 'authority' and keep_empty_authority:
                continue
            if key_lower in ('host', 'authority') and (not value or not value.strip()):
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del query_params[key]
        
        # Собираем query string, сохраняя оригинальные закодированные значения для важных параметров
        query_parts = []
        # Сначала добавляем все параметры из original_encoded_params (важные параметры)
        # Это гарантирует, что path и serviceName сохраняются точно как были
        # Пустые authority уже не попадут сюда благодаря проверке выше
        used_keys = set()
        for key_lower, (original_key, encoded_value) in original_encoded_params.items():
            # Пропускаем пустые значения (дополнительная проверка)
            if encoded_value and encoded_value.strip():
                # Добавляем параметр с оригинальным ключом и закодированным значением
                query_parts.append(f"{original_key}={encoded_value}")
                used_keys.add(key_lower)
        
        # Затем добавляем остальные параметры из query_params
        # Пропускаем те, которые уже были добавлены из original_encoded_params
        for key, value in query_params.items():
            key_lower = key.lower()
            # Пропускаем параметры, которые уже были добавлены из original_encoded_params
            if key_lower not in used_keys:
                # Для остальных параметров кодируем через quote
                encoded_key = quote(str(key), safe='')
                encoded_value = quote(str(value), safe='')
                query_parts.append(f"{encoded_key}={encoded_value}")
        
        new_query = '&'.join(query_parts)
        new_link = f"vless://{new_netloc}?{new_query}"
        
        # Сохраняем fragment как есть (он уже URL-encoded)
        if parsed.fragment:
            new_link += f"#{parsed.fragment}"
        
        logger.debug(
            f"Normalized VLESS link server={server_cfg.server_id} "
            f"{host}:{port} -> {server_cfg.public_host}:{server_cfg.public_port} "
            f"(security={'preserved' if has_valid_security else 'set to tls'}, "
            f"sni={'preserved' if has_valid_sni else 'added'})"
        )
        
        return new_link
    
    except Exception as e:
        logger.warning(f"Failed to rewrite VLESS link: {e}", exc_info=True)
        return link


def rewrite_trojan(link: str, server_cfg: XuiServerConfig) -> str:
    """
    Переписывает Trojan ссылку для reverse proxy контуров.
    
    Правила:
    - Переписывает только если host == 127.0.0.1 (или link_host_rewrite_from)
    - Сохраняет security/sni если они уже заданы и не пустые
    - Добавляет security=tls и sni=public_host если их нет
    - Сохраняет fragment (#name) как есть
    """
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
        
        # Проверяем security и sni - сохраняем если уже есть и не пустые
        current_security = query_params.get('security', '').strip().lower()
        has_valid_security = current_security and current_security not in ('none', '')
        
        current_sni = query_params.get('sni', '').strip()
        has_valid_sni = bool(current_sni)
        
        # Заменяем host и port
        new_netloc = f"{password}@{server_cfg.public_host}:{server_cfg.public_port}"
        
        # Добавляем security и sni если их нет (НЕ перетираем существующие)
        if not has_valid_security:
            upsert_query_param(query_params, 'security', 'tls', preserve_if_exists=False)
        if not has_valid_sni:
            upsert_query_param(query_params, 'sni', server_cfg.public_host, preserve_if_exists=False)
        
        # Собираем новую ссылку используя urlencode
        query_parts = []
        for key, value in query_params.items():
            encoded_key = quote(str(key), safe='')
            encoded_value = quote(str(value), safe='')
            query_parts.append(f"{encoded_key}={encoded_value}")
        
        new_query = '&'.join(query_parts) if query_parts else ''
        new_link = f"trojan://{new_netloc}"
        if new_query:
            new_link += f"?{new_query}"
        if parsed.fragment:
            new_link += f"#{parsed.fragment}"
        
        logger.debug(
            f"Rewrite link proto=trojan server={server_cfg.server_id} "
            f"{host}:{port} -> {server_cfg.public_host}:{server_cfg.public_port} "
            f"(security={'preserved' if has_valid_security else 'set to tls'}, "
            f"sni={'preserved' if has_valid_sni else 'added'})"
        )
        
        return new_link
    
    except Exception as e:
        logger.warning(f"Failed to rewrite Trojan link: {e}", exc_info=True)
        return link


def rewrite_ss(link: str, server_cfg: XuiServerConfig) -> str:
    """
    Переписывает Shadowsocks ссылку для reverse proxy контуров.
    
    Поддерживает форматы:
    - ss://BASE64(method:password)@host:port#name
    - ss://BASE64(method:password@host:port)#name
    - ss://method:password@host:port#name
    
    Правила:
    - Переписывает только если host == 127.0.0.1 (или link_host_rewrite_from)
    - Сохраняет query параметры (plugin=...) если есть
    - Сохраняет fragment (#name) как есть
    """
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
            
            # Собираем новую ссылку
            query_parts = []
            for key, value in query_params.items():
                encoded_key = quote(str(key), safe='')
                encoded_value = quote(str(value), safe='')
                query_parts.append(f"{encoded_key}={encoded_value}")
            
            new_query = '&'.join(query_parts) if query_parts else ''
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
            
            # Парсим query если есть
            query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query_parts = []
            for key, value in query_params.items():
                encoded_key = quote(str(key), safe='')
                encoded_value = quote(str(value), safe='')
                query_parts.append(f"{encoded_key}={encoded_value}")
            
            new_query = '&'.join(query_parts) if query_parts else ''
            
            # Собираем новую ссылку
            new_link = f"ss://{new_base64}"
            if new_query:
                new_link += f"?{new_query}"
            if parsed.fragment:
                new_link += f"#{parsed.fragment}"
            
            logger.debug(
                f"Rewrite link proto=ss server={server_cfg.server_id} "
                f"{host}:{port} -> {server_cfg.public_host}:{server_cfg.public_port}"
            )
            
            return new_link
    
    except Exception as e:
        logger.warning(f"Failed to rewrite SS link: {e}", exc_info=True)
        return link


def rewrite_vmess(link: str, server_cfg: XuiServerConfig) -> str:
    """
    Переписывает VMESS ссылку для reverse proxy контуров.
    
    Формат: vmess://BASE64(JSON)
    
    Правила:
    - Переписывает только если add == 127.0.0.1 (или link_host_rewrite_from)
    - Сохраняет tls/sni если они уже заданы и не пустые
    - Добавляет tls=tls и sni=public_host если их нет
    """
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
        
        # Сохраняем tls и sni если они уже есть и не пустые
        current_tls = vmess_json.get('tls', '')
        has_valid_tls = bool(current_tls) and str(current_tls).strip().lower() not in ('none', '')
        
        current_sni = vmess_json.get('sni', '')
        has_valid_sni = bool(current_sni) and str(current_sni).strip()
        
        # Сохраняем оригинальный port для логирования
        original_port = vmess_json.get('port', '?')
        
        # Заменяем add и port (port должен быть строкой для VMESS)
        vmess_json['add'] = server_cfg.public_host
        vmess_json['port'] = str(server_cfg.public_port)
        
        # Добавляем tls и sni если их нет (НЕ перетираем существующие)
        if not has_valid_tls:
            vmess_json['tls'] = 'tls'
        if not has_valid_sni:
            vmess_json['sni'] = server_cfg.public_host
        
        # Кодируем обратно в base64
        new_json_str = json.dumps(vmess_json, separators=(',', ':'), ensure_ascii=False)
        new_base64 = safe_b64_encode(new_json_str.encode('utf-8'))
        
        new_link = f"vmess://{new_base64}"
        
        logger.debug(
            f"Rewrite link proto=vmess server={server_cfg.server_id} "
            f"{add}:{original_port} -> {server_cfg.public_host}:{server_cfg.public_port} "
            f"(tls={'preserved' if has_valid_tls else 'set to tls'}, "
            f"sni={'preserved' if has_valid_sni else 'added'})"
        )
        
        return new_link
    
    except Exception as e:
        logger.warning(f"Failed to rewrite VMESS link: {e}", exc_info=True)
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
