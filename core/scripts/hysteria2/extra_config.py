import json
import argparse
import os
import sys

from init_paths import *
from paths import *

VALID_PROTOCOLS = ("vmess://", "vless://", "ss://", "trojan://")
VALID_PLANS = ("standard", "premium")


def normalize_plan(plan: str | None) -> str:
    p = (plan or "standard").strip().lower()
    return "premium" if p == "premium" else "standard"


def read_configs():
    if not os.path.exists(EXTRA_CONFIG_PATH):
        return []
    try:
        with open(EXTRA_CONFIG_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
            if not content:
                return []
            data = json.loads(content)
            if isinstance(data, list):
                # Обратная совместимость: если plan нет — считаем standard
                normalized = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name")
                    uri = item.get("uri")
                    if not name or not uri:
                        continue
                    normalized.append({
                        "name": name,
                        "uri": uri,
                        "plan": normalize_plan(item.get("plan") or item.get("type") or "standard"),
                    })
                return normalized
            return []
    except (json.JSONDecodeError, IOError):
        return []


def write_configs(configs):
    try:
        os.makedirs(os.path.dirname(EXTRA_CONFIG_PATH), exist_ok=True)
        with open(EXTRA_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(configs, f, indent=4, ensure_ascii=False)
    except IOError as e:
        print(f"Error writing to {EXTRA_CONFIG_PATH}: {e}", file=sys.stderr)
        sys.exit(1)


def add_config(name, uri, plan: str = "standard"):
    if not any(uri.startswith(protocol) for protocol in VALID_PROTOCOLS):
        print(f"Error: Invalid URI. Must start with one of {', '.join(VALID_PROTOCOLS)}", file=sys.stderr)
        sys.exit(1)

    plan = normalize_plan(plan)
    if plan not in VALID_PLANS:
        print("Error: plan must be either 'standard' or 'premium'", file=sys.stderr)
        sys.exit(1)

    configs = read_configs()

    if any(c.get('name') == name for c in configs):
        print(f"Error: A configuration with the name '{name}' already exists.", file=sys.stderr)
        sys.exit(1)

    configs.append({"name": name, "uri": uri, "plan": plan})
    write_configs(configs)
    print(f"Successfully added configuration '{name}' ({plan}).")


def delete_config(name):
    configs = read_configs()

    initial_length = len(configs)
    configs = [c for c in configs if c.get('name') != name]

    if len(configs) == initial_length:
        print(f"Error: No configuration found with the name '{name}'.", file=sys.stderr)
        sys.exit(1)

    write_configs(configs)
    print(f"Successfully deleted configuration '{name}'.")


def list_configs():
    configs = read_configs()
    print(json.dumps(configs, indent=4, ensure_ascii=False))


def get_config(name):
    configs = read_configs()
    config = next((c for c in configs if c.get('name') == name), None)

    if config:
        print(json.dumps(config, indent=4, ensure_ascii=False))
    else:
        print(f"Error: No configuration found with the name '{name}'.", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Manage extra proxy configurations for subscription links.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_add = subparsers.add_parser("add", help="Add a new proxy configuration.")
    parser_add.add_argument("--name", type=str, required=True, help="A unique name for the configuration.")
    parser_add.add_argument("--uri", type=str, required=True, help="The proxy URI (vmess, vless, ss, trojan).")
    parser_add.add_argument(
        "--plan",
        type=str,
        default="standard",
        choices=list(VALID_PLANS),
        help="Access level: standard or premium (default: standard)."
    )

    parser_delete = subparsers.add_parser("delete", help="Delete a proxy configuration.")
    parser_delete.add_argument("--name", type=str, required=True, help="The name of the configuration to delete.")

    subparsers.add_parser("list", help="List all extra proxy configurations.")

    parser_get = subparsers.add_parser("get", help="Get a specific proxy configuration by name.")
    parser_get.add_argument("--name", type=str, required=True, help="The name of the configuration to retrieve.")

    args = parser.parse_args()

    if os.geteuid() != 0:
        print("This script must be run as root.", file=sys.stderr)
        sys.exit(1)

    if args.command == "add":
        add_config(args.name, args.uri, args.plan)
    elif args.command == "delete":
        delete_config(args.name)
    elif args.command == "list":
        list_configs()
    elif args.command == "get":
        get_config(args.name)


if __name__ == "__main__":
    main()
