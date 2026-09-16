from __future__ import annotations

import json
import urllib.error
import urllib.request


def request_json(url: str, payload: dict | None = None, *, timeout: float = 30) -> dict:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    # Local inference traffic must not be routed through a machine-wide HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"本地服务 HTTP {error.code}: {detail}") from error
