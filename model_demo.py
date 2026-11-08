"""External inference for one fixed synthetic example."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


SYSTEM = "你正在参加一个合成示例测试。只解释给定事实，使用简短中文。"
EXAMPLE = "虚构城市甲有一条拟开通航线，当前只确认机场已启用，缺少客流记录与航线运行许可。请说明已知事实、两项待补材料及能否认定航线已运行。请勿给出分数。"
ENDPOINTS = {
    "https://api.openai.com/v1": ("openai", "/chat/completions"),
    "https://api.deepseek.com": ("openai", "/chat/completions"),
    "https://api.deepseek.com/v1": ("openai", "/chat/completions"),
    "https://api.anthropic.com": ("anthropic", "/v1/messages"),
    "https://api.anthropic.com/v1": ("anthropic", "/messages"),
}
MAX_BODY = 256_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def run_synthetic(environ):
    """Read operator-only settings. No case, user text, tool output, or IDs are accepted."""
    base = environ.get("MODEL_BASE_URL", "").strip().rstrip("/")
    key = environ.get("MODEL_API_KEY", "").strip()
    model = environ.get("MODEL_NAME", "").strip()
    if not (base and key and model):
        return {"status": "NOT_CONFIGURED"}
    if base not in ENDPOINTS:
        return {"status": "ENDPOINT_NOT_ALLOWED"}
    protocol, route = ENDPOINTS[base]
    body = {"model": model, "max_tokens": 256, "messages": [{"role": "user", "content": EXAMPLE}]}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if protocol == "anthropic":
        body["system"] = SYSTEM
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        body["messages"].insert(0, {"role": "system", "content": SYSTEM})
        headers["Authorization"] = f"Bearer {key}"
        if urlsplit(base).hostname == "api.deepseek.com":
            body["thinking"] = {"type": "disabled"}
    try:
        request = Request(base + route, json.dumps(body).encode("utf-8"), headers)
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=20) as response:
            raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            return {"status": "RESPONSE_TOO_LARGE"}
        result = json.loads(raw)
        if protocol == "anthropic":
            answer = "".join(block["text"] for block in result["content"] if block["type"] == "text")
        else:
            answer = result["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            return {"status": "EMPTY_RESPONSE"}
        return {"status": "CONNECTED", "answer": answer.strip().replace(key, "[redacted]")[:2000]}
    except HTTPError as exc:
        exc.close()
        return {"status": "HTTP_ERROR", "http_code": exc.code}
    except (URLError, OSError):
        return {"status": "UNAVAILABLE"}
    except (ValueError, KeyError, IndexError, TypeError):
        return {"status": "INVALID_RESPONSE"}
