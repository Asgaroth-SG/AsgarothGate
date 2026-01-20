#!/usr/bin/env python3
"""
Unit-тесты для LinkRewriter
"""
import sys
import os
from pathlib import Path

# Добавляем путь к модулю
sys.path.insert(0, str(Path(__file__).parent))
from link_rewriter import (
    rewrite_proxy_links, XuiServerConfig,
    rewrite_vless, rewrite_trojan, rewrite_ss, rewrite_vmess
)


def test_vless_rewrite():
    """Тест переписывания VLESS ссылки"""
    server_cfg = XuiServerConfig(
        server_id="server1",
        public_host="gateway.asgaroth.ru",
        public_port=443
    )
    
    # Тест 1: host=127.0.0.1 -> переписан
    input_link = "vless://07ccf3b7-1a47-5d2f-99ca-1f3fd34195ee@127.0.0.1:20000?type=xhttp&encryption=none&path=%2Fxhttp%2F9f3a1cfba29df6b437aed633b158d0e9%2F&host=&mode=auto&security=none#%F0%9F%87%B9%F0%9F%87%B7%20%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F"
    result = rewrite_vless(input_link, server_cfg)
    
    assert result.startswith("vless://07ccf3b7-1a47-5d2f-99ca-1f3fd34195ee@gateway.asgaroth.ru:443"), \
        f"Host/port mismatch. Got: {result}"
    assert "#%F0%9F%87%B9%F0%9F%87%B7%20%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F" in result, \
        f"Fragment missing. Got: {result}"
    assert "security=tls" in result, f"security=tls missing. Got: {result}"
    assert "sni=gateway.asgaroth.ru" in result, f"sni missing. Got: {result}"
    assert "alpn=h2" in result, f"alpn=h2 missing. Got: {result}"
    assert "fp=chrome" in result, f"fp=chrome missing. Got: {result}"
    assert "path=%2Fxhttp%2F9f3a1cfba29df6b437aed633b158d0e9%2F" in result, f"path missing. Got: {result}"
    assert "host=" not in result, f"Empty host should be removed. Got: {result}"
    
    print("✓ test_vless_rewrite passed")
    
    # Тест 2: host уже публичный -> не изменен
    input_link2 = "vless://uuid@example.com:443?type=xhttp&security=tls#test"
    result2 = rewrite_vless(input_link2, server_cfg)
    assert result2 == input_link2, f"Non-localhost link should be unchanged. Got: {result2}"
    
    print("✓ test_vless_rewrite (non-localhost) passed")


def test_vless_security_preserved():
    """Тест: security и sni сохраняются если уже есть"""
    server_cfg = XuiServerConfig(
        server_id="server1",
        public_host="gateway.asgaroth.ru",
        public_port=443
    )
    
    input_link = "vless://uuid@127.0.0.1:20000?type=xhttp&security=reality&sni=example.com#test"
    result = rewrite_vless(input_link, server_cfg)
    
    assert "security=reality" in result, f"Existing security should be preserved. Got: {result}"
    assert "sni=example.com" in result, f"Existing sni should be preserved. Got: {result}"
    assert result.startswith("vless://uuid@gateway.asgaroth.ru:443"), \
        f"Host should still be rewritten. Got: {result}"
    
    print("✓ test_vless_security_preserved passed")


def test_trojan_rewrite():
    """Тест переписывания Trojan ссылки"""
    server_cfg = XuiServerConfig(
        server_id="server1",
        public_host="gateway.asgaroth.ru",
        public_port=443
    )
    
    # Тест 1: host=127.0.0.1 -> переписан
    input_link = "trojan://password123@127.0.0.1:443?security=none#test-server"
    result = rewrite_trojan(input_link, server_cfg)
    
    assert result.startswith("trojan://password123@gateway.asgaroth.ru:443"), \
        f"Host/port mismatch. Got: {result}"
    assert "security=tls" in result, f"security=tls should be added. Got: {result}"
    assert "sni=gateway.asgaroth.ru" in result, f"sni should be added. Got: {result}"
    assert "#test-server" in result, f"Fragment missing. Got: {result}"
    
    print("✓ test_trojan_rewrite passed")
    
    # Тест 2: host уже публичный -> не изменен
    input_link2 = "trojan://pass@example.com:443?security=tls#test"
    result2 = rewrite_trojan(input_link2, server_cfg)
    assert result2 == input_link2, f"Non-localhost link should be unchanged. Got: {result2}"
    
    print("✓ test_trojan_rewrite (non-localhost) passed")


def test_ss_rewrite():
    """Тест переписывания Shadowsocks ссылки"""
    server_cfg = XuiServerConfig(
        server_id="server1",
        public_host="gateway.asgaroth.ru",
        public_port=443
    )
    
    # Тест 1: формат с @
    input_link = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@127.0.0.1:443#test"
    result = rewrite_ss(input_link, server_cfg)
    
    assert result.startswith("ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@gateway.asgaroth.ru:443"), \
        f"Host/port mismatch. Got: {result}"
    assert "#test" in result, f"Fragment missing. Got: {result}"
    
    print("✓ test_ss_rewrite (format with @) passed")
    
    # Тест 2: формат без @ (base64 encoded)
    import base64
    encoded = base64.b64encode(b"aes-256-gcm:password@127.0.0.1:443").decode('ascii').rstrip('=')
    input_link2 = f"ss://{encoded}#test"
    result2 = rewrite_ss(input_link2, server_cfg)
    
    assert result2.startswith("ss://"), f"Should start with ss://. Got: {result2}"
    assert "#test" in result2, f"Fragment missing. Got: {result2}"
    # Проверяем, что host заменен в декодированной части
    decoded_part = result2[5:].split('#')[0]
    decoded = base64.b64decode(decoded_part + '==')
    assert b"gateway.asgaroth.ru" in decoded, f"Host should be rewritten in base64. Got: {decoded}"
    
    print("✓ test_ss_rewrite (base64 format) passed")
    
    # Тест 3: host уже публичный -> не изменен
    input_link3 = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@example.com:443#test"
    result3 = rewrite_ss(input_link3, server_cfg)
    assert result3 == input_link3, f"Non-localhost link should be unchanged. Got: {result3}"
    
    print("✓ test_ss_rewrite (non-localhost) passed")


def test_vmess_rewrite():
    """Тест переписывания VMESS ссылки"""
    server_cfg = XuiServerConfig(
        server_id="server1",
        public_host="gateway.asgaroth.ru",
        public_port=443
    )
    
    import base64
    import json
    
    # Тест 1: add=127.0.0.1 -> переписан
    vmess_json = {
        "v": "2",
        "ps": "Test Server",
        "add": "127.0.0.1",
        "port": "20000",
        "id": "uuid-here",
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": "",
        "path": "/path",
        "tls": "none"
    }
    vmess_b64 = base64.b64encode(json.dumps(vmess_json, separators=(',', ':')).encode()).decode().rstrip('=')
    input_link = f"vmess://{vmess_b64}"
    
    result = rewrite_vmess(input_link, server_cfg)
    
    assert result.startswith("vmess://"), f"Should start with vmess://. Got: {result}"
    
    # Декодируем результат
    result_b64 = result[8:]
    result_json = json.loads(base64.b64decode(result_b64 + '==').decode())
    
    assert result_json["add"] == "gateway.asgaroth.ru", \
        f"add should be rewritten. Got: {result_json['add']}"
    assert result_json["port"] == "443", \
        f"port should be rewritten. Got: {result_json['port']}"
    assert result_json["tls"] == "tls", \
        f"tls should be added. Got: {result_json['tls']}"
    assert result_json["sni"] == "gateway.asgaroth.ru", \
        f"sni should be added. Got: {result_json.get('sni')}"
    assert result_json["ps"] == "Test Server", \
        f"ps should be preserved. Got: {result_json['ps']}"
    
    print("✓ test_vmess_rewrite passed")
    
    # Тест 2: tls и sni уже есть -> сохраняются
    vmess_json2 = {
        "v": "2",
        "ps": "Test",
        "add": "127.0.0.1",
        "port": "20000",
        "id": "uuid",
        "aid": "0",
        "net": "tcp",
        "type": "none",
        "tls": "reality",
        "sni": "example.com"
    }
    vmess_b642 = base64.b64encode(json.dumps(vmess_json2, separators=(',', ':')).encode()).decode().rstrip('=')
    input_link2 = f"vmess://{vmess_b642}"
    
    result2 = rewrite_vmess(input_link2, server_cfg)
    result_b642 = result2[8:]
    result_json2 = json.loads(base64.b64decode(result_b642 + '==').decode())
    
    assert result_json2["tls"] == "reality", \
        f"Existing tls should be preserved. Got: {result_json2['tls']}"
    assert result_json2["sni"] == "example.com", \
        f"Existing sni should be preserved. Got: {result_json2['sni']}"
    assert result_json2["add"] == "gateway.asgaroth.ru", \
        f"Host should still be rewritten. Got: {result_json2['add']}"
    
    print("✓ test_vmess_rewrite (tls/sni preserved) passed")
    
    # Тест 3: add уже публичный -> не изменен
    vmess_json3 = {
        "v": "2",
        "ps": "Test",
        "add": "example.com",
        "port": "443",
        "id": "uuid",
        "aid": "0"
    }
    vmess_b643 = base64.b64encode(json.dumps(vmess_json3, separators=(',', ':')).encode()).decode().rstrip('=')
    input_link3 = f"vmess://{vmess_b643}"
    
    result3 = rewrite_vmess(input_link3, server_cfg)
    assert result3 == input_link3, f"Non-localhost link should be unchanged. Got: {result3}"
    
    print("✓ test_vmess_rewrite (non-localhost) passed")


def test_rewrite_proxy_links():
    """Тест главной функции rewrite_proxy_links"""
    server_cfg = XuiServerConfig(
        server_id="server1",
        public_host="gateway.asgaroth.ru",
        public_port=443
    )
    
    # Тест определения протокола
    vless_link = "vless://uuid@127.0.0.1:20000?type=xhttp#test"
    result = rewrite_proxy_links(vless_link, server_cfg)
    assert result.startswith("vless://uuid@gateway.asgaroth.ru:443"), \
        f"Should rewrite VLESS. Got: {result}"
    
    trojan_link = "trojan://pass@127.0.0.1:443#test"
    result2 = rewrite_proxy_links(trojan_link, server_cfg)
    assert result2.startswith("trojan://pass@gateway.asgaroth.ru:443"), \
        f"Should rewrite Trojan. Got: {result2}"
    
    ss_link = "ss://YWVzLTI1Ni1nY206cGFzc3dvcmQ=@127.0.0.1:443#test"
    result3 = rewrite_proxy_links(ss_link, server_cfg)
    assert result3.startswith("ss://"), f"Should rewrite SS. Got: {result3}"
    
    # Неизвестный протокол
    unknown_link = "hy2://user:pass@127.0.0.1:443"
    result4 = rewrite_proxy_links(unknown_link, server_cfg)
    assert result4 == unknown_link, f"Unknown protocol should be unchanged. Got: {result4}"
    
    print("✓ test_rewrite_proxy_links passed")


if __name__ == "__main__":
    print("Running LinkRewriter tests...\n")
    
    try:
        test_vless_rewrite()
        test_vless_security_preserved()
        test_trojan_rewrite()
        test_ss_rewrite()
        test_vmess_rewrite()
        test_rewrite_proxy_links()
        
        print("\n✅ All tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
