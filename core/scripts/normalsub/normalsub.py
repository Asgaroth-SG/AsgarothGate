import os
import json
import subprocess
import re
import time
import threading
import shlex
import base64
import sys
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from io import BytesIO

from aiohttp import web
from aiohttp.web_middlewares import middleware
from urllib.parse import unquote, parse_qs, urlparse, urljoin, quote, urlencode
from dotenv import load_dotenv
import qrcode
from jinja2 import Environment, FileSystemLoader

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from db.database import db

# Импортируем LinkRewriter
from link_rewriter import rewrite_proxy_links, XuiServerConfig as LinkRewriterServerConfig

load_dotenv()

# Настраиваем базовое логирование для normalsub
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
        logging.FileHandler('/var/log/hysteria_normalsub.log', encoding='utf-8')  # Вывод в файл
    ]
)

logger = logging.getLogger(__name__)

# Настраиваем логирование для X-UI модулей при импорте
try:
    from xui.logging_config import setup_xui_logging
    setup_xui_logging()
except Exception as e:
    logger.warning(f"Failed to setup X-UI logging: {e}")


@dataclass
class AppConfig:
    domain: str
    external_port: int
    aiohttp_listen_address: str
    aiohttp_listen_port: int
    sni_file: str
    singbox_template_path: str
    hysteria_cli_path: str
    nodes_json_path: str
    extra_config_path: str
    rate_limit: int
    rate_limit_window: int
    sni: str
    template_dir: str
    subpath: str
    public_host: Optional[str] = None  # Публичный хост для нормализации VLESS ссылок
    public_port: int = 443  # Публичный порт для нормализации VLESS ссылок


class RateLimiter:
    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self.store: Dict[str, Tuple[int, float]] = {}

    def check_limit(self, client_ip: str) -> bool:
        current_time = time.monotonic()
        requests, last_request_time = self.store.get(client_ip, (0, 0))
        if current_time - last_request_time < self.window:
            if requests >= self.limit:
                return False
        else:
            requests = 0
        self.store[client_ip] = (requests + 1, current_time)
        return True


@dataclass
class UriComponents:
    username: Optional[str]
    password: Optional[str]
    ip: Optional[str]
    port: Optional[int]
    obfs_password: str


@dataclass
class UserInfo:
    username: str
    password: str
    upload_bytes: int
    download_bytes: int
    max_download_bytes: int
    account_creation_date: str
    expiration_days: int
    blocked: bool = False
    plan: str = "standard"
    block_reason: Optional[str] = None  # "traffic" или "expiration"

    @property
    def total_usage(self) -> int:
        return self.upload_bytes + self.download_bytes

    @property
    def expiration_timestamp(self) -> int:
        if not self.account_creation_date or self.expiration_days <= 0:
            return 0
        creation_timestamp = int(time.mktime(time.strptime(self.account_creation_date, "%Y-%m-%d")))
        return creation_timestamp + (self.expiration_days * 24 * 3600)

    @property
    def expiration_date(self) -> str:
        if not self.account_creation_date or self.expiration_days <= 0:
            return "Ожидает подключения"

        creation_timestamp = int(time.mktime(time.strptime(self.account_creation_date, "%Y-%m-%d")))
        expiration_timestamp = creation_timestamp + (self.expiration_days * 24 * 3600)

        months = [
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ]
        lt = time.localtime(expiration_timestamp)
        day = lt.tm_mday
        month_name = months[lt.tm_mon - 1]
        year = lt.tm_year
        return f"{day} {month_name} {year} г."

    @property
    def usage_human_readable(self) -> str:
        total = Utils.human_readable_bytes(self.max_download_bytes)
        used = Utils.human_readable_bytes(self.total_usage)
        return f"{used} / {total}"

    @property
    def usage_detailed(self) -> str:
        total = Utils.human_readable_bytes(self.max_download_bytes)
        upload = Utils.human_readable_bytes(self.upload_bytes)
        download = Utils.human_readable_bytes(self.download_bytes)
        return f"Upload: {upload}, Download: {download}, Total: {total}"


@dataclass
class NodeURI:
    label: str
    uri: str
    qrcode: Optional[str] = None


@dataclass
class TemplateContext:
    username: str
    usage: str
    usage_raw: str
    expiration_date: str
    sublink_qrcode: str
    sub_link: str
    sub_link_encoded: str
    blocked: bool = False
    local_uris: List[NodeURI] = field(default_factory=list)
    node_uris: List[NodeURI] = field(default_factory=list)
    singbox_qrcode: Optional[str] = None
    hiddify_qrcode: Optional[str] = None
    streisand_qrcode: Optional[str] = None
    nekobox_qrcode: Optional[str] = None


class Utils:
    @staticmethod
    def sanitize_input(value: str, pattern: str) -> str:
        if not re.match(pattern, value):
            raise ValueError(f"Invalid value: {value}")
        return shlex.quote(value)

    @staticmethod
    def generate_qrcode_base64(data: str) -> str:
        if not data:
            return None
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode()

    @staticmethod
    def human_readable_bytes(bytes_value: int) -> str:
        units = ["Bytes", "KB", "MB", "GB", "TB"]
        size = float(bytes_value)
        for unit in units:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

    @staticmethod
    def build_url(base: str, path: str) -> str:
        return urljoin(base, path)

    @staticmethod
    def is_valid_url(url: str) -> bool:
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    @staticmethod
    def normalize_plan(value: Optional[str]) -> str:
        v = str(value or "standard").strip().lower()
        return "premium" if v == "premium" else "standard"


class HysteriaCLI:
    def __init__(self, cli_path: str):
        self.cli_path = cli_path

    def _run_command(self, args: List[str]) -> str:
        try:
            command = ['python3', self.cli_path] + args
            logger.info(f"Running command: {' '.join(command)}")
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                if "User not found" in stderr:
                    logger.warning(f"User not found in command: {' '.join(command)}")
                    return None
                else:
                    logger.error(f"Hysteria CLI error (command: {' '.join(command)}): returncode={process.returncode}, stderr={stderr}, stdout={stdout[:200]}")
                    print(f"Hysteria CLI error: {stderr}")
                    raise subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)
            result = stdout.strip()
            if not result:
                logger.warning(f"Empty output from command: {' '.join(command)}, stderr: {stderr[:200] if stderr else 'None'}")
            else:
                logger.info(f"Command succeeded, output length: {len(result)} chars")
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Hysteria CLI error: {e}, stdout: {e.stdout[:200] if e.stdout else 'None'}, stderr: {e.stderr[:200] if e.stderr else 'None'}")
            print(f"Hysteria CLI error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error running command {' '.join(command)}: {e}", exc_info=True)
            raise

    def get_username_by_password(self, password_token: str) -> Optional[str]:
        if not db:
            return None
        user_doc = db.collection.find_one({"password": password_token}, {"_id": 1})
        return user_doc['_id'] if user_doc else None

    def get_user_info(self, username: str) -> Optional[UserInfo]:
        if not db:
            return None
        user_doc = db.get_user(username)
        if not user_doc:
            return None

        return UserInfo(
            username=user_doc.get('_id'),
            password=user_doc.get('password'),
            upload_bytes=user_doc.get('upload_bytes', 0),
            download_bytes=user_doc.get('download_bytes', 0),
            max_download_bytes=user_doc.get('max_download_bytes', 0),
            account_creation_date=user_doc.get('account_creation_date', ''),
            expiration_days=user_doc.get('expiration_days', 0),
            blocked=user_doc.get('blocked', False),
            plan=user_doc.get('plan', 'standard'),
            block_reason=user_doc.get('block_reason', None),
        )

    def get_all_uris(self, username: str) -> List[str]:
        output = self._run_command(['show-user-uri', '-u', username, '-a'])
        if not output:
            return []
        return re.findall(r'hy2://.*', output)

    def get_all_labeled_uris(self, username: str) -> List[Dict[str, str]]:
        logger.info(f"Getting labeled URIs for user {username}")
        output = self._run_command(['show-user-uri', '-u', username, '-a'])
        if not output:
            logger.warning(f"No output from show-user-uri for user {username}")
            return []
        
        logger.info(f"show-user-uri output length: {len(output)} chars, preview: {output[:200]}")

        # Парсим вывод в формате:
        # Label:
        # hy2://...
        # или
        # Label: hy2://...
        # 
        # Используем более гибкое регулярное выражение, которое обрабатывает:
        # 1. Label: hy2://... (на одной строке)
        # 2. Label:\nhy2://... (на разных строках)
        # 3. Label:\n\nhy2://... (с пустой строкой между)
        
        # Сначала пробуем формат на одной строке
        matches = re.findall(r"^([^\n:]+?):\s*(hy2://[^\s\n]+)", output, re.MULTILINE)
        
        # Если не нашли, пробуем формат с переносом строки
        if not matches:
            # Ищем паттерн: Label:\n(возможно пустые строки)\nhy2://...
            pattern = r"^([^\n:]+?):\s*\n\s*(hy2://[^\n]+)"
            matches = re.findall(pattern, output, re.MULTILINE)
        
        # Если всё ещё не нашли, пробуем более простой подход - ищем все hy2:// ссылки
        # и пытаемся найти соответствующие метки перед ними
        if not matches:
            # Находим все hy2:// ссылки
            uri_lines = re.findall(r"^(hy2://[^\n]+)", output, re.MULTILINE)
            # Находим все метки (строки, заканчивающиеся на :)
            label_lines = re.findall(r"^([^\n:]+?):\s*$", output, re.MULTILINE)
            
            # Сопоставляем метки и URI по порядку
            if uri_lines and label_lines:
                # Берем минимальное количество для сопоставления
                min_count = min(len(uri_lines), len(label_lines))
                matches = [(label_lines[i], uri_lines[i]) for i in range(min_count)]
        
        if not matches:
            # Если всё ещё нет совпадений, логируем вывод для отладки
            logger.warning(f"Could not parse URIs from show-user-uri output for {username}. Output preview: {output[:500]}")
            # Пробуем найти хотя бы hy2:// ссылки без меток
            uri_lines = re.findall(r"hy2://[^\s\n]+", output)
            if uri_lines:
                logger.info(f"Found {len(uri_lines)} hy2:// URIs without labels, using default label")
                matches = [("Hysteria2", uri) for uri in uri_lines]
            else:
                logger.error(f"No hy2:// URIs found in output for {username}. Full output: {output}")
        
        result = []
        for label, uri in matches:
            cleaned_label = label.strip()
            cleaned_uri = uri.strip()
            logger.info(f"Processing match: label='{cleaned_label}', uri_length={len(cleaned_uri)}, uri_preview='{cleaned_uri[:100]}'")
            if cleaned_uri:
                result.append({'label': cleaned_label, 'uri': cleaned_uri})
            else:
                logger.warning(f"Skipping match with empty URI, label='{cleaned_label}'")
        
        logger.info(f"Parsed {len(result)} labeled URIs for {username}")
        if result:
            for r in result:
                logger.info(f"Final parsed URI: label='{r['label']}', uri_length={len(r['uri'])}, uri_preview='{r['uri'][:100]}'")
        else:
            logger.warning(f"No valid URIs parsed from {len(matches)} matches for {username}")
        return result


class UriParser:
    @staticmethod
    def extract_uri_components(uri: Optional[str], prefix: str) -> Optional[UriComponents]:
        if not uri or not uri.startswith(prefix):
            return None
        uri = uri[len(prefix):].strip()
        try:
            decoded_uri = unquote(uri)
            parsed_url = urlparse(decoded_uri)
            query_params = parse_qs(parsed_url.query)
            hostname = parsed_url.hostname
            if hostname and hostname.startswith('[') and hostname.endswith(']'):
                hostname = hostname[1:-1]
            port = parsed_url.port if parsed_url.port is not None else None
            return UriComponents(
                username=parsed_url.username,
                password=parsed_url.password,
                ip=hostname,
                port=port,
                obfs_password=query_params.get('obfs-password', [''])[0]
            )
        except Exception as e:
            print(f"Error during URI parsing: {e}, URI: {uri}")
            return None


class SingboxConfigGenerator:
    def __init__(self, hysteria_cli: HysteriaCLI, default_sni: str):
        self.hysteria_cli = hysteria_cli
        self.default_sni = default_sni
        self._template_cache = None
        self.template_path = None

    def set_template_path(self, path: str):
        self.template_path = path
        self._template_cache = None

    def get_template(self) -> Dict[str, Any]:
        if self._template_cache is None:
            try:
                with open(self.template_path, 'r') as f:
                    self._template_cache = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError, IOError) as e:
                raise RuntimeError(f"Error loading Singbox template: {e}") from e
        return self._template_cache.copy()

    def generate_config_from_uri(self, uri: str, username: str, fragment: str) -> Optional[Dict[str, Any]]:
        if not uri:
            return None

        try:
            parsed_url = urlparse(uri)
            server = parsed_url.hostname
            server_port = parsed_url.port
            auth_password = parsed_url.password
            auth_user = unquote(parsed_url.username or '')
            obfs_password = parse_qs(parsed_url.query).get('obfs-password', [''])[0]

            if auth_password:
                if auth_user:
                    final_password = f"{auth_user}:{auth_password}"
                else:
                    final_password = auth_password
            else:
                final_password = auth_user

        except Exception as e:
            print(f"Error during Singbox config generation from URI: {e}, URI: {uri}")
            return None

        return {
            "type": "hysteria2",
            "tag": unquote(parsed_url.fragment),
            "server": server,
            "server_port": server_port,
            "obfs": {
                "type": "salamander",
                "password": obfs_password
            },
            "password": final_password,
            "tls": {
                "enabled": True,
                "server_name": fragment if fragment else self.default_sni,
                "insecure": True
            }
        }

    def combine_configs(self, all_uris: List[str], username: str, fragment: str) -> Optional[Dict[str, Any]]:
        if not all_uris:
            return None

        combined_config = self.get_template()
        combined_config['outbounds'] = [out for out in combined_config['outbounds'] if out.get('type') != 'hysteria2']

        hysteria_outbounds = []
        for uri in all_uris:
            outbound = self.generate_config_from_uri(uri, username, fragment)
            if outbound:
                hysteria_outbounds.append(outbound)

        if not hysteria_outbounds:
            return None

        all_tags = [out['tag'] for out in hysteria_outbounds]

        for outbound in combined_config['outbounds']:
            if outbound.get('tag') == 'select':
                outbound['outbounds'] = ["auto"] + all_tags
            elif outbound.get('tag') == 'auto':
                outbound['outbounds'] = all_tags

        combined_config['outbounds'].extend(hysteria_outbounds)
        return combined_config


class SubscriptionManager:
    def __init__(self, hysteria_cli: HysteriaCLI, config: AppConfig):
        self.hysteria_cli = hysteria_cli
        self.config = config
        # Кэш VLESS ссылок для ускорения выдачи подписки
        # TTL можно задать через XUI_LINKS_CACHE_TTL (в секундах)
        # Увеличено до 3600 секунд (1 час) для ускорения выдачи подписки
        try:
            self._xui_links_cache_ttl = int(os.getenv('XUI_LINKS_CACHE_TTL', '3600'))
        except Exception:
            self._xui_links_cache_ttl = 3600  # 1 час по умолчанию
        try:
            self._xui_links_cache_max_stale = int(os.getenv('XUI_LINKS_CACHE_MAX_STALE', '86400'))
        except Exception:
            self._xui_links_cache_max_stale = 86400  # 24 часа для stale cache
        self._xui_links_cache_path = os.getenv(
            'XUI_LINKS_CACHE_PATH',
            '/etc/hysteria/xui_links_cache.json'
        )
        self._xui_links_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._xui_links_cache_lock = threading.Lock()
        self._xui_links_refreshing: set[str] = set()
        self._load_xui_links_cache()

    def _xui_links_cache_key(self, username: str, user_plan: str) -> str:
        return f"{username}:{user_plan}"

    def _load_xui_links_cache(self) -> None:
        if not self._xui_links_cache_path:
            return
        try:
            if not os.path.exists(self._xui_links_cache_path):
                return
            with open(self._xui_links_cache_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return
            with self._xui_links_cache_lock:
                for key, entry in raw.items():
                    if not isinstance(entry, dict):
                        continue
                    ts = entry.get('timestamp')
                    links = entry.get('links')
                    if isinstance(ts, (int, float)) and isinstance(links, list):
                        self._xui_links_cache[key] = (float(ts), links)
        except Exception as e:
            logger.debug(f"Failed to load X-UI links cache: {e}")

    def _save_xui_links_cache(self) -> None:
        if not self._xui_links_cache_path:
            return
        try:
            with self._xui_links_cache_lock:
                payload = {
                    key: {
                        "timestamp": ts,
                        "links": links
                    }
                    for key, (ts, links) in self._xui_links_cache.items()
                }
            tmp_path = f"{self._xui_links_cache_path}.tmp"
            os.makedirs(os.path.dirname(self._xui_links_cache_path), exist_ok=True)
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp_path, self._xui_links_cache_path)
        except Exception as e:
            logger.debug(f"Failed to save X-UI links cache: {e}")

    def _refresh_xui_links_async(self, username: str, user_plan: str) -> None:
        cache_key = self._xui_links_cache_key(username, user_plan)
        with self._xui_links_cache_lock:
            if cache_key in self._xui_links_refreshing:
                return
            self._xui_links_refreshing.add(cache_key)

        def _worker():
            try:
                from xui.config import get_xui_sync_manager
                sync_manager = get_xui_sync_manager()
                if not sync_manager:
                    return
                links = sync_manager.get_user_vless_uris(username) or []
                with self._xui_links_cache_lock:
                    self._xui_links_cache[cache_key] = (time.time(), list(links))
                self._save_xui_links_cache()
                logger.debug(
                    f"Background refresh completed for {username} (plan={user_plan})"
                )
            except Exception as e:
                logger.debug(f"Background refresh failed for {username}: {e}")
            finally:
                with self._xui_links_cache_lock:
                    self._xui_links_refreshing.discard(cache_key)

        threading.Thread(target=_worker, daemon=True).start()

    def _load_nodes_types(self) -> Dict[str, str]:
        """
        Считывает nodes.json и строит карту:
        {
            "🇺🇸 США": "standard",
            "📶 LTE": "premium",
            ...
        }
        """
        nodes_map: Dict[str, str] = {}
        try:
            if not os.path.exists(self.config.nodes_json_path):
                return nodes_map
            with open(self.config.nodes_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for node in data:
                    name = str(node.get("name", "")).strip()
                    if not name:
                        continue
                    node_type = Utils.normalize_plan(node.get("type", "standard"))
                    nodes_map[name] = node_type
        except Exception as e:
            print(f"Warning: failed to load nodes from {self.config.nodes_json_path}: {e}")
        return nodes_map

    def _get_extra_configs_raw(self) -> List[Dict[str, Any]]:
        """
        Читает extra.json как список объектов.
        Допускает пустой файл/отсутствие.
        """
        if not os.path.exists(self.config.extra_config_path):
            return []
        try:
            with open(self.config.extra_config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content:
                    return []
                data = json.loads(content)
                if isinstance(data, list):
                    return [x for x in data if isinstance(x, dict)]
                return []
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not read or parse extra configs from {self.config.extra_config_path}: {e}")
            return []

    def _filter_extra_configs_for_user(
        self,
        user_plan: str
    ) -> List[Dict[str, Any]]:
        """
        Возвращает список extra-config элементов, доступных пользователю.
        - Standard: только standard
        - Premium: standard + premium
        Поддерживает поля:
          - type: "standard"/"premium"
          - plan: "standard"/"premium"
        Если поле отсутствует — считаем standard (обратная совместимость).
        """
        user_plan = Utils.normalize_plan(user_plan)
        is_premium_user = (user_plan == "premium")

        allowed: List[Dict[str, Any]] = []
        for item in self._get_extra_configs_raw():
            uri = str(item.get("uri", "")).strip()
            if not uri:
                continue

            item_plan = Utils.normalize_plan(item.get("type") or item.get("plan") or "standard")
            if (not is_premium_user) and item_plan == "premium":
                continue

            allowed.append(item)

        return allowed

    def _get_extra_uris_for_user(self, user_plan: str) -> List[str]:
        return [str(x.get("uri")).strip() for x in self._filter_extra_configs_for_user(user_plan)]

    def _get_default_server_config(self) -> Optional[LinkRewriterServerConfig]:
        """
        Получает дефолтную конфигурацию сервера из первого включенного сервера X-UI.
        Используется для ссылок без явного контекста сервера (Hysteria, extra).
        
        Returns:
            LinkRewriterServerConfig или None если нет настроенных серверов
        """
        try:
            from pathlib import Path
            
            xui_path = Path(__file__).parent.parent / "xui"
            if xui_path.exists():
                sys.path.insert(0, str(xui_path.parent))
                from xui.config import load_xui_config
                
                config = load_xui_config()
                servers = config.get('xui_servers', [])
                
                # Ищем первый включенный сервер с public_host или извлекаем из host
                for server in servers:
                    if not server.get('enabled', True):
                        continue
                    
                    public_host = server.get('public_host')
                    
                    # Если public_host не задан, извлекаем домен из host (для reverse proxy)
                    if not public_host:
                        host_url = server.get('host', '')
                        if host_url:
                            try:
                                parsed = urlparse(host_url)
                                public_host = parsed.hostname
                            except Exception:
                                continue
                    
                    if public_host:
                        return LinkRewriterServerConfig(
                            server_id=server.get('name', 'default'),
                            public_host=public_host,
                            public_port=server.get('public_port', 443),
                            link_host_rewrite_from=server.get('link_host_rewrite_from', '127.0.0.1'),
                            sni=server.get('sni') or public_host,
                            xhttp_alpn=server.get('xhttp_alpn'),
                            xhttp_fp=server.get('xhttp_fp'),
                            xhttp_mode=server.get('xhttp_mode'),
                            grpc_authority=server.get('grpc_authority')
                        )
        except Exception as e:
            print(f"Warning: Failed to get default server config: {e}", file=sys.stderr)
        
        return None

    def _normalize_link(self, uri: str, server_cfg: Optional[LinkRewriterServerConfig] = None) -> str:
        """
        Нормализует ссылку через LinkRewriter.
        
        Args:
            uri: Ссылка для нормализации
            server_cfg: Конфигурация сервера (если None, используется дефолтная)
        
        Returns:
            Нормализованная ссылка
        """
        if not uri:
            return uri
        
        # Если нет конфигурации сервера, пытаемся получить дефолтную
        if not server_cfg:
            server_cfg = self._get_default_server_config()
        
        # Если всё равно нет конфигурации или public_host не задан, возвращаем как есть
        if not server_cfg or not server_cfg.public_host:
            # Логируем только для VLESS ссылок с 127.0.0.1 (чтобы не спамить для других протоколов)
            if uri.startswith('vless://') and '127.0.0.1' in uri:
                if server_cfg:
                    logger.warning(f"Cannot rewrite link - server_cfg exists but public_host is empty. Server: {server_cfg.server_id}, URI: {uri[:80]}...")
                else:
                    logger.warning(f"Cannot rewrite link - no server config. URI: {uri[:80]}...")
            return uri
        
        # Применяем rewrite только если это поддерживаемый протокол
        try:
            rewritten = rewrite_proxy_links(uri, server_cfg)
            # Логируем успешное переписывание для отладки
            if rewritten != uri:
                logger.debug(f"Normalized VLESS link server={server_cfg.server_id} 127.0.0.1 -> {server_cfg.public_host}:{server_cfg.public_port} (security/sni preserved if present)")
            return rewritten
        except Exception as e:
            # Fail-open: при ошибке возвращаем исходную ссылку
            logger.warning(f"Failed to rewrite link {uri[:50]}...: {e}", exc_info=True)
            return uri

    def get_normal_subscription(self, username: str, user_agent: str) -> str:
        """
        Получает нормализованную подписку для пользователя.
        
        Все ссылки проходят через единый pipeline нормализации через LinkRewriter.
        """
        user_info = self.hysteria_cli.get_user_info(username)
        if user_info is None:
            return "User not found"

        user_plan = Utils.normalize_plan(getattr(user_info, "plan", "standard"))
        is_premium_user = (user_plan == "premium")

        nodes_types = self._load_nodes_types()
        labeled_uris = self.hysteria_cli.get_all_labeled_uris(username)
        
        logger.info(f"Retrieved {len(labeled_uris)} labeled URIs for {username}")
        if labeled_uris:
            logger.info(f"Labeled URIs: {[item.get('label') for item in labeled_uris]}")

        # Список ссылок с контекстом (uri, server_cfg)
        links_with_context: List[Tuple[str, Optional[LinkRewriterServerConfig]]] = []

        # Обрабатываем Hysteria ссылки
        hysteria_count = 0
        logger.info(f"Processing {len(labeled_uris)} labeled URIs for {username}")
        for item in labeled_uris:
            label = item.get("label", "")
            uri = item.get("uri", "")
            
            logger.info(f"Processing URI item: label='{label}', uri_length={len(uri) if uri else 0}")

            if not uri:
                logger.warning(f"Skipping item with empty URI, label: {label}")
                continue

            # Проверяем IPv6 более точно: ищем IPv6 адреса в квадратных скобках [::] или метку IPv6
            # НЕ фильтруем по "v6" в URI, так как это может быть часть параметров (например, obfs-password)
            # IPv6 адреса в Hysteria URI всегда в квадратных скобках: hy2://user:pass@[::1]:443
            if "[" in uri:
                # Проверяем, что это действительно IPv6 адрес в квадратных скобках
                # Извлекаем часть между @ и : после квадратных скобок
                try:
                    if "@" in uri:
                        host_part = uri.split("@")[1].split(":")[0]
                        if host_part.startswith("[") and host_part.endswith("]"):
                            # Это IPv6 адрес в квадратных скобках
                            logger.info(f"Skipping IPv6 URI: {label}")
                            continue
                except Exception:
                    pass  # Если не удалось распарсить, пропускаем проверку
            
            # Проверяем метку на наличие IPv6
            if "IPv6" in label or ("v6" in label.lower() and "v4" not in label.lower()):
                # Это явно помечено как IPv6
                logger.info(f"Skipping IPv6 URI by label: {label}")
                continue

            if label.startswith("Node:"):
                node_name = label[len("Node:"):].strip()
                node_type = nodes_types.get(node_name, "standard")
                if (not is_premium_user) and node_type == "premium":
                    logger.info(f"Skipping premium node {node_name} for standard user")
                    continue

            # Обработка v2ray-ng специфичных параметров
            if "v2ray" in user_agent and "ng" in user_agent:
                match = re.search(r'pinSHA256=sha256/([^&]+)', uri)
                if match:
                    decoded = base64.b64decode(match.group(1))
                    formatted = ":".join("{:02X}".format(byte) for byte in decoded)
                    uri = uri.replace(
                        f'pinSHA256=sha256/{match.group(1)}',
                        f'pinSHA256={formatted}'
                    )

            # Hysteria ссылки без явного контекста сервера (используется дефолтный)
            links_with_context.append((uri, None))
            hysteria_count += 1
            logger.info(f"Added Hysteria URI: {label} -> {uri[:80]}...")
        
        logger.info(f"Total Hysteria URIs added: {hysteria_count}, total links_with_context: {len(links_with_context)}")

        # Обрабатываем extra ссылки
        extra_uris = self._get_extra_uris_for_user(user_plan)
        for uri in extra_uris:
            # Extra ссылки без явного контекста сервера
            links_with_context.append((uri, None))

        # Получаем VLESS URIs из 3X-UI для пользователя
        try:
            from pathlib import Path
            xui_path = Path(__file__).parent.parent / "xui"
            if xui_path.exists():
                sys.path.insert(0, str(xui_path.parent))
                from xui.config import get_xui_sync_manager
                
                sync_manager = get_xui_sync_manager()
                if sync_manager:
                    vless_nodes: List[Dict[str, Any]] = []
                    cache_used = False
                    cache_key = self._xui_links_cache_key(username, user_plan)
                    now = time.time()

                    if self._xui_links_cache_ttl > 0:
                        cached = self._xui_links_cache.get(cache_key)
                        if cached:
                            cached_at, cached_links = cached
                            age = now - cached_at
                            if age < self._xui_links_cache_ttl:
                                vless_nodes = cached_links
                                cache_used = True
                                logger.debug(
                                    f"Using cached X-UI links for {username} (ttl={self._xui_links_cache_ttl}s)"
                                )
                            elif self._xui_links_cache_max_stale > 0 and age < self._xui_links_cache_max_stale:
                                # Используем устаревший кэш, но всё равно обновляем в фоне
                                vless_nodes = cached_links
                                cache_used = True
                                logger.debug(
                                    f"Using stale X-UI links for {username} "
                                    f"(age={int(age)}s, max_stale={self._xui_links_cache_max_stale}s)"
                                )
                                # Обновляем в фоне без блокировки
                                self._refresh_xui_links_async(username, user_plan)

                    if not cache_used:
                        # Cache miss в памяти - перечитываем файл кэша
                        # (он мог быть обновлён при создании пользователя)
                        logger.debug(f"Cache miss in memory for {username}, reloading cache file...")
                        self._load_xui_links_cache()
                        
                        # Проверяем кэш снова после перезагрузки файла
                        cached = self._xui_links_cache.get(cache_key)
                        if cached:
                            cached_at, cached_links = cached
                            age = now - cached_at
                            if age < self._xui_links_cache_max_stale:
                                vless_nodes = cached_links
                                cache_used = True
                                logger.debug(
                                    f"Found links in cache file for {username} "
                                    f"(age={int(age)}s, links={len(cached_links)})"
                                )
                                # Если кэш устарел, обновляем в фоне
                                if age >= self._xui_links_cache_ttl:
                                    self._refresh_xui_links_async(username, user_plan)
                        
                        # Если всё ещё нет кэша - генерируем синхронно для первого запроса
                        if not cache_used:
                            logger.info(f"No cache found for {username}, generating links synchronously...")
                            try:
                                # Генерируем ссылки синхронно - это должно быть быстро благодаря параллельной генерации
                                logger.debug(f"Calling get_user_vless_uris for {username}...")
                                generated_nodes = sync_manager.get_user_vless_uris(username) or []
                                logger.debug(f"get_user_vless_uris returned {len(generated_nodes) if generated_nodes else 0} nodes")
                                
                                if generated_nodes:
                                    vless_nodes = generated_nodes
                                    cache_used = True
                                    logger.info(f"Successfully generated {len(generated_nodes)} links for {username}")
                                    
                                    # Сохраняем в кэш для следующих запросов
                                    if self._xui_links_cache_ttl > 0:
                                        with self._xui_links_cache_lock:
                                            self._xui_links_cache[cache_key] = (time.time(), list(generated_nodes))
                                        self._save_xui_links_cache()
                                        logger.debug(f"Cached {len(generated_nodes)} links for {username} (TTL={self._xui_links_cache_ttl}s)")
                                else:
                                    logger.warning(f"No links generated for {username} - check X-UI configuration and user mapping")
                                    vless_nodes = []
                            except Exception as e:
                                logger.error(f"Error generating links for {username}: {e}", exc_info=True)
                                # При ошибке возвращаем пустой список, но не блокируем запрос
                                vless_nodes = []
                                
                                # Запускаем генерацию в фоне для следующего запроса
                                with self._xui_links_cache_lock:
                                    if cache_key not in self._xui_links_refreshing:
                                        self._xui_links_refreshing.add(cache_key)
                                        
                                        def generate_in_background():
                                            try:
                                                logger.debug(f"Background: generating links for {username}...")
                                                generated_nodes = sync_manager.get_user_vless_uris(username) or []
                                                if self._xui_links_cache_ttl > 0:
                                                    with self._xui_links_cache_lock:
                                                        self._xui_links_cache[cache_key] = (time.time(), list(generated_nodes))
                                                    self._save_xui_links_cache()
                                                    logger.debug(f"Background: cached {len(generated_nodes)} links for {username} (TTL={self._xui_links_cache_ttl}s)")
                                            except Exception as e:
                                                logger.error(f"Background: error generating links for {username}: {e}", exc_info=True)
                                            finally:
                                                with self._xui_links_cache_lock:
                                                    self._xui_links_refreshing.discard(cache_key)
                                        
                                        try:
                                            import threading
                                            thread = threading.Thread(target=generate_in_background, daemon=True)
                                            thread.start()
                                        except Exception as e:
                                            logger.error(f"Failed to start background link generation for {username}: {e}", exc_info=True)
                                            self._xui_links_refreshing.discard(cache_key)
                    
                    if vless_nodes:
                        for node in vless_nodes:
                            uri = node.get("uri", "")
                            if not uri:
                                continue
                            
                            # Получаем конфигурацию сервера для переписывания
                            server_config_dict = node.get("server_config", {})
                            server_id = server_config_dict.get("name", "unknown")
                            
                            # Создаем конфигурацию для LinkRewriter
                            public_host = server_config_dict.get("public_host")
                            public_port = server_config_dict.get("public_port", 443)
                            link_host_rewrite_from = server_config_dict.get("link_host_rewrite_from", "127.0.0.1")
                            sni = server_config_dict.get("sni")
                            xhttp_alpn = server_config_dict.get("xhttp_alpn")
                            xhttp_fp = server_config_dict.get("xhttp_fp")
                            xhttp_mode = server_config_dict.get("xhttp_mode")
                            grpc_authority = server_config_dict.get("grpc_authority")
                            
                            # Если public_host не задан, извлекаем домен из host сервера X-UI (для reverse proxy)
                            if not public_host:
                                host_url = server_config_dict.get("host", "")
                                if host_url:
                                    try:
                                        parsed = urlparse(host_url)
                                        public_host = parsed.hostname
                                        if public_host:
                                            logger.debug(f"Using host domain as public_host for '{server_id}': {public_host}")
                                    except Exception as e:
                                        logger.warning(f"Failed to extract hostname from '{host_url}': {e}")
                            
                            # Создаем конфигурацию если есть public_host (из настроек или из host)
                            server_cfg = None
                            if public_host:
                                server_cfg = LinkRewriterServerConfig(
                                    server_id=server_id,
                                    public_host=public_host,
                                    public_port=public_port,
                                    link_host_rewrite_from=link_host_rewrite_from,
                                    sni=sni or public_host,
                                    xhttp_alpn=xhttp_alpn,
                                    xhttp_fp=xhttp_fp,
                                    xhttp_mode=xhttp_mode,
                                    grpc_authority=grpc_authority
                                )
                                logger.debug(f"Created server_cfg for '{server_id}' with public_host={public_host}, public_port={public_port}")
                            else:
                                # Логируем предупреждение, если public_host не удалось определить
                                logger.warning(f"Server '{server_id}' has no public_host configured and host URL is invalid. Link will not be rewritten.")
                            
                            # X-UI ссылки с явным контекстом сервера
                            links_with_context.append((uri, server_cfg))
        except Exception as e:
            # Не блокируем выдачу подписки при ошибке получения VLESS URIs
            logger.warning(f"Failed to get X-UI VLESS URIs for {username}: {e}", exc_info=True)

        # Единый pipeline нормализации: все ссылки проходят через rewrite_proxy_links
        normalized_uris: List[str] = []
        hysteria_normalized = 0
        vless_normalized = 0
        
        for uri, server_cfg in links_with_context:
            normalized_uri = self._normalize_link(uri, server_cfg)
            if normalized_uri:
                normalized_uris.append(normalized_uri)
                if normalized_uri.startswith('hy2://'):
                    hysteria_normalized += 1
                elif normalized_uri.startswith('vless://'):
                    vless_normalized += 1

        logger.info(f"Normalized URIs: {len(normalized_uris)} total (Hysteria: {hysteria_normalized}, VLESS: {vless_normalized})")
        
        if not normalized_uris:
            logger.error(f"No normalized URIs available for {username}")
            return "No URI available"

        subscription_info = (
            f"//subscription-userinfo: upload={user_info.upload_bytes}; "
            f"download={user_info.download_bytes}; "
            f"total={user_info.max_download_bytes}; "
            f"expire={user_info.expiration_timestamp}\n"
        )
        profile_lines = "//profile-title: Asgaroth Gate\n//profile-update-interval: 1\n"
        result = profile_lines + subscription_info + "\n".join(normalized_uris)
        logger.info(f"Generated subscription for {username}: {len(normalized_uris)} URIs, length={len(result)} chars")
        return result


class TemplateRenderer:
    def __init__(self, template_dir: str, config: AppConfig):
        self.env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
        self.html_template = self.env.get_template('index.html')
        self.config = config

    def render(self, context: TemplateContext) -> str:
        return self.html_template.render(vars(context))


class HysteriaServer:
    def __init__(self):
        self.config = self._load_config()
        self.rate_limiter = RateLimiter(self.config.rate_limit, self.config.rate_limit_window)
        self.hysteria_cli = HysteriaCLI(self.config.hysteria_cli_path)
        self.singbox_generator = SingboxConfigGenerator(self.hysteria_cli, self.config.sni)
        self.singbox_generator.set_template_path(self.config.singbox_template_path)
        self.subscription_manager = SubscriptionManager(self.hysteria_cli, self.config)
        self.template_renderer = TemplateRenderer(self.config.template_dir, self.config)
        self.app = web.Application(middlewares=[
            self._invalid_endpoint_middleware,
            self._rate_limit_middleware,
            self._noindex_middleware
        ])

        safe_subpath = self.validate_and_escape_subpath(self.config.subpath)

        base_path = f'/{safe_subpath}'
        self.app.router.add_get(f'{base_path}/sub/normal/style.css', self.handle_style)
        self.app.router.add_get(f'{base_path}/sub/normal/script.js', self.handle_script)
        self.app.router.add_get(f'{base_path}/sub/normal/{{password_token}}', self.handle)
        self.app.router.add_get(f'{base_path}/robots.txt', self.robots_handler)
        self.app.router.add_route('*', f'{base_path}/{{tail:.*}}', self.handle_404_subpath)

    def _load_config(self) -> AppConfig:
        domain = os.getenv('HYSTERIA_DOMAIN', 'localhost')
        external_port = int(os.getenv('HYSTERIA_PORT', '443'))
        aiohttp_listen_address = os.getenv('AIOHTTP_LISTEN_ADDRESS', '127.0.0.1')
        aiohttp_listen_port = int(os.getenv('AIOHTTP_LISTEN_PORT', '33261'))

        subpath = os.getenv('SUBPATH', '').strip().strip("/")
        if not subpath or not self.is_valid_subpath(subpath):
            raise ValueError(
                f"Invalid or empty SUBPATH: '{subpath}'. Subpath must be non-empty and contain only alphanumeric characters.")

        sni_file = '/etc/hysteria/.configs.env'
        singbox_template_path = '/etc/hysteria/core/scripts/normalsub/singbox.json'
        hysteria_cli_path = '/etc/hysteria/core/cli.py'
        nodes_json_path = '/etc/hysteria/nodes.json'
        extra_config_path = '/etc/hysteria/extra.json'
        rate_limit = 100
        rate_limit_window = 60
        template_dir = os.path.join(os.path.dirname(__file__), 'template')

        sni = self._load_sni_from_env(sni_file)
        
        # Загружаем публичный хост для нормализации VLESS ссылок
        public_host = os.getenv('NORMAL_SUB_PUBLIC_HOST', None)
        public_port = int(os.getenv('NORMAL_SUB_PUBLIC_PORT', '443'))
        
        return AppConfig(
            domain=domain,
            external_port=external_port,
            aiohttp_listen_address=aiohttp_listen_address,
            aiohttp_listen_port=aiohttp_listen_port,
            sni_file=sni_file,
            singbox_template_path=singbox_template_path,
            hysteria_cli_path=hysteria_cli_path,
            nodes_json_path=nodes_json_path,
            extra_config_path=extra_config_path,
            rate_limit=rate_limit,
            rate_limit_window=rate_limit_window,
            sni=sni,
            template_dir=template_dir,
            subpath=subpath,
            public_host=public_host,
            public_port=public_port
        )

    def _load_sni_from_env(self, sni_file: str) -> str:
        try:
            with open(sni_file, 'r') as f:
                for line in f:
                    if line.startswith('SNI='):
                        return line.strip().split('=')[1]
        except FileNotFoundError:
            print("Warning: SNI file not found. Using default SNI.")
        return "bts.com"

    def is_valid_subpath(self, subpath: str) -> bool:
        return bool(re.match(r"^[a-zA-Z0-9]+$", subpath))

    def validate_and_escape_subpath(self, subpath: str) -> str:
        if not self.is_valid_subpath(subpath):
            raise ValueError(f"Invalid subpath: {subpath}")
        return re.escape(subpath)

    @middleware
    async def _rate_limit_middleware(self, request: web.Request, handler):
        client_ip_hdr = request.headers.get('X-Forwarded-For', request.headers.get('X-Real-IP'))
        client_ip = client_ip_hdr.split(',')[0].strip() if client_ip_hdr else request.remote

        if client_ip and not self.rate_limiter.check_limit(client_ip):
            return web.Response(status=429, text="Rate limit exceeded.")
        return await handler(request)

    @middleware
    async def _invalid_endpoint_middleware(self, request: web.Request, handler):
        expected_prefix = f'/{self.config.subpath}/'
        if not request.path.startswith(expected_prefix):
            print(f"Warning: Request {request.path} reached aiohttp outside expected subpath {expected_prefix}. Closing connection.")
            if request.transport is not None:
                request.transport.close()
            raise web.HTTPForbidden()
        return await handler(request)

    @middleware
    async def _noindex_middleware(self, request: web.Request, handler):
        response = await handler(request)
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive, nosnippet'
        return response

    async def handle(self, request: web.Request) -> web.Response:
        try:
            password_token_raw = request.match_info.get('password_token', '')
            if not password_token_raw:
                return web.Response(status=400, text="Error: Missing 'password_token' parameter.")

            password_token = Utils.sanitize_input(password_token_raw, r'^[a-zA-Z0-9]+$')

            username = self.hysteria_cli.get_username_by_password(password_token)
            if username is None:
                return web.Response(status=404, text="User not found for the provided token.")

            user_info = self.hysteria_cli.get_user_info(username)
            if user_info is None:
                return web.Response(status=404, text=f"User '{username}' details not found.")

            if user_info.blocked:
                return await self._handle_blocked_user(request, user_info)

            user_agent = request.headers.get('User-Agent', '').lower()
            if any(browser in user_agent for browser in ['chrome', 'firefox', 'safari', 'edge', 'opera']):
                return await self._handle_html(request, username, user_info)
            fragment = request.query.get('fragment', '')
            if not user_agent.startswith('hiddifynext') and ('singbox' in user_agent or 'sing' in user_agent):
                return await self._handle_singbox(username, fragment, user_info)
            return await self._handle_normalsub(request, username, user_info)
        except ValueError as e:
            return web.Response(status=400, text=f"Error: {e}")
        except Exception as e:
            print(f"Internal Server Error: {e}")
            return web.Response(status=500, text="Error: Internal server error")

    async def _handle_blocked_user(self, request: web.Request, user_info: UserInfo) -> web.Response:
        # Определяем сообщение в зависимости от причины блокировки
        if user_info.block_reason == "traffic":
            message = "⚠️ Трафик исчерпан"
        elif user_info.block_reason == "expiration":
            message = "⛔️ Подписка истекла"
        else:
            # По умолчанию, если причина не указана, определяем по данным пользователя
            import time
            from datetime import datetime, timedelta
            now = datetime.now()
            total_bytes = user_info.upload_bytes + user_info.download_bytes
            expired_by_traffic = (user_info.max_download_bytes > 0 and total_bytes >= user_info.max_download_bytes)
            
            if expired_by_traffic:
                message = "⚠️ Трафик исчерпан"
            else:
                message = "⛔️ Подписка истекла"
        
        fake_uri = f"hysteria2://x@end.com:443?sni=support.me#{message}"
        user_agent = request.headers.get('User-Agent', '').lower()

        if any(browser in user_agent for browser in ['chrome', 'firefox', 'safari', 'edge', 'opera']):
            context = self._get_blocked_template_context(fake_uri, user_info, message)
            return web.Response(text=self.template_renderer.render(context), content_type='text/html')

        fragment = request.query.get('fragment', '')
        if not user_agent.startswith('hiddifynext') and ('singbox' in user_agent or 'sing' in user_agent):
            combined_config = self.singbox_generator.combine_configs([fake_uri], "blocked", fragment)
            return web.Response(text=json.dumps(combined_config, indent=4, sort_keys=True), content_type='application/json')

        return web.Response(text=fake_uri, content_type='text/plain')

    def _get_blocked_template_context(self, fake_uri: str, user_info: UserInfo, message: str = "⛔️ Подписка истекла") -> TemplateContext:
        return TemplateContext(
            username=user_info.username,
            usage=user_info.usage_human_readable,
            usage_raw=message,
            expiration_date=user_info.expiration_date,
            sublink_qrcode="",
            sub_link="#blocked",
            sub_link_encoded="",
            blocked=True,
            local_uris=[
                NodeURI(
                    label="Blocked",
                    uri=fake_uri,
                    qrcode=None
                )
            ],
            node_uris=[]
        )

    async def _handle_html(self, request: web.Request, username: str, user_info: UserInfo) -> web.Response:
        context = await self._get_template_context(username, user_info)
        return web.Response(text=self.template_renderer.render(context), content_type='text/html')

    async def _handle_singbox(self, username: str, fragment: str, user_info: UserInfo) -> web.Response:
        all_uris = self.hysteria_cli.get_all_uris(username)
        if not all_uris:
            return web.Response(status=404, text=f"Error: No valid URIs found for user {username}.")
        combined_config = self.singbox_generator.combine_configs(all_uris, username, fragment)
        return web.Response(text=json.dumps(combined_config, indent=4, sort_keys=True), content_type='application/json')

    async def _handle_normalsub(self, request: web.Request, username: str, user_info: UserInfo) -> web.Response:
        user_agent = request.headers.get('User-Agent', '').lower()
        subscription = self.subscription_manager.get_normal_subscription(username, user_agent)
        if subscription == "User not found":
            return web.Response(status=404, text=f"User '{username}' not found.")
        return web.Response(text=subscription, content_type='text/plain')

    async def _get_template_context(self, username: str, user_info: UserInfo) -> TemplateContext:
        labeled_uris = self.hysteria_cli.get_all_labeled_uris(username)
        port_str = f":{self.config.external_port}" if self.config.external_port not in [80, 443, 0] else ""
        base_url = f"https://{self.config.domain}{port_str}"

        if not Utils.is_valid_url(base_url):
            print(f"Warning: Constructed base URL '{base_url}' might be invalid. Check domain and port config.")

        sub_link = f"{base_url}/{self.config.subpath}/sub/normal/{user_info.password}"
        sub_link_encoded = quote(sub_link, safe='')
        sublink_qrcode = Utils.generate_qrcode_base64(sub_link)

        singbox_qrcode = Utils.generate_qrcode_base64(f"sing-box://import-remote-profile?url={sub_link}")
        hiddify_qrcode = Utils.generate_qrcode_base64(f"hiddify://import/{sub_link}")
        streisand_qrcode = Utils.generate_qrcode_base64(f"streisand://import/sub?url={sub_link}")
        nekobox_qrcode = Utils.generate_qrcode_base64(f"nekobox://import?url={sub_link}")

        local_uris: List[NodeURI] = []
        node_uris: List[NodeURI] = []

        user_plan = Utils.normalize_plan(getattr(user_info, "plan", "standard"))
        is_premium_user = (user_plan == "premium")

        nodes_types: Dict[str, str] = {}
        try:
            if os.path.exists(self.config.nodes_json_path):
                with open(self.config.nodes_json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for node in data:
                        name = str(node.get("name", "")).strip()
                        if not name:
                            continue
                        nodes_types[name] = Utils.normalize_plan(node.get("type", "standard"))
        except Exception as e:
            print(f"Warning: failed to load nodes from {self.config.nodes_json_path} for HTML view: {e}")

        for item in labeled_uris:
            label = item.get('label', '')
            uri = item.get('uri', '')

            if "IPv6" in label or "v6" in label:
                continue

            if label.startswith("Node:"):
                node_name = label[len("Node:"):].strip()
                node_type = nodes_types.get(node_name, "standard")
                if (not is_premium_user) and node_type == "premium":
                    continue

            node_uri = NodeURI(
                label=label,
                uri=uri,
                qrcode=Utils.generate_qrcode_base64(uri)
            )

            if label.startswith('Node:'):
                node_uris.append(node_uri)
            else:
                local_uris.append(node_uri)
        extra_items = self.subscription_manager._filter_extra_configs_for_user(user_plan)
        for x in extra_items:
            uri = str(x.get("uri", "")).strip()
            if not uri:
                continue
            name = str(x.get("name", "Extra")).strip() or "Extra"
            item_plan = Utils.normalize_plan(x.get("type") or x.get("plan") or "standard")

            label = f"{name}"

            local_uris.append(NodeURI(
                label=label,
                uri=uri,
                qrcode=Utils.generate_qrcode_base64(uri)
            ))

        return TemplateContext(
            username=username,
            usage=user_info.usage_human_readable,
            usage_raw=user_info.usage_detailed,
            expiration_date=user_info.expiration_date,
            sublink_qrcode=sublink_qrcode,
            sub_link=sub_link,
            sub_link_encoded=sub_link_encoded,
            blocked=user_info.blocked,
            local_uris=local_uris,
            node_uris=node_uris,
            singbox_qrcode=singbox_qrcode,
            hiddify_qrcode=hiddify_qrcode,
            streisand_qrcode=streisand_qrcode,
            nekobox_qrcode=nekobox_qrcode
        )

    async def robots_handler(self, request: web.Request) -> web.Response:
        return web.Response(text="User-agent: *\nDisallow: /", content_type="text/plain")

    async def handle_404_subpath(self, request: web.Request) -> web.Response:
        print(f"404 Not Found (within subpath, unhandled by specific routes): {request.path}")
        return web.Response(status=404, text="Not Found within Subpath")

    async def handle_style(self, request: web.Request) -> web.Response:
        return web.FileResponse(os.path.join(self.config.template_dir, 'style.css'))

    async def handle_script(self, request: web.Request) -> web.Response:
        return web.FileResponse(os.path.join(self.config.template_dir, 'script.js'))

    def run(self):
        print(f"Starting Hysteria Normalsub server on {self.config.aiohttp_listen_address}:{self.config.aiohttp_listen_port}")
        print(f"External access via Caddy should be at https://{self.config.domain}:{self.config.external_port}/{self.config.subpath}/sub/normal/<USER_PASSWORD>")
        web.run_app(
            self.app,
            host=self.config.aiohttp_listen_address,
            port=self.config.aiohttp_listen_port
        )


if __name__ == '__main__':
    server = HysteriaServer()
    server.run()
