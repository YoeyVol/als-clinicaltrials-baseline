"""ClinicalTrials.gov API v2 client: pagination, retries, schema checks."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from alsmon.constants import (
    API_URL,
    HTTP_RETRIES,
    HTTP_TIMEOUT_SECONDS,
    MAX_PAGES,
    MONITORING_CONDITION,
    MONITORING_FILTER,
    PAGE_DELAY_SECONDS,
    PAGE_SIZE,
    RETRY_STATUSES,
    STUDY_FIELDS,
    USER_AGENT,
)

PageFetch = Callable[[dict[str, str]], dict[str, Any]]
Sleeper = Callable[[float], None]


class ApiError(Exception):
    """Transport, HTTP, or response-schema failure. Callers must not write latest."""


class PaginationError(ApiError):
    """The paged result does not match totalCount or repeats a page token."""


def monitoring_params(*, page_token: str | None = None, count_total: bool = True) -> dict[str, str]:
    params = {
        "query.cond": MONITORING_CONDITION,
        "filter.advanced": MONITORING_FILTER,
        "pageSize": str(PAGE_SIZE),
        "fields": STUDY_FIELDS,
    }
    if count_total:
        params["countTotal"] = "true"
    if page_token:
        params["pageToken"] = page_token
    return params


def broad_count_params() -> dict[str, str]:
    """Background condition-search size, before the drug/biological/EA filter."""
    return {
        "query.cond": MONITORING_CONDITION,
        "pageSize": "1",
        "countTotal": "true",
        "fields": "NCTId",
    }


def is_broad_count_request(params: dict[str, str]) -> bool:
    return (
        params.get("query.cond") == MONITORING_CONDITION
        and "filter.advanced" not in params
        and params.get("pageSize") == "1"
        and params.get("countTotal") == "true"
    )


def request_json(
    url: str,
    *,
    sleeper: Sleeper = time.sleep,
    retries: int = HTTP_RETRIES,
    timeout: float = HTTP_TIMEOUT_SECONDS,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    """GET JSON with backoff on rate limits and transient server errors."""
    delay = 1.0
    last_error = "request failed"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with opener(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                header_map = {key.lower(): value for key, value in response.headers.items()}
                body = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            header_map = {key.lower(): value for key, value in (exc.headers.items() if exc.headers else [])}
            body = exc.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = f"network error: {exc}"
            if attempt >= retries:
                raise ApiError(last_error) from exc
            sleeper(delay)
            delay = min(delay * 2, 30)
            continue

        if status == 200:
            try:
                parsed = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError("response was not JSON") from exc
            if not isinstance(parsed, dict):
                raise ApiError("response JSON was not an object")
            return parsed

        if status in RETRY_STATUSES:
            last_error = f"HTTP {status}"
            if attempt >= retries:
                raise ApiError(last_error)
            retry_after = str(header_map.get("retry-after", ""))
            wait = min(float(retry_after), 60.0) if retry_after.isdigit() else delay
            sleeper(wait)
            delay = min(delay * 2, 30)
            continue

        snippet = body[:300].decode("utf-8", errors="replace")
        raise ApiError(f"HTTP {status}: {snippet}")
    raise ApiError(last_error)


def make_live_page_fetch(
    *,
    sleeper: Sleeper = time.sleep,
    retries: int = HTTP_RETRIES,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> PageFetch:
    def page_fetch(params: dict[str, str]) -> dict[str, Any]:
        url = API_URL + "?" + urllib.parse.urlencode(params)
        return request_json(url, sleeper=sleeper, retries=retries, timeout=timeout)

    return page_fetch


def fetch_all_pages(
    page_fetch: PageFetch,
    *,
    sleeper: Sleeper = lambda _seconds: None,
    page_delay: float = PAGE_DELAY_SECONDS,
    max_pages: int = MAX_PAGES,
) -> dict[str, Any]:
    """Follow nextPageToken until the fetched study count equals totalCount."""
    studies: list[Any] = []
    seen_tokens: set[str] = set()
    token: str | None = None
    total: int | None = None
    pages = 0
    while True:
        pages += 1
        if pages > max_pages:
            raise PaginationError(f"stopped after {max_pages} pages")
        params = monitoring_params(page_token=token, count_total=token is None)
        payload = page_fetch(params)
        if not isinstance(payload, dict) or not isinstance(payload.get("studies"), list):
            raise ApiError("schema break: response has no studies list")
        if token is None:
            reported = payload.get("totalCount")
            if not isinstance(reported, int) or isinstance(reported, bool):
                raise ApiError("schema break: totalCount is missing")
            total = reported
        batch = payload["studies"]
        studies.extend(batch)
        next_token = payload.get("nextPageToken")
        if not next_token:
            break
        if not isinstance(next_token, str):
            raise PaginationError("nextPageToken was not a string")
        if next_token in seen_tokens:
            raise PaginationError("repeated page token")
        seen_tokens.add(next_token)
        token = next_token
        sleeper(page_delay)

    if total is None:
        raise PaginationError("totalCount was not read")
    if len(studies) != total:
        raise PaginationError(f"fetched {len(studies)} studies but totalCount is {total}")
    return {"studies": studies, "totalCount": total, "pagesFetched": pages}


def fetch_broad_count(page_fetch: PageFetch) -> int | None:
    """Best-effort background total. A failure here does not fail the sync."""
    try:
        payload = page_fetch(broad_count_params())
    except ApiError:
        return None
    if not isinstance(payload, dict):
        return None
    total = payload.get("totalCount")
    if isinstance(total, int) and not isinstance(total, bool):
        return total
    return None
