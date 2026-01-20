#!/usr/bin/env python3
"""
Unit-тесты для функции normalize_vless_link
"""
import sys
import os
from pathlib import Path

# Добавляем путь к модулю
sys.path.insert(0, str(Path(__file__).parent))
from normalsub import normalize_vless_link


def test_xhttp_normalization():
    """Тест нормализации xhttp ссылки"""
    input_link = "vless://07ccf3b7-1a47-5d2f-99ca-1f3fd34195ee@127.0.0.1:20000?type=xhttp&encryption=none&path=%2Fxhttp%2F9f3a1cfba29df6b437aed633b158d0e9%2F&host=&mode=auto&security=none#%F0%9F%87%B9%F0%9F%87%B7%20%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F"
    expected_output = "vless://07ccf3b7-1a47-5d2f-99ca-1f3fd34195ee@gateway.asgaroth.ru:443?alpn=h2&encryption=none&fp=chrome&mode=auto&path=%2Fxhttp%2F9f3a1cfba29df6b437aed633b158d0e9%2F&security=tls&sni=gateway.asgaroth.ru&type=xhttp#%F0%9F%87%B9%F0%9F%87%B7%20%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F"
    
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    
    # Сравниваем по частям, так как порядок параметров может отличаться
    assert result.startswith("vless://07ccf3b7-1a47-5d2f-99ca-1f3fd34195ee@gateway.asgaroth.ru:443"), \
        f"Host/port mismatch. Got: {result}"
    assert "#%F0%9F%87%B9%F0%9F%87%B7%20%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F" in result, \
        f"Fragment missing. Got: {result}"
    assert "security=tls" in result, f"security=tls missing. Got: {result}"
    assert "sni=gateway.asgaroth.ru" in result, f"sni missing. Got: {result}"
    assert "alpn=h2" in result, f"alpn=h2 missing. Got: {result}"
    assert "fp=chrome" in result, f"fp=chrome missing. Got: {result}"
    assert "encryption=none" in result, f"encryption=none missing. Got: {result}"
    assert "mode=auto" in result, f"mode=auto missing. Got: {result}"
    assert "path=%2Fxhttp%2F9f3a1cfba29df6b437aed633b158d0e9%2F" in result, f"path missing. Got: {result}"
    assert "type=xhttp" in result, f"type=xhttp missing. Got: {result}"
    
    print("✓ test_xhttp_normalization passed")


def test_grpc_normalization():
    """Тест нормализации grpc ссылки"""
    input_link = "vless://07ccf3b7-1a47-5d2f-99ca-1f3fd34195ee@127.0.0.1:20001?type=grpc&encryption=none&serviceName=cdn&authority=&security=none#%F0%9F%87%B9%F0%9F%87%B7%20%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20(%D0%A0%D0%B5%D0%B7%D0%B5%D1%80%D0%B2)"
    expected_output = "vless://07ccf3b7-1a47-5d2f-99ca-1f3fd34195ee@gateway.asgaroth.ru:443?type=grpc&encryption=none&serviceName=cdn&security=tls&sni=gateway.asgaroth.ru#%F0%9F%87%B9%F0%9F%87%B7%20%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20(%D0%A0%D0%B5%D0%B7%D0%B5%D1%80%D0%B2)"
    
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    
    assert result.startswith("vless://07ccf3b7-1a47-5d2f-99ca-1f3fd34195ee@gateway.asgaroth.ru:443"), \
        f"Host/port mismatch. Got: {result}"
    assert "#%F0%9F%87%B9%F0%9F%87%B7%20%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F%20(%D0%A0%D0%B5%D0%B7%D0%B5%D1%80%D0%B2)" in result, \
        f"Fragment missing. Got: {result}"
    assert "security=tls" in result, f"security=tls missing. Got: {result}"
    assert "sni=gateway.asgaroth.ru" in result, f"sni missing. Got: {result}"
    assert "encryption=none" in result, f"encryption=none missing. Got: {result}"
    assert "serviceName=cdn" in result, f"serviceName=cdn missing. Got: {result}"
    assert "type=grpc" in result, f"type=grpc missing. Got: {result}"
    assert "authority=" not in result, f"Empty authority should be removed. Got: {result}"
    
    print("✓ test_grpc_normalization passed")


def test_non_localhost_unchanged():
    """Тест: ссылки не с 127.0.0.1 должны оставаться без изменений"""
    input_link = "vless://uuid@example.com:443?type=xhttp&security=tls#test"
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    assert result == input_link, f"Non-localhost link should be unchanged. Got: {result}"
    print("✓ test_non_localhost_unchanged passed")


def test_non_vless_unchanged():
    """Тест: не-VLESS ссылки должны оставаться без изменений"""
    input_link = "hy2://user:pass@example.com:443"
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    assert result == input_link, f"Non-VLESS link should be unchanged. Got: {result}"
    print("✓ test_non_vless_unchanged passed")


def test_port_detection():
    """Тест: определение типа по порту, если type не указан"""
    # xhttp по порту 20000
    input_link = "vless://uuid@127.0.0.1:20000?encryption=none&path=/test#name"
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    assert "type=xhttp" in result, f"Should detect xhttp from port 20000. Got: {result}"
    assert "alpn=h2" in result, f"Should add alpn for xhttp. Got: {result}"
    
    # grpc по порту 20001
    input_link = "vless://uuid@127.0.0.1:20001?encryption=none&serviceName=test#name"
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    assert "type=grpc" in result, f"Should detect grpc from port 20001. Got: {result}"
    assert "alpn=h2" not in result, f"Should not add alpn for grpc. Got: {result}"
    
    print("✓ test_port_detection passed")


def test_fragment_preservation():
    """Тест: сохранение фрагмента с URL encoding"""
    fragment = "%F0%9F%87%B9%F0%9F%87%B7%20%D0%A2%D1%83%D1%80%D1%86%D0%B8%D1%8F"
    input_link = f"vless://uuid@127.0.0.1:20000?type=xhttp#fragment"
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    assert "#fragment" in result, f"Fragment should be preserved. Got: {result}"
    
    input_link = f"vless://uuid@127.0.0.1:20000?type=xhttp#{fragment}"
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    assert f"#{fragment}" in result, f"URL-encoded fragment should be preserved. Got: {result}"
    
    print("✓ test_fragment_preservation passed")


def test_existing_params_preserved():
    """Тест: сохранение существующих параметров"""
    input_link = "vless://uuid@127.0.0.1:20000?type=xhttp&custom=value&another=test#name"
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    assert "custom=value" in result, f"Custom params should be preserved. Got: {result}"
    assert "another=test" in result, f"Custom params should be preserved. Got: {result}"
    print("✓ test_existing_params_preserved passed")


def test_empty_params_removed():
    """Тест: удаление пустых параметров"""
    input_link = "vless://uuid@127.0.0.1:20000?type=xhttp&host=&authority=#name"
    result = normalize_vless_link(input_link, "gateway.asgaroth.ru", 443)
    assert "host=" not in result, f"Empty host should be removed. Got: {result}"
    assert "authority=" not in result, f"Empty authority should be removed. Got: {result}"
    print("✓ test_empty_params_removed passed")


if __name__ == "__main__":
    print("Running normalize_vless_link tests...\n")
    
    try:
        test_xhttp_normalization()
        test_grpc_normalization()
        test_non_localhost_unchanged()
        test_non_vless_unchanged()
        test_port_detection()
        test_fragment_preservation()
        test_existing_params_preserved()
        test_empty_params_removed()
        
        print("\n✅ All tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
