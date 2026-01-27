#!/usr/bin/env python3
import subprocess
import sys
import json
from pathlib import Path
core_scripts_dir = Path(__file__).resolve().parents[1]

if str(core_scripts_dir) not in sys.path:
    sys.path.append(str(core_scripts_dir))

from paths import *

WARP_SCRIPT_PATH = Path(__file__).resolve().parent / "warp.py"
WARP_DEVICE = "wgcf"

def is_service_active(service_name: str) -> bool:
    return subprocess.run(["systemctl", "is-active", "--quiet", service_name]).returncode == 0


def install_warp():
    print("Installing WARP...")
    result = subprocess.run(
        [sys.executable, str(WARP_SCRIPT_PATH), "install"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        error_msg = result.stderr.strip() if result.stderr.strip() else result.stdout.strip()
        if error_msg:
            print(f"WARP installation error: {error_msg}", file=sys.stderr)
        else:
            print(f"WARP installation failed with exit code {result.returncode}", file=sys.stderr)
        return False
    return True


def add_warp_outbound_to_config():
    if not CONFIG_FILE.exists():
        print(f"Error: Config file {CONFIG_FILE} not found.")
        return

    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

    outbounds = config.get("outbounds", [])
    if any(outbound.get("name") == "warps" for outbound in outbounds):
        print("WARP outbound already exists in the configuration.")
        return

    outbounds.append({
        "name": "warps",
        "type": "direct",
        "direct": {
            "mode": 4,
            "bindDevice": WARP_DEVICE
        }
    })
    config["outbounds"] = outbounds

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    print("WARP outbound added to config.json.")


def restart_hysteria():
    subprocess.run(["python3", str(CLI_PATH), "restart-hysteria2"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Hysteria2 restarted with updated configuration.")


def main():
    warp_service = f"wg-quick@{WARP_DEVICE}.service"

    if is_service_active(warp_service):
        print("WARP is already active. Checking configuration...")
        add_warp_outbound_to_config()
        restart_hysteria()
    else:
        if install_warp():
            # Wait a bit for service to start
            import time
            time.sleep(2)
            if is_service_active(warp_service):
                print("WARP installation successful.")
                add_warp_outbound_to_config()
                restart_hysteria()
            else:
                print("WARP installation completed but service is not active. Please check logs:", file=sys.stderr)
                print(f"Run: journalctl -u {warp_service} --no-pager", file=sys.stderr)
                sys.exit(1)
        else:
            print("WARP installation failed. Check error messages above.", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()