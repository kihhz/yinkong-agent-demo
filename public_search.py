"""Look up public government pages using only allowlisted search terms."""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from model_demo_v4 import NoRedirect
from region_evidence_v1 import PROVINCE_PATTERN


SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
TOPICS = (
    "人口", "城镇化", "统计公报", "低空", "通航", "通用航空", "无人机", "政策",
    "行动方案", "场景清单", "应用场景", "空域", "适飞", "机场", "航线",
    "应急", "植保", "物流", "文旅", "观光", "短途运输", "产业",
)


def public_keywords(prompt):
    """Construct a query from a fixed vocabulary without sending the original message."""
    regions = list(dict.fromkeys(PROVINCE_PATTERN.findall(prompt)))[:2]
    if not regions and "全国" in prompt:
        regions = ["全国"]
    topics = [topic for topic in TOPICS if topic in prompt]
    if not topics or (not regions and topics == ["政策"]):
        return ""
    if not any(topic in topics for topic in ("人口", "城镇化", "统计公报")):
        if "低空" in topics:
            topics.remove("低空")
        topics.insert(0, "低空经济")
    years = list(dict.fromkeys(re.findall(r"(?<!\d)(20[0-3]\d)\s*年", prompt)))[:2]
    return " ".join([*regions, *(f"{year}年" for year in years), *topics[:5]])


def official_domain(url):
    if not isinstance(url, str) or not url or re.search(r"[\s<>\\]", url):
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc.lower() != host:
        return None
    return host if re.fullmatch(r"(?:[a-z0-9-]+\.)+gov\.cn", host) else None


def search_public_pages(api_key, keywords):
    body = {"query": f"{keywords} site:gov.cn", "count": 8, "need_content": False}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"}
    try:
        request = Request(SEARCH_URL, json.dumps(body).encode("utf-8"), headers)
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=15) as response:
            data = response.read(160_001)
        if len(data) > 160_000:
            return {"status": "INVALID_RESPONSE"}
        matches = json.loads(data)["results"]
        if not isinstance(matches, list):
            return {"status": "INVALID_RESPONSE"}
    except HTTPError as exc:
        exc.close()
        return {"status": "HTTP_ERROR", "http_code": exc.code}
    except (URLError, OSError):
        return {"status": "UNAVAILABLE"}
    except (ValueError, KeyError, TypeError):
        return {"status": "INVALID_RESPONSE"}

    results = []
    seen = set()
    for match in matches:
        if not isinstance(match, dict):
            continue
        url = match.get("url")
        host = official_domain(url)
        if not host or url in seen or api_key in url:
            continue
        seen.add(url)
        title = match.get("title")
        snippet = match.get("snippet")
        date = match.get("date")
        results.append({
            "url": url,
            "domain": host,
            "title": " ".join(title.replace(api_key, "[已隐藏]").split())[:140] if isinstance(title, str) else host,
            "snippet": " ".join(snippet.replace(api_key, "[已隐藏]").split())[:240] if isinstance(snippet, str) else "",
            "date": date[:10] if isinstance(date, str) and re.match(r"\d{4}-\d{2}-\d{2}T", date) else None,
        })
        if len(results) == 5:
            break
    return {"status": "OK", "sources": results}
