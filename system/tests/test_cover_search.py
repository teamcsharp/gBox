"""Cover picker pagination, provider failures and public-only image downloads."""
import io
import socket
import urllib.error
from unittest.mock import Mock

import httpx
import pytest

from gbox import cover_art as cover

PNG = b"\x89PNG\r\n\x1a\n" + bytes(32)


@pytest.fixture(autouse=True)
def clean_search_cache():
    cover._SEARCH_CACHE.clear()
    yield
    cover._SEARCH_CACHE.clear()


def image(number, **kwargs):
    return {"title": f"Grand Theft Auto III cover {number}", "img_src": f"https://images.example/cover-{number}.jpg",
            "thumbnail_src": f"https://thumbs.example/cover-{number}.jpg",
            "url": f"https://covers.example/grand-theft-auto-iii/{number}", **kwargs}


def test_pages_are_nine_distinct_images_from_real_provider_batches(monkeypatch):
    calls = []
    def provider(url, query, page, timeout):
        calls.append((query, page))
        return {"results": [image(i) for i in range((page - 1) * 7, page * 7)] if page <= 3 else []}
    monkeypatch.setattr(cover, "_search_page", provider)
    first = cover.search("Grand Theft Auto III cover")
    second = cover.search("Grand Theft Auto III cover", page=2)
    third = cover.search("Grand Theft Auto III cover", page=3)
    assert [len(row["items"]) for row in (first, second, third)] == [9, 9, 3]
    assert first["has_next"] and second["has_next"] and not third["has_next"]
    assert first["previous_page"] is None and second["previous_page"] == 1
    assert len({item["url"] for row in (first, second, third) for item in row["items"]}) == 21
    assert [page for _, page in calls] == [1, 2, 3, 4]
    assert cover.search("Grand Theft Auto III cover")["items"] == first["items"]
    assert len(calls) == 4


def test_repeated_upstream_batch_never_becomes_fake_next_page(monkeypatch):
    calls = []
    monkeypatch.setattr(cover, "_search_page", lambda url, query, page, timeout:
                        calls.append(page) or {"results": [image(i) for i in range(9)]})
    page = cover.search("Grand Theft Auto III cover")
    assert len(page["items"]) == 9 and not page["has_next"] and calls == [1, 2]
    assert not cover.search("Grand Theft Auto III cover", page=2)["items"]
    assert calls == [1, 2]


def test_duplicate_tracking_urls_svg_noise_and_wrong_game_versions_are_removed(monkeypatch):
    rows = [image(0), image(0, img_src="https://images.example/cover-0.jpg?utm_source=test#fragment"),
            image(1, img_src="//images.example/cover-1.png"), image(2, img_src="https://images.example/a.svg"),
            image(3, title="Grand Canyon scenery", url="https://photos.example/canyon", img_src="https://photos.example/canyon.jpg"),
            image(4, title="Grand Theft Auto IV cover", url="https://covers.example/grand-theft-auto-iv/4"),
            image(5, title="Grand Theft Auto 3 cover"),
            image(6, title="Grand Theft Auto V free upgrade on March 3", url="https://games.example/gta-v-march-3")]
    monkeypatch.setattr(cover, "_search_page", lambda url, query, page, timeout: {"results": rows if page == 1 else []})
    result = cover.search("Grand Theft Auto III cover")
    assert [item["url"] for item in result["items"]] == [
        "https://images.example/cover-0.jpg", "https://images.example/cover-1.png", "https://images.example/cover-5.jpg"]


def test_vimm_requires_real_vimm_provenance_and_reports_empty_results(monkeypatch):
    calls = []
    def provider(url, query, page, timeout):
        calls.append(query)
        return {"results": [image(1, url="https://vimm.net.evil.test/vault/1"),
                            image(2, url="https://vimm.net/vault/2")] if page == 1 else []}
    monkeypatch.setattr(cover, "_search_page", provider)
    result = cover.search("Grand Theft Auto III cover", source="vimm")
    assert calls[0] == "site:vimm.net Grand Theft Auto III cover"
    assert len(result["items"]) == 1 and result["items"][0]["source"] == "Vimm's Lair"
    result = cover.search("Unknown game", source="vimm")
    assert result["items"] == [] and any("Try Web" in warning for warning in result["warnings"])


def test_provider_errors_are_actionable_and_queries_stay_bounded(monkeypatch):
    def unavailable(*args):
        raise cover.CoverSearchError("SearXNG is unavailable")
    monkeypatch.setattr(cover, "_search_page", unavailable)
    with pytest.raises(cover.CoverSearchError, match="SearXNG"):
        cover.search("Grand Theft Auto III cover")
    for kwargs in ({"query": ""}, {"query": "x" * 301}, {"query": "game", "page": 101},
                   {"query": "game", "source": "unknown"}):
        with pytest.raises(ValueError):
            cover.search(**kwargs)


def test_provider_json_403_and_byte_limit(monkeypatch):
    response = httpx.Response(403, request=httpx.Request("GET", "https://search.example/search"))
    class Stream:
        def __enter__(self):
            return response
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: Stream())
    with pytest.raises(cover.CoverSearchError, match="Enable JSON"):
        cover._search_page("https://search.example", "game", 1, 1)
    monkeypatch.setattr(cover, "SEARCH_BYTES", 10)
    response = httpx.Response(200, content=b"x" * 11, request=httpx.Request("GET", "https://search.example/search"))
    with pytest.raises(cover.CoverSearchError, match="4 MB"):
        cover._search_page("https://search.example", "game", 1, 1)


def public_dns(monkeypatch, addresses=("93.184.216.34",)):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in addresses])


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://user:pass@example.org/a.jpg",
                                    "https://example.org/\r\nx", "https://localhost/a.jpg",
                                    "http://[fe80::1%25eth0]/a.jpg"])
def test_download_rejects_unsafe_url_shapes_before_request(url):
    with pytest.raises(ValueError):
        cover.validate_public_url(url)


@pytest.mark.parametrize("addresses", [("127.0.0.1",), ("10.1.2.3",), ("169.254.169.254",),
                                           ("::1",), ("224.0.0.1",), ("93.184.216.34", "10.0.0.1")])
def test_download_rejects_private_or_mixed_dns_answers(monkeypatch, addresses):
    public_dns(monkeypatch, addresses)
    with pytest.raises(ValueError, match="public Internet"):
        cover.validate_public_url("https://images.example/cover.png")


def test_connections_pin_public_ip_and_preserve_tls_hostname(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "create_connection", lambda address, timeout, source:
                        calls.append(address) or object())
    connection = cover._pinned_connection(cover.http.client.HTTPSConnection, ["93.184.216.34"])("images.example:443", timeout=2)
    connection._create_connection(("images.example", 443), 2)
    assert calls == [("93.184.216.34", 443)] and connection.host == "images.example"


def test_redirects_are_revalidated_and_auth_is_never_forwarded(monkeypatch):
    public_dns(monkeypatch)
    calls = []
    def opening(req, **kwargs):
        calls.append(req)
        raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": "http://127.0.0.1/private"}, None)
    opener = Mock(open=opening)
    monkeypatch.setattr(cover.urllib.request, "build_opener", lambda *args: opener)
    original_dns = socket.getaddrinfo
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *args, **kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
                        if host == "127.0.0.1" else original_dns(host, *args, **kwargs))
    with pytest.raises(ValueError, match="public Internet"):
        cover.fetch("https://images.example/cover.png")
    assert len(calls) == 1
    assert all(name.lower() not in ("authorization", "cookie", "proxy-authorization") for name in calls[0].headers)


def test_public_download_still_checks_type_and_size(monkeypatch):
    public_dns(monkeypatch)
    class Response(io.BytesIO):
        headers = {}
    response = Response(PNG)
    monkeypatch.setattr(cover.urllib.request, "build_opener", lambda *args: Mock(open=lambda *a, **k: response))
    assert cover.fetch("https://images.example/cover.png") == PNG
    response = Response(b"<html>not an image</html>")
    with pytest.raises(ValueError, match="did not return a picture"):
        cover.fetch("https://images.example/cover.png")
    response = Response(PNG)
    response.headers = {"Content-Length": str(cover.MAX_BYTES + 1)}
    with pytest.raises(ValueError, match="15 MB"):
        cover.fetch("https://images.example/cover.png")
