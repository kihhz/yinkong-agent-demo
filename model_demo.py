"""External inference and read-only tool routing for approved synthetic questions."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from core.api import find_evidence


QUESTIONS = (
    "虚构城市甲的短途航线可以认定已运营吗？有哪些证据和待补材料？",
    "虚构城市甲的评价指标为什么留空？可以把空值读成零需求吗？",
)
PLANS = (
    {"tool": "evidence_query", "arguments": {"query": "短途航线"}},
    {"tool": "read_verified_result", "arguments": {}},
)
FIXTURE = [
    {"id": "SYNTHETIC-AIRPORT", "quote": "合成记录：虚构城市甲的机场已启用，短途航线仍在筹备。"},
    {"id": "SYNTHETIC-GAPS", "quote": "合成记录：短途航线未见客流记录和航线运行许可。"},
]
PLAN_SYSTEM = (
    '选择一个只读工具，以 JSON 对象回答。问证据、运营或待补材料时用 '
    '{"tool":"evidence_query","arguments":{"query":"短途航线"}}；'
    '问评价指标或零需求时用 {"tool":"read_verified_result","arguments":{}}。'
)
EXPLAIN_SYSTEM = (
    '根据给定的合成工具结果，用 JSON 回答，例如 '
    '{"conclusion":"INSUFFICIENT","explanation":"现有资料不足以得出正式结论。"}。'
    '只写给定事实和缺项，最多两句，不编数字、日期或审批。'
)
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


def _request_model(environ, system, text):
    base = environ.get("MODEL_BASE_URL", "").strip().rstrip("/")
    key = environ.get("MODEL_API_KEY", "").strip()
    model = environ.get("MODEL_NAME", "").strip()
    if not (base and key and model):
        return {"status": "NOT_CONFIGURED"}
    if base not in ENDPOINTS:
        return {"status": "ENDPOINT_NOT_ALLOWED"}
    protocol, route = ENDPOINTS[base]
    body = {"model": model, "max_tokens": 256, "messages": [{"role": "user", "content": text}]}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if protocol == "anthropic":
        body["system"] = system
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        body["messages"].insert(0, {"role": "system", "content": system})
        body["response_format"] = {"type": "json_object"}
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
        usage = result.get("usage", {})
        usage = {name: value for name in ("prompt_tokens", "completion_tokens", "prompt_cache_hit_tokens",
                                         "prompt_cache_miss_tokens", "input_tokens", "output_tokens")
                 if isinstance(usage, dict) and type(value := usage.get(name)) is int and value >= 0}
        return {"status": "CONNECTED", "answer": answer.strip().replace(key, "[redacted]")[:2000],
                "usage": usage}
    except HTTPError as exc:
        exc.close()
        return {"status": "HTTP_ERROR", "http_code": exc.code}
    except (URLError, OSError):
        return {"status": "UNAVAILABLE"}
    except (ValueError, KeyError, IndexError, TypeError):
        return {"status": "INVALID_RESPONSE"}


def _parse(reply):
    try:
        return json.loads(reply["answer"])
    except (ValueError, KeyError):
        return None


def run_synthetic(environ, question_index):
    """The caller can choose a fixture index; it cannot supply outbound text or tool data."""
    if type(question_index) is not int or not 0 <= question_index < len(QUESTIONS):
        return {"status": "SYNTHETIC_QUESTION_NOT_ALLOWED"}
    question = QUESTIONS[question_index]
    plan_reply = _request_model(environ, PLAN_SYSTEM, question)
    if plan_reply["status"] != "CONNECTED":
        return {**plan_reply, "stage": "理解问题"}
    plan = _parse(plan_reply)
    if plan != PLANS[question_index]:
        return {"status": "PLAN_NOT_ALLOWED", "stage": "校验工具计划", "usage": [plan_reply["usage"]]}
    tool = plan["tool"]
    if tool == "evidence_query":
        observation = {"synthetic": True, "matches": find_evidence(FIXTURE, plan["arguments"]["query"], 2),
                       "can_confirm_operation": False}
    else:
        observation = {"synthetic": True, "N": None, "D": None, "S": None, "G": None, "T": None,
                       "missing": ["合成评估范围未签发", "合格承载输入缺失"], "means_zero_demand": False}
    context = json.dumps({"question": question, "tool_result": observation}, ensure_ascii=False)
    final = _request_model(environ, EXPLAIN_SYSTEM, context)
    details = {"tool": tool, "observation": observation, "usage": [plan_reply["usage"]]}
    if final["status"] != "CONNECTED":
        return {**final, **details, "stage": "解释结果"}
    details["usage"].append(final["usage"])
    answer = _parse(final)
    if not isinstance(answer, dict) or set(answer) != {"conclusion", "explanation"}:
        return {"status": "INVALID_EXPLANATION", **details}
    explanation = answer["explanation"]
    if (answer["conclusion"] != "INSUFFICIENT" or not isinstance(explanation, str)
            or not explanation.strip() or len(explanation) > 300 or any(c.isdigit() for c in explanation)):
        return {"status": "INVALID_EXPLANATION", **details}
    return {"status": "CONNECTED", "answer": explanation.strip(), **details}
