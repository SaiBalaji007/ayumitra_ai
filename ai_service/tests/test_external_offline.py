"""Offline behaviour of live external lookups: fail fast, then stop trying for a while."""
import httpx

from ayumitra_ai.external import ExternalSources


def test_connection_failure_skips_further_lookups(tmp_path, monkeypatch):
    calls = []

    def no_network(url, **kw):
        calls.append(url)
        raise httpx.ConnectError("getaddrinfo failed")

    monkeypatch.setattr(httpx, "get", no_network)
    ext = ExternalSources(tmp_path)
    assert ext._get("https://example.org/a", {}) is None
    assert ext._get("https://example.org/b", {}) is None  # skipped: no second wait while offline
    assert ext.search("what is iron deficiency") == []
    assert len(calls) == 1


def test_cached_results_still_work_offline(tmp_path, monkeypatch):
    responses = iter(["cached body"])
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(200, text=next(responses)))
    ext = ExternalSources(tmp_path)
    assert ext._get("https://example.org/a", {"q": 1}) == "cached body"

    def no_network(url, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", no_network)
    assert ext._get("https://example.org/b", {}) is None   # goes offline
    assert ext._get("https://example.org/a", {"q": 1}) == "cached body"  # cache still served


def test_back_online_after_backoff(tmp_path, monkeypatch):
    ext = ExternalSources(tmp_path)
    monkeypatch.setattr(httpx, "get", lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    assert ext._get("https://example.org/a", {}) is None
    ext._offline_until = 0.0  # backoff elapsed
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(200, text="ok"))
    assert ext._get("https://example.org/a", {}) == "ok"
