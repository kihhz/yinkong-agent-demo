import hmac
import os
from collections import deque
from threading import Lock
from time import monotonic

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from case_chat import HISTORY_REASONS, case_reply, case_topic, history_reply, method_reply, method_topic
from demo_core_v2 import DemoService, HandoffError
from model_demo_v4 import CHAT_ENDPOINTS, QUESTIONS as SYNTHETIC_QUESTIONS, draft_method, plan_chat, run_synthetic
from public_search import public_keywords, search_public_pages
from region_evidence_v1 import POLICIES, REGIONS, STATS_TITLE, STATS_URL, lookup_region


CASES = {"hlj-production": "肇东农林植保", "hlj-transport": "呼玛短途运输"}
QUESTIONS = (
    "Q1 · 植保有何地区条件？能判断落地吗？",
    "Q2 · 历史指标为何为空？是不是零需求？",
    "Q3 · 呼玛航线依据在哪？计划年怎么填？",
    "Q4 · 四川和广东 2024 年人口和城镇化差多少？",
    "Q5 · 云南有哪些低空文旅政策？",
)
MODEL_CONNECTION_FIELDS = ("MODEL_BASE_URL", "MODEL_NAME", "MODEL_API_KEY")
SEARCH_KEY_NAME = "DEEPSEEK_SEARCH_API_KEY"
PRODUCTION = "hlj-production"
TRANSPORT = "hlj-transport"


def render_evidence(result):
    sources = {source["id"]: source for source in result["sources"]}
    if not result["hits"]:
        st.info("冻结资料未检出相关片段。可换关键词或补充资料。")
    for item in result["hits"]:
        source = sources[item["source_id"]]
        st.markdown(f"**{item['id']}** · {item['locator']}")
        st.write(item["quote"])
        st.markdown(f"[{source['title']}]({source['url']})")
        if source.get("attachment_url"):
            st.markdown(f"[清单 PDF]({source['attachment_url']})")


def new_chat():
    state = st.session_state
    state.chat_counter += 1
    state.active_chat = state.chat_counter
    state.chats[state.active_chat] = {"messages": []}
    if len(state.chats) > 8:
        del state.chats[next(iter(state.chats))]


def render_sidebar(service):
    state = st.session_state
    if "chats" not in state:
        state.chats = {}
        state.chat_counter = 0
        new_chat()
    with st.sidebar:
        st.subheader("因空制宜")
        st.caption("低空智策 · Agent 工作台")
        st.button("＋ 新建对话", on_click=new_chat, width="stretch")
        labels = {cid: chat.get("title", f"新对话 {cid}") for cid, chat in state.chats.items()}
        st.radio("对话", list(reversed(labels)), key="active_chat", format_func=labels.__getitem__)
        st.divider()
        st.subheader("资料库")
        st.caption(f"{len(REGIONS)} 个省级地区统计背景 · {len(POLICIES)} 地低空政策或场景资料")
        sources = {}
        for case_id, label in CASES.items():
            st.write(f"• {label}")
            for source in service.evidence_query(case_id)["sources"]:
                sources[source["id"]] = source
        with st.expander("查看资料来源", expanded=True):
            st.markdown(f"[{STATS_TITLE}]({STATS_URL})")
            for source in sources.values():
                st.markdown(f"[{source['title']}]({source['url']})")
        model_mode = st.toggle("模型联调")
    return state.chats[state.active_chat], model_mode


def resolve_question(prompt, case_id):
    text = prompt.casefold()
    if any(word in text for word in ("q2", "指标", "评分", "零需求", "空值", "d/s/g/t", "dsgt", "未计算")):
        return "history", case_id or PRODUCTION, ""
    if any(word in text for word in ("q3", "呼玛", "短途", "载人")) or (not case_id and "航线" in text):
        return "case", TRANSPORT, "短途运输"
    if any(word in text for word in ("q1", "植保", "肇东")):
        return "case", PRODUCTION, ""
    if case_id and case_topic(text):
        return "case", case_id, "短途运输" if case_id == TRANSPORT else ""
    return None


def answer_public_search(chat, prompt, api_key):
    keywords = public_keywords(prompt)
    sources = []
    steps = []
    if not keywords:
        summary = "请写明要查的公开主题，例如「浙江低空物流政策」或「江苏 2025 年人口」。本次没有发出搜索请求。"
    elif not reserve_judge_request():
        summary = "本次会话或应用已达到外部请求上限，可以继续使用资料库。"
    else:
        with st.spinner("正在检索政府网站…"):
            reply = search_public_pages(api_key, keywords)
        steps.append(f"检索词 · {keywords}")
        if reply["status"] == "OK":
            sources = reply["sources"]
            steps.append(f"筛选 HTTPS 政府网页 · 保留 {len(sources)} 条")
            summary = (f"找到 {len(sources)} 条政府网站线索。右栏有检索摘要和原文入口，具体口径与项目状态请核对原文。"
                       if sources else "这次未找到符合要求的政府网页。可以换地区或缩短主题后再试。")
        else:
            code = reply.get("http_code")
            steps.append(f"搜索未完成 · HTTP {code}" if code else "搜索未完成 · 接口暂不可用")
            summary = {
                401: "搜索服务未通过鉴权，请让应用管理员检查 DeepSeek 搜索密钥。",
                402: "搜索服务账户余额不足，可以继续使用资料库。",
                429: "搜索服务请求较多，请稍后再试。",
            }.get(code, "搜索暂未完成，可以稍后重试或继续使用资料库。")
    chat["result"] = {"title": "联网检索结果", "summary": summary, "web_sources": sources}
    return summary, steps


def answer_question(service, chat, prompt, model_config=None, search_key=""):
    if search_key:
        return answer_public_search(chat, prompt, search_key)
    topic = method_topic(prompt)
    if topic:
        model_steps = None
        steps = [f"识别为通用方法问题 · {topic}"]
        if model_config and reserve_judge_request():
            with st.spinner("DeepSeek 正在整理试点方案…"):
                model_steps = draft_method(model_config, topic)
        origin = "DeepSeek 通用建议" if model_steps else "本地方法指引"
        steps.append(origin)
        answer = method_reply(topic, model_steps)
        chat.pop("case_id", None)
        chat["result"] = {"title": origin, "summary": answer, "method_guidance": True}
        return answer, steps

    previous = chat.get("result")
    regional = lookup_region(prompt, previous if previous and "facts" in previous else None)
    if regional:
        steps = ["查阅国家统计局 2024 年分地区人口表"]
        if regional["regional_topic"] == "policy":
            steps.append(f"检索公开低空资料 · 命中 {len(regional['regional_sources'])} 份")
        steps.append("资料库只读查询")
        with st.status("省域资料查询完成", state="complete", expanded=False):
            for step in steps:
                st.write(step)
        chat.pop("case_id", None)
        chat["result"] = regional
        return regional["summary"], steps

    active_case = chat.get("case_id")
    route = resolve_question(prompt, active_case)
    steps = []
    if model_config:
        if reserve_judge_request():
            with st.spinner("DeepSeek 正在理解问题…"):
                model_result = plan_chat(model_config, prompt, active_case)
            status = model_result["status"]
            if status == "CONNECTED":
                plan = model_result["plan"]
                case_id = plan["case_id"]
                mode = {"read_verified_result": "history", "analyze_region": "case",
                        "evidence_query": "evidence"}[plan["tool"]]
                route = (mode, case_id, "短途运输" if case_id == TRANSPORT else "")
                steps.append(f"DeepSeek 已识别意图 · {plan['tool']}")
            elif status == "OUT_OF_SCOPE":
                steps.append("DeepSeek 未匹配工具 · 继续检查资料库")
            else:
                http_code = model_result.get("http_code")
                detail = f"HTTP {http_code}" if http_code else status
                steps.append(f"DeepSeek 未完成 · {detail} · 改用本地规则")
                st.caption(steps[-1])
        else:
            steps.append("模型问答达到限额 · 改用本地规则")
            st.caption(steps[-1])
    if route is None:
        chat.pop("result", None)
        return "可查各省级地区 2024 年人口和城镇化、部分地区的低空政策，以及黑龙江的植保、呼玛航线和冻结评价。可以写明地区和要查的事项，或试一下上方示例。", steps

    mode, case_id, query = route
    steps.append(f"定位资料 · {'历史评价状态' if mode == 'history' else CASES[case_id]}")
    with st.status("正在处理问题", expanded=True) as status:
        for step in steps:
            st.write(step)
        try:
            if mode == "history":
                history = service.call_tool("read_verified_result", {"case_id": case_id})
                steps.append("读取 C v2 冻结状态 · read_verified_result")
                summary = "N、D、S、G、T 均为空。N 缺评估范围签发，D 缺准入和已审核需求，S/G/T 缺合格承载数据发布。空值不能解释为零需求。"
                answer = history_reply()
                result = {"title": "黑龙江冻结评价状态", "summary": summary, "history": history}
            else:
                evidence = service.call_tool("evidence_query", {"case_id": case_id, "query": query})
                steps.append(f"检索公开资料 · evidence_query · 命中 {len(evidence['hits'])} 条")
                st.write(steps[-1])
                analysis = service.call_tool("analyze_region", {"case_id": case_id})
                steps.append("生成核验建议 · analyze_region")
                summary, answer = case_reply(prompt, analysis, evidence)
                result = {"title": CASES[case_id], "summary": summary, "analysis": analysis, "evidence": evidence}
            st.write(steps[-1])
        except HandoffError as exc:
            status.update(label="处理未完成", state="error", expanded=False)
            return f"资料暂不可用（{exc.code}）。", steps
        chat.update(case_id=case_id, result=result)
        status.update(label="处理完成", state="complete", expanded=False)
    return answer, steps


def render_results(result):
    st.subheader("对话成果")
    if result is None:
        st.info("发出问题后，这里会显示结论、来源和待补资料。")
        return
    conclusion, sources = st.tabs(["结论", "证据来源"])
    lines = [f"# {result['title']}", "", result["summary"]]
    with conclusion:
        st.markdown(f"**{result['title']}**")
        st.write(result["summary"])
        if "history" in result:
            history = result["history"]
            metrics = {"N": history["N"], "D": history["D"], **history["metrics"]}
            st.table([{"指标": label, "结果": "未计算" if value is None else str(value), "原因": HISTORY_REASONS[label]}
                      for label, value in metrics.items()])
            versions = history["versions"]
            version_line = f"{history['schema_version']} · {versions['legacy_model']} · {versions['legacy_data']}"
            st.caption(f"C v2 冻结状态 · {history['snapshot_date']} · {version_line}")
            lines.extend(["", f"冻结状态 {history['snapshot_date']} · {version_line}", "",
                          *(f"- {label}：{HISTORY_REASONS[label]}" for label in metrics)])
        elif "method_guidance" in result:
            st.caption("本次给出的是试点方法。")
        elif "web_sources" in result:
            st.caption("网页搜索只提供资料线索。")
        elif "facts" in result:
            st.table(result["facts"])
            st.caption("统计背景用于了解地区情况。正式评价请查看对应版本的计算状态。")
            lines.extend(["", "## 统计背景", "", "| 省级地区 | 数据年 | 年末人口（万人） | 城镇人口比重（%） |",
                          "| --- | --- | --- | --- |",
                          *(f"| {' | '.join(str(value) for value in row.values())} |" for row in result["facts"])])
        else:
            analysis = result["analysis"]
            case = analysis["case"]
            year_line = f"资料年 {case['data_year']} · 设施启用年 {case['facility_start_year']} · 任务计划年 {case['planned_year'] or '未证实'}"
            st.caption(year_line)
            st.write(analysis["suggestion"])
            st.markdown("**待补资料**")
            for item in analysis["verification_needed"]:
                st.markdown(f"- {item}")
            lines.extend(["", year_line, "", analysis["suggestion"], "",
                          *(f"- {item}" for item in analysis["verification_needed"])])
    with sources:
        if "evidence" in result:
            evidence = result["evidence"]
            render_evidence(evidence)
            lines.extend(["", "## 证据来源",
                          *(f"- [{item['title']}]({item['url']})" for item in evidence["sources"])])
        elif "method_guidance" in result:
            st.caption("本次未检索项目资料。可以补充地区再查具体证据。")
        elif "web_sources" in result:
            for index, item in enumerate(result["web_sources"], start=1):
                st.text(item["title"])
                st.caption(" · ".join(value for value in (item["domain"], item["date"]) if value))
                if item["snippet"]:
                    st.text(item["snippet"])
                st.link_button(f"打开原文 {index}", item["url"])
                lines.append(f"\n- [政府网页 {index}](<{item['url']}>)")
        elif "facts" in result:
            source_links = [f"[{STATS_TITLE}]({STATS_URL})"]
            source_links.extend(f"{item['region']} · {item['year']} · {item['kind']} · [{item['title']}]({item['url']})"
                                for item in result["regional_sources"])
            for link in source_links:
                st.markdown(link)
            lines.extend(["", "## 证据来源", *(f"- {link}" for link in source_links)])
        else:
            st.caption("来源为 C v2 随包的 B 本地运行状态摘要。网页读取冻结状态，当前未执行重算。")
    st.download_button("下载本次成果", "\n".join(lines) + "\n", "因空制宜_对话成果.md",
                       mime="text/markdown", width="stretch", on_click="ignore")


@st.cache_resource
def model_throttle():
    return Lock(), [0.0]


@st.cache_resource
def judge_request_window():
    return Lock(), deque()


def reserve_judge_request():
    used = st.session_state.get("judge_model_requests", 0)
    if used >= 12:
        return False
    lock, recent = judge_request_window()
    with lock:
        now = monotonic()
        while recent and recent[0] <= now - 3600:
            recent.popleft()
        if len(recent) >= 60:
            return False
        recent.append(now)
    st.session_state["judge_model_requests"] = used + 1
    return True


def read_model_config():
    try:
        secret_values = st.secrets.to_dict()
    except StreamlitSecretNotFoundError:
        secret_values = {}
    return {name: str(secret_values.get(name, os.environ.get(name, ""))).strip()
            for name in (*MODEL_CONNECTION_FIELDS, "MODEL_DEMO_CODE", SEARCH_KEY_NAME)}


def capture_chat_consent(chat_id):
    for mode in ("judge", "search"):
        consent_key = f"{mode}-consent-{chat_id}"
        st.session_state[f"{mode}-send-{chat_id}"] = st.session_state.get(consent_key, False)
        if consent_key in st.session_state:
            st.session_state[consent_key] = False


def render_model():
    st.subheader("大模型与工具联调")
    st.caption("合成模式只向模型发送选定的合成问题和对应的合成工具结果。")
    config = read_model_config()
    code = config["MODEL_DEMO_CODE"]
    if len(code) < 16 or not all(config[name] for name in MODEL_CONNECTION_FIELDS):
        st.info("合成联调暂未配置。关闭左栏「模型联调」可返回普通对话。")
        return None
    supplied = st.text_input("模型联调码", type="password", max_chars=128)
    if not hmac.compare_digest(code.encode("utf-8"), supplied.encode("utf-8")):
        return None
    index = st.radio("合成问题", range(len(SYNTHETIC_QUESTIONS)), format_func=SYNTHETIC_QUESTIONS.__getitem__)
    if st.button("运行一次模型联调", type="primary"):
        lock, deadline = model_throttle()
        with lock:
            now = monotonic()
            if now < deadline[0]:
                st.warning("联调间隔为 30 秒，请稍后重试。")
                return None
            deadline[0] = now + 30
        with st.status("模型理解问题、调用只读工具并解释结果", expanded=True) as progress:
            result = run_synthetic(config, index)
            if result.get("tool"):
                st.write(f"已执行合成只读工具 · {result['tool']}")
            done = result["status"] == "CONNECTED"
            progress.update(label="模型闭环完成" if done else "模型闭环未完成",
                            state="complete" if done else "error")
        st.session_state["model_probe"] = (index, result)
    stored = st.session_state.get("model_probe")
    result = stored[1] if stored and stored[0] == index else None
    if result:
        if result["status"] == "CONNECTED":
            st.success("模型已返回")
            st.text(result["answer"])
        else:
            http_code = result.get("http_code")
            status = result["status"]
            stage = result.get("stage", "解释结果")
            st.warning(f"模型调用未完成 · {stage} · {status}" + (f" · HTTP {http_code}" if http_code else ""))
    return result


def main():
    st.set_page_config(page_title="因空制宜 Agent", page_icon="🛩️", layout="wide",
                       initial_sidebar_state="expanded")
    try:
        service = DemoService()
    except HandoffError as exc:
        st.error(f"演示数据暂不可用 · {exc.code}")
        return
    chat, model_mode = render_sidebar(service)
    st.title("因空制宜 Agent")
    st.caption("省域统计对比 · 公开低空资料 · 黑龙江冻结评价")
    center, right = st.columns([1.65, 1], gap="large")
    if model_mode:
        with center:
            model_result = render_model()
        with right, st.container(border=True):
            st.subheader("合成联调成果")
            if model_result and "observation" in model_result:
                st.caption(f"本次执行 · {model_result['tool']}")
                st.json(model_result["observation"], expanded=True)
            if model_result and any(model_result.get("usage", [])):
                st.caption("本次模型接口回传的 Token 用量，扣费以供应商账单为准。")
                st.json(model_result["usage"], expanded=True)
            if model_result is None:
                st.info("运行联调后，这里会显示合成工具的返回。")
        return
    with center:
        st.subheader("对话与处理进程")
        with st.expander("试试这些示例", expanded=True):
            choices = [st.button(q, key=f"example-{index}", width="stretch")
                       for index, q in enumerate(QUESTIONS)]
            example = next((q for q, clicked in zip(QUESTIONS, choices) if clicked), None)
        history = st.container()
        with history:
            if not chat["messages"]:
                st.caption("可以点击示例，也可以在下方提问。")
            for entry in chat["messages"]:
                with st.chat_message("user"):
                    st.text(entry["prompt"])
                with st.chat_message("assistant"):
                    st.write(entry["answer"])
                    if entry["steps"]:
                        with st.expander("处理进程"):
                            for step in entry["steps"]:
                                st.write(step)
        chat_id = st.session_state.active_chat
        config = read_model_config()
        endpoint = config["MODEL_BASE_URL"].rstrip("/")
        chat_enabled = endpoint in CHAT_ENDPOINTS and config["MODEL_API_KEY"] and config["MODEL_NAME"]
        search_key = config[SEARCH_KEY_NAME]
        if chat_enabled:
            provider = "华为云 MaaS" if endpoint == "https://api.modelarts-maas.com/v2" else "DeepSeek"
            st.checkbox(f"允许下一条消息使用{provider}模型",
                        key=f"judge-consent-{chat_id}")
            st.caption("案例问答可发送本条问题和案例标识来识别意图。通用试点建议只发送主题词。资料原文和工具结果留在应用中。")
        if search_key:
            st.checkbox("下一条消息联网查官方网页", key=f"search-consent-{chat_id}",
                        help="只将从消息中识别出的省份、年份和公开主题发给 DeepSeek 搜索。勾选后，这条消息只走搜索工具。")
        typed = st.chat_input("例如：四川和广东城镇化差多少？", max_chars=300,
                              key=f"composer-{chat_id}", on_submit=capture_chat_consent, args=(chat_id,))
        consent = st.session_state.pop(f"judge-send-{chat_id}", False)
        use_search = st.session_state.pop(f"search-send-{chat_id}", False)
        prompt = (example or typed or "").strip()
        if prompt:
            with history:
                with st.chat_message("user"):
                    st.text(prompt)
                with st.chat_message("assistant"):
                    typed_message = typed and not example
                    answer, steps = answer_question(
                        service, chat, prompt,
                        model_config=config if typed_message and consent and chat_enabled else None,
                        search_key=search_key if typed_message and use_search else "",
                    )
                    st.write(answer)
            chat.setdefault("title", prompt[:18] + ("…" if len(prompt) > 18 else ""))
            chat["messages"].append({"prompt": prompt, "answer": answer, "steps": steps})
            chat["messages"] = chat["messages"][-16:]
    with right:
        with st.container(border=True):
            render_results(chat.get("result"))


if __name__ == "__main__":
    main()
