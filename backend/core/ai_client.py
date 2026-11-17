"""
Client for the internal AyuMitra AI service (OCR, NLP, RAG, LangGraph).

Django is the only caller: browsers never talk to the AI service directly. Requests carry the
shared service token, and only the minimum data needed is sent (one document's bytes, or a question
plus that user's own extracted results).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from django.conf import settings


class AIServiceError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _request(path: str, *, body: bytes, content_type: str, extra_headers: dict | None = None, timeout: float,
             raw: bool = False):
    url = settings.AI_SERVICE_URL.rstrip("/") + path
    headers = {"Content-Type": content_type, "Accept": "application/json", **(extra_headers or {})}
    if settings.AI_SERVICE_TOKEN:
        headers["Authorization"] = f"Bearer {settings.AI_SERVICE_TOKEN}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            return content if raw else json.loads(content.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        try:
            detail = json.loads(detail).get("detail", detail)
        except (ValueError, AttributeError):
            pass
        raise AIServiceError(f"AI service error {exc.code}: {detail}", exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AIServiceError(f"AI service unreachable at {settings.AI_SERVICE_URL}: {exc}") from exc


def analyze_document(data: bytes, content_type: str, document_type: str = "") -> dict:
    """document_type: the type the user chose at upload ("" if unknown); the AI service extracts lab
    results or prescription lines for that type even when its own classifier is unsure (noisy scans)."""
    headers = {"X-Document-Content-Type": content_type}
    if document_type:
        headers["X-Document-Type"] = document_type
    return _request("/v1/documents/analyze", body=data, content_type="application/octet-stream",
                    extra_headers=headers, timeout=settings.AI_SERVICE_OCR_TIMEOUT)


def run_agent(payload: dict) -> dict:
    return _request("/v1/agent", body=json.dumps(payload).encode(), content_type="application/json",
                    timeout=settings.AI_SERVICE_LLM_TIMEOUT)


def render_report_pdf(data: dict) -> bytes:
    return _request("/v1/export/report", body=json.dumps(data).encode(), content_type="application/json",
                    timeout=120, raw=True)


def medicine_info(names: list[str]) -> dict:
    """FDA label information for exactly-identified or user-confirmed medicine names (never guesses)."""
    return _request("/v1/medicine-info", body=json.dumps({"names": names}).encode(), content_type="application/json",
                    timeout=90)
