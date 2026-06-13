import sys
from types import SimpleNamespace

import pytest

import convert_to_md


def test_private_url_is_blocked_by_default():
    with pytest.raises(ValueError, match="non-public address"):
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
    with pytest.raises(ValueError, match="http and https"):
        convert_to_md._check_url_allowed(
            "file:///c:/secret.txt",
            allow_private=True,
        )


def test_read_limited_response_rejects_large_content_length():
    response = SimpleNamespace(
        headers={"content-length": "10"},
        iter_content=lambda chunk_size: [b"ignored"],
    )

    with pytest.raises(ValueError, match="exceeds the limit"):
        convert_to_md._read_limited_response(response, max_bytes=5)


def test_read_limited_response_rejects_large_stream_without_header():
    response = SimpleNamespace(
        headers={},
        iter_content=lambda chunk_size: [b"1234", b"5678"],
    )

    with pytest.raises(ValueError, match="exceeds the limit"):
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


def test_download_url_follows_checked_redirect(monkeypatch):
    class Response:
        def __init__(self, status_code, headers, url, body=b""):
            self.status_code = status_code
            self.headers = headers
            self.url = url
            self._body = body
            self.closed = False

        def iter_content(self, chunk_size):
            return [self._body]

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError("unexpected HTTP error")

        def close(self):
            self.closed = True

    class Session:
        def __init__(self):
            self.trust_env = True
            self.headers = {}
            self.urls = []

        def get(self, url, **kwargs):
            self.urls.append((url, kwargs))
            if len(self.urls) == 1:
                return Response(
                    302,
                    {"location": "https://example.com/final.html"},
                    url,
                )
            return Response(
                200,
                {"content-length": "12"},
                "https://example.com/final.html",
                b"<h1>ok</h1>",
            )

        def close(self):
            self.closed = True

    session = Session()
    monkeypatch.setitem(
        sys.modules,
        "requests",
        SimpleNamespace(Session=lambda: session),
    )
    monkeypatch.setattr(
        convert_to_md,
        "_resolved_ips",
        lambda hostname: {"93.184.216.34"},
    )

    data, final_url, suffix = convert_to_md._download_url(
        "https://example.com/start",
        timeout=3,
        max_bytes=100,
        allow_private=False,
    )

    assert data == b"<h1>ok</h1>"
    assert final_url == "https://example.com/final.html"
    assert suffix == ".html"
    assert session.trust_env is False
    assert [url for url, _ in session.urls] == [
        "https://example.com/start",
        "https://example.com/final.html",
    ]
