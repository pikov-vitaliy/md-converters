from types import SimpleNamespace

import pytest

import convert_to_md


def test_private_url_is_blocked_by_default():
    with pytest.raises(ValueError, match="непубличный адрес"):
        convert_to_md._check_url_allowed(
            "http://127.0.0.1:8000/admin",
            allow_private=False,
        )


def test_private_url_can_be_explicitly_allowed():
    convert_to_md._check_url_allowed(
        "http://127.0.0.1:8000/admin",
        allow_private=True,
    )


def test_public_url_policy_allows_public_resolved_ip(monkeypatch):
    monkeypatch.setattr(
        convert_to_md,
        "_resolved_ips",
        lambda hostname: {"93.184.216.34"},
    )

    convert_to_md._check_url_allowed(
        "https://example.com/page",
        allow_private=False,
    )


def test_url_policy_rejects_non_http_schemes():
    with pytest.raises(ValueError, match="http и https"):
        convert_to_md._check_url_allowed(
            "file:///c:/secret.txt",
            allow_private=True,
        )


def test_read_limited_response_rejects_large_content_length():
    response = SimpleNamespace(
        headers={"content-length": "10"},
        iter_content=lambda chunk_size: [b"ignored"],
    )

    with pytest.raises(ValueError, match="больше лимита"):
        convert_to_md._read_limited_response(response, max_bytes=5)


def test_read_limited_response_rejects_large_stream_without_header():
    response = SimpleNamespace(
        headers={},
        iter_content=lambda chunk_size: [b"1234", b"5678"],
    )

    with pytest.raises(ValueError, match="больше лимита"):
        convert_to_md._read_limited_response(response, max_bytes=5)


def test_parse_url_policy_flags():
    parsed = convert_to_md._parse([
        "https://example.com",
        "--allow-private-url",
        "--url-timeout",
        "3.5",
        "--max-url-mb",
        "2",
    ])

    assert parsed["errors"] == []
    assert parsed["allow_private_url"] is True
    assert parsed["url_timeout"] == 3.5
    assert parsed["max_url_mb"] == 2.0


def test_parse_rejects_invalid_url_policy_numbers():
    parsed = convert_to_md._parse([
        "https://example.com",
        "--url-timeout",
        "0",
        "--max-url-mb",
        "-1",
    ])

    assert parsed["errors"]
