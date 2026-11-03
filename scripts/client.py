"""Small helper for talking to LeaseLedger and Keystone.

We go slowly on purpose. Both systems share one speed limit.
"""

import json
import time
import urllib.error
import urllib.request

HOST = "https://moab-mesa-case.fly.dev"
BASE = HOST + "/c/mp-d3c30b00d577d2be"
MIN_GAP = 0.15
_last_call = 0.0


def resolve(path):
    """Turn an API path into a full URL.

    The export service returns poll links that already include /c/<workspace>.
    Other calls are relative to the workspace.
    """
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("/c/"):
        return HOST + path
    if path.startswith("/"):
        return BASE + path
    return BASE + "/" + path


def call(method, path, body=None, headers=None):
    """Return status, response headers, and raw bytes.

    Retries when the server asks us to slow down (429) or has a hiccup (503).
    A 503 on a write can mean the save worked, so callers that write must send
    the same Idempotency-Key on the retry.
    """
    global _last_call
    url = resolve(path)
    data = None
    hdrs = {"Accept": "application/json, text/csv, */*"}
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)

    for attempt in range(8):
        wait = _last_call + MIN_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        _last_call = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as err:
            err_body = err.read()
            if err.code in (429, 503):
                retry = err.headers.get("Retry-After")
                delay = float(retry) if retry else min(2 ** attempt, 20)
                time.sleep(delay)
                continue
            text = err_body.decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {url} failed with {err.code}: {text[:800]}") from err
    raise RuntimeError(f"Gave up after several tries: {method} {url}")


def call_json(method, path, body=None, headers=None):
    status, hdrs, raw = call(method, path, body=body, headers=headers)
    if not raw:
        return status, hdrs, None
    return status, hdrs, json.loads(raw.decode("utf-8"))


def call_result(method, path, body=None, headers=None):
    """Like call_json, but a 4xx comes back as data instead of crashing.

    429 and 503 still wait and retry. A write that gets 503 can use the same
    Idempotency-Key on the next try.
    """
    global _last_call
    url = resolve(path)
    data = None
    hdrs = {"Accept": "application/json, text/csv, */*"}
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)

    last_status = None
    last_body = None
    for attempt in range(8):
        wait = _last_call + MIN_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        _last_call = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read()
                parsed = json.loads(raw.decode("utf-8")) if raw else None
                return resp.status, dict(resp.headers), parsed
        except urllib.error.HTTPError as err:
            err_body = err.read()
            text = err_body.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text) if text else None
            except json.JSONDecodeError:
                parsed = {"raw": text[:800]}
            last_status = err.code
            last_body = parsed
            if err.code in (429, 503):
                retry = err.headers.get("Retry-After")
                delay = float(retry) if retry else min(2 ** attempt, 20)
                time.sleep(delay)
                continue
            return err.code, dict(err.headers), parsed
    return last_status, {}, last_body
