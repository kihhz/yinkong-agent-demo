"""Presentation of a single public-analysis turn and its exports."""
import re

from judge_evidence import DOMAIN, is_greeting

FORMAL = re.compile(r"数值|指标|评分|打分|承载|测度|排名|N/D/S/G/T", re.I)
FOLLOW_UP = re.compile(r"刚才|上文|前面|上一个|进一步|接着|继续|上述|还有吗|再说说")
DOCUMENT = re.compile(r"这份|这篇|原文|第.{1,4}[页条章]|文件.{0,8}(说|提到|写)")
ANALYSIS = re.compile(r"分析|优先|建议|怎么发展|如何落|怎么落|对比|比较|试点|适合")
HEADINGS = re.compile(r"^#{1,6}\s*(结论|依据|建议先做什么|建议|仍需核实|仍需补齐)\s*[:：]?\s*$", re.M)
CAPABILITIES = "你好！我可以帮你查阅低空经济公开资料，分析地区条件、核对项目进展，并列出下一步要核实的材料。"


def route_for(question, turns):
    if is_greeting(question):
        return "一般对话"
    if turns and FOLLOW_UP.search(question):
        return "结合前文"
    if DOCUMENT.search(question):
        return "资料阅读"
    if ANALYSIS.search(question):
        return "综合分析"
    return "公开资料问答"


def sections(body):
    matches = list(HEADINGS.finditer(body))
    return {
        match[1]: body[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(body)].strip()
        for i, match in enumerate(matches)
    }


def bullets(block):
    return [
        re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", line).strip()
        for line in block.splitlines() if line.strip()
    ]


def make_outcome(turn, route):
    result = turn["result"]
    status = result["status"]
    sources = turn["cited"]
    regions = turn["regions"]
    general = route == "一般对话" or (not turn["sources"] and not DOMAIN.search(turn["question"])
                                    and not FORMAL.search(turn["question"]) and route == "公开资料问答")
    steps = ["识别问题与所需资料"]
    if status == "CATALOG":
        steps.append("读取公开资料目录")
    elif not general:
        steps.append("检索公开资料库")
    if turn.get("uses_attachment"):
        steps.append("读取会话附件并定位相关内容")
    if status in {"CONNECTED", "EVIDENCE_VALIDATION_FAILED"}:
        steps.append("请求华为云模型生成回答")
    if status == "CONNECTED" and sources:
        steps.append("核对引用编号与已检出的来源")
    no_local_evidence = bool(not turn.get("uses_attachment") and regions and any(
        not any(row["region"] == region for row in turn["sources"]) for region in regions
    ))
    unavailable = status not in {"CONNECTED", "CATALOG"}
    body = result.get("answer", "")
    blocks = sections(body)
    summary = blocks.get("结论") or result.get("summary") or body
    first_line = next((line.strip() for line in summary.splitlines()
                       if line.strip() and not line.lstrip().startswith("#")), "")
    core = first_line if len(first_line) <= 175 else first_line[:175] + "…"
    suggestions = bullets(blocks.get("建议先做什么") or blocks.get("建议", ""))[:3]
    pending = bullets(blocks.get("仍需核实") or blocks.get("仍需补齐", ""))
    if unavailable:
        if general:
            body = CAPABILITIES
        else:
            attachment_sources = [row for row in turn["sources"] if row["url"] is None]
            relevant = [row for row in turn["sources"] if row["region"] in regions]
            sources = (attachment_sources or
                       relevant + [row for row in turn["sources"] if row not in relevant])[:4]
            if attachment_sources:
                core = "已提取附件内容，可在「依据」中查看相关片段。"
            elif not sources:
                core = "当前资料库没有找到直接依据。"
            elif no_local_evidence:
                core = "当前资料库缺少部分或全部目标地区的直接依据。"
            else:
                core = "已找到以下公开资料，可据此开始核查。"
            body = core
            if sources and not attachment_sources:
                body += "\n\n" + "\n".join(f"- {row['text']} [{row['number']}]" for row in sources)
            if not attachment_sources:
                pending = ["补查目标地区主管部门公开文件、实际作业或运营记录。"]
    if no_local_evidence and not unavailable:
        pending.insert(0, "部分或全部目标地区缺直接公开依据，需补查当地原文。")
    label = "证据不足" if unavailable or no_local_evidence or not sources else (
        "定性分析" if route in {"综合分析", "结合前文"} else "资料问答"
    )
    return {"route": "一般对话" if general else route, "label": label, "steps": steps,
            "general": general, "body": body, "core": core, "sources": sources,
            "suggestions": suggestions, "pending": pending}


def build_brief(question, outcome):
    lines = ["# 因空制宜 · 低空经济分析简报", "", "## 问题", "", question,
             "", "## 核心判断", "", outcome["core"], "", f"状态：{outcome['label']}"]
    for title, key in (("建议先做什么", "suggestions"), ("仍需补齐", "pending")):
        if outcome[key]:
            lines += ["", f"## {title}", "", *(f"- {item}" for item in outcome[key])]
    if outcome["sources"]:
        lines += ["", "## 依据", ""]
        for row in outcome["sources"]:
            lines += [f"### [{row['number']}] {row['title']}", "", row["locator"], ""]
            if row["url"]:
                lines += [row["text"], "", row["url"], ""]
            else:
                lines += ["来源为本轮会话附件。", ""]
    return "\n".join(lines) + "\n"
