#!/usr/bin/env python3

import os
import sys
import json
import time
import subprocess
import socket
from pathlib import Path
from init_paths import *
from paths import *

# Путь к файлу с токеном Cloudflare
CLOUDFLARE_INI = "/etc/hysteria/cloudflare.ini"

def run_command(command, capture_output=True, shell=True):
    """Run a shell command and return its output"""
    result = subprocess.run(
        command,
        shell=shell,
        capture_output=capture_output,
        text=True
    )
    if capture_output:
        return result.stdout.strip()
    return None

def get_ip_from_domain(domain):
    """Get the first IPv4 address from a domain using dig"""
    try:
        output = run_command(f"dig +short {domain} A | head -n 1")
        if output and is_valid_ipv4(output):
            return output
    except:
        pass
    return None

def is_valid_ipv4(ip):
    """Check if a string is a valid IPv4 address"""
    try:
        socket.inet_pton(socket.AF_INET, ip)
        return True
    except (socket.error, ValueError):
        return False

def get_server_ip():
    """Get the server's public IP address"""
    return run_command("curl -s -4 ifconfig.me")

def update_config_tls(insecure, pinSHA256=None):
    """Helper to update TLS settings in config.json"""
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        config['tls']['insecure'] = insecure
        if pinSHA256:
            config['tls']['pinSHA256'] = pinSHA256
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)

def install_certs(cert_path, key_path):
    """Copy certs to destination and set permissions"""
    run_command(f"cp {cert_path} /etc/hysteria/ca.crt", capture_output=False)
    run_command(f"cp {key_path} /etc/hysteria/ca.key", capture_output=False)
    run_command("chown hysteria:hysteria /etc/hysteria/ca.key /etc/hysteria/ca.crt", capture_output=False)
    run_command("chmod 640 /etc/hysteria/ca.key /etc/hysteria/ca.crt", capture_output=False)

def update_sni(sni):
    if not sni:
        print("Invalid SNI. Please provide a valid SNI.")
        print(f"Example: {sys.argv[0]} yourdomain.com")
        return 1

    print(f"Processing SNI: {sni}...")

    # --- 1. Cloudflare DNS-01 Challenge Strategy ---
    use_cloudflare = False
    if os.path.exists(CLOUDFLARE_INI):
        print(f"Found Cloudflare credentials at {CLOUDFLARE_INI}. Attempting DNS-01 challenge...")
        
        # Пробуем получить сертификат через плагин Cloudflare
        cmd = (
            f"certbot certonly --dns-cloudflare "
            f"--dns-cloudflare-credentials {CLOUDFLARE_INI} "
            f"--dns-cloudflare-propagation-seconds 30 "
            f"-d {sni} --non-interactive --agree-tos --email admin@{sni} --force-renewal"
        )
        
        result = run_command(cmd, capture_output=True)
        
        # Проверяем успешность (Certbot пишет 'Successfully received certificate' или 'not yet due')
        if "Successfully received certificate" in result or "Certificate not yet due" in result:
            print("✅ Successfully obtained certificate via Cloudflare!")
            use_cloudflare = True
            
            live_cert = f"/etc/letsencrypt/live/{sni}/fullchain.pem"
            live_key = f"/etc/letsencrypt/live/{sni}/privkey.pem"
            
            install_certs(live_cert, live_key)
            update_config_tls(insecure=False)
            print(f"TLS insecure flag set to false in {CONFIG_FILE}")
        else:
            print("⚠️ Cloudflare Certbot failed. Falling back to standard checks.")
            print(f"Error details (partial): {result[-200:] if result else 'No output'}")

    # --- 2. Standard Strategy (HTTP-01 or Self-Signed) ---
    # Запускаем только если Cloudflare не сработал
    use_certbot_http = False
    if not use_cloudflare:
        if os.path.isfile(CONFIG_ENV):
            env_vars = {}
            with open(CONFIG_ENV, 'r') as f:
                for line in f:
                    if '=' in line:
                        name, value = line.strip().split('=', 1)
                        env_vars[name] = value
        else:
            print(f"Error: Config file {CONFIG_ENV} not found.")
            return 1

        server_ip = None
        if 'IP4' in env_vars:
            ip4 = env_vars['IP4']
            if is_valid_ipv4(ip4):
                server_ip = ip4
                print(f"Using server IP from config: {server_ip}")
            else:
                domain_ip = get_ip_from_domain(ip4)
                if domain_ip:
                    server_ip = domain_ip
                    print(f"Resolved domain {ip4} to IP: {server_ip}")
                else:
                    server_ip = get_server_ip()
                    print(f"Could not resolve domain {ip4}. Using auto-detected server IP: {server_ip}")
        else:
            server_ip = get_server_ip()
            print(f"Using auto-detected server IP: {server_ip}")

        print(f"Checking if {sni} points to this server ({server_ip})...")
        domain_ip = get_ip_from_domain(sni)
        
        if not domain_ip:
            print(f"Warning: Could not resolve {sni} to an IPv4 address.")
        elif domain_ip == server_ip:
            print(f"Success: {sni} correctly points to this server ({server_ip}).")
            use_certbot_http = True
        else:
            print(f"Notice: {sni} points to {domain_ip}, not to this server ({server_ip}).")

        os.chdir('/etc/hysteria/')

        if use_certbot_http:
            print(f"Using certbot (HTTP-01) to obtain a valid certificate for {sni}...")
            
            certbot_output = run_command(f"certbot certificates")
            if sni in certbot_output:
                print(f"Certificate for {sni} already exists. Renewing...")
                run_command(f"certbot renew --cert-name {sni}", capture_output=False)
            else:
                print(f"Requesting new certificate for {sni}...")
                run_command(f"certbot certonly --standalone -d {sni} --non-interactive --agree-tos --email admin@{sni}", 
                           capture_output=False)
            
            install_certs(f"/etc/letsencrypt/live/{sni}/fullchain.pem", f"/etc/letsencrypt/live/{sni}/privkey.pem")
            
            print("Certificates successfully installed from Let's Encrypt.")
            update_config_tls(insecure=False)
            print(f"TLS insecure flag set to false in {CONFIG_FILE}")
        else:
            print(f"Using self-signed certificate with openssl for {sni}...")
            
            if os.path.exists("ca.key"):
                os.remove("ca.key")
            if os.path.exists("ca.crt"):
                os.remove("ca.crt")
            
            print(f"Generating CA key and certificate for SNI: {sni} ...")
            run_command("openssl ecparam -genkey -name prime256v1 -out ca.key > /dev/null 2>&1", capture_output=False)
            run_command(f"openssl req -new -x509 -days 36500 -key ca.key -out ca.crt -subj '/CN={sni}' > /dev/null 2>&1", 
                       capture_output=False)
            print(f"Self-signed certificate generated for {sni}")
            
            update_config_tls(insecure=True)
            print(f"TLS insecure flag set to true in {CONFIG_FILE}")

        run_command("chown hysteria:hysteria /etc/hysteria/ca.key /etc/hysteria/ca.crt", capture_output=False)
        run_command("chmod 640 /etc/hysteria/ca.key /etc/hysteria/ca.crt", capture_output=False)

    # --- 3. Post-Processing (SHA256 Pinning & Env Update) ---
    
    # Calculate PIN regardless of how the cert was obtained
    sha256 = run_command(
        "openssl x509 -noout -fingerprint -sha256 -inform pem -in /etc/hysteria/ca.crt | sed 's/.*=//;s///g'"
    )
    print(f"SHA-256 fingerprint generated: {sha256}")

    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
        
        config['tls']['pinSHA256'] = sha256
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"SHA-256 updated successfully in {CONFIG_FILE}")
    else:
        print(f"Error: Config file {CONFIG_FILE} not found.")
        return 1

    sni_found = False
    if os.path.isfile(CONFIG_ENV):
        with open(CONFIG_ENV, 'r') as f:
            lines = f.readlines()
        
        with open(CONFIG_ENV, 'w') as f:
            for line in lines:
                if line.startswith('SNI='):
                    f.write(f'SNI={sni}\n')
                    sni_found = True
                else:
                    f.write(line)
            
            if not sni_found:
                f.write(f'SNI={sni}\n')
                print(f"Added new SNI entry to {CONFIG_ENV}")
            else:
                print(f"SNI updated successfully in {CONFIG_ENV}")
    else:
        with open(CONFIG_ENV, 'w') as f:
            f.write(f'SNI={sni}\n')
        print(f"Created {CONFIG_ENV} with new SNI.")

    run_command(f"python3 {CLI_PATH} restart-hysteria2 > /dev/null 2>&1", capture_output=False)
    print(f"Hysteria2 restarted successfully with new SNI: {sni}.")

    if use_cloudflare:
        print(f"✅ Valid Let's Encrypt certificate installed via Cloudflare DNS for {sni}")
        print("   TLS insecure mode is now DISABLED")
    elif use_certbot_http:
        print(f"✅ Valid Let's Encrypt certificate installed via HTTP-01 for {sni}")
        print("   TLS insecure mode is now DISABLED")
    else:
        print(f"⚠️ Self-signed certificate installed for {sni}")
        print("   TLS insecure mode is now ENABLED")
        print("   (This certificate won't be trusted by browsers)")

    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <sni>")
        sys.exit(1)
    
    sni = sys.argv[1]
    sys.exit(update_sni(sni))