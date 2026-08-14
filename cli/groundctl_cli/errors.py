"""Normalizes FastAPI's error response shapes into a single readable string.

FastAPI errors come in two shapes:
  - {"detail": "some string"}                                   (most errors)
  - {"detail": [{"loc": [...], "msg": "...", "type": "..."}]}    (422 validation)

Some endpoints in this app also raise HTTPException with a plain string
detail that happens to look like neither (defensive fallback below).
"""

from __future__ import annotations

import httpx


class GroundctlError(Exception):
    """A clean, user-facing CLI error. Root app catches this and prints
    str(exc) to stderr with a non-zero exit — no traceback."""


def format_error_detail(detail: object) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict) and "msg" in item:
                loc = item.get("loc") or []
                # loc typically looks like ["body", "field_name"] — drop the
                # leading "body"/"query"/"path" marker when present so the
                # message reads as "field_name: msg" rather than "body -> field_name: msg".
                loc_parts = [str(p) for p in loc if p not in ("body", "query", "path")]
                field = ".".join(loc_parts)
                parts.append(f"{field}: {item['msg']}" if field else str(item["msg"]))
            else:
                parts.append(str(item))
        return "; ".join(parts)
    return str(detail)


def error_from_response(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:500]}"

    if isinstance(body, dict) and "detail" in body:
        return f"HTTP {response.status_code}: {format_error_detail(body['detail'])}"
    return f"HTTP {response.status_code}: {body}"
