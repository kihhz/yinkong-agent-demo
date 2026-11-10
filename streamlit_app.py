"""Public Streamlit workbench for judges."""
from collections import deque
from html import escape
from pathlib import Path
from threading import Lock
from time import monotonic

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from judge_experience import LIMITS, build_brief, make_outcome, route_for
from judge_public_evidence import MAX_QUESTION, PUBLIC_SOURCES, answer, catalog_response, conversation_summary
from report_docx import build as word_report

LOGO = Path(__file__).parent / "assets" / "yinkong-logo.jpg"
EXAMPLES = (
    "黑龙江低空经济适合优先核查哪些场景？",
    "现有资料能否说明呼玛短途运输已经运营？",
    "黑龙江农林植保政策如何落到具体任务？",
)
FEATURED = (
    ("国家通用航空装备实施方案", "national-2024", "工业和信息化部等四部门 · 2024"),
    ("黑龙江低空经济发展实施方案", "hlj-policy", "黑龙江省人民政府办公厅 · 2024"),
    ("黑龙江 2024 项目与场景清单", "hlj-zhaodong", "黑龙江省人民政府公开页附件 2 · 2024"),
    ("广州低空应用场景需求", "gz-demand", "广州市交通运输局 · 2026"),
    ("黑龙江 2024 统计公报", "hlj-statistics", "黑龙江省统计局、国家统计局黑龙江调查总队 · 2025"),
)
SOURCE_INDEX = {row["id"]: row for row in PUBLIC_SOURCES}
MODEL_FAILURES = {
    "UNAVAILABLE": "连接中断或响应超时。",
    "HTTP_ERROR": "模型服务请求失败。",
    "EMPTY_RESPONSE": "模型未返回正文。",
    "RESPONSE_TOO_LARGE": "模型回复超过处理上限，请缩小问题范围。",
    "INVALID_RESPONSE": "模型回复格式无法读取。",
    "EVIDENCE_VALIDATION_FAILED": "模型回答未通过引用或数值校验。",
}
DRAFT = "judge_question"
CSS = """
<style>
:root {color-scheme: light;}
[data-testid="stAppViewContainer"] {background:#f4f6f2;}
[data-testid="stHeader"] {background:#f4f6f2;}
[data-testid="stSidebar"] {background:#f5f7f5; border-right:1px solid #dfe7e1; width:272px;}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {padding-top:0;}
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {padding:1.1rem 1rem 1.4rem;}
[data-testid="stMainBlockContainer"] {padding-top:3.7rem; padding-bottom:2.5rem;}
.stMarkdown p, .stMarkdown li {font-size:.94rem; line-height:1.75; overflow-wrap:anywhere;}
[data-testid="stMarkdownContainer"] h1 {font-size:2rem; line-height:1.2; color:#173e35;}
[data-testid="stMarkdownContainer"] h2 {font-size:1.45rem; color:#173e35;}
[data-testid="stMarkdownContainer"] h3 {font-size:1.15rem; color:#173e35;}
.judge-eyebrow {font-size:.8rem; color:#687c71; font-weight:650; letter-spacing:.09em;}
.judge-chip {display:inline-block; padding:.2rem .64rem; margin-bottom:.25rem; border-radius:999px;
    background:#e7f1e9; color:#245c48; font-weight:650; font-size:.78rem;}
.judge-chip-warn {background:#f8ebd7; color:#775018;}
.judge-history {white-space:nowrap; overflow:hidden; text-overflow:ellipsis; padding:.3rem .6rem;
    font-size:.9rem; color:#50695e;}
.judge-history-current {background:#e7f1e9; color:#173e35; border-radius:.55rem; font-weight:650;}
.st-key-brand-logo img, .st-key-welcome-logo img {border-radius:.75rem;}
.st-key-workbench > div > [data-testid="stHorizontalBlock"] {align-items:flex-start;}
[data-testid="stChatMessage"] {background:white; border:1px solid #dfe7e1; border-radius:.8rem;
    padding:.7rem .85rem;}
.st-key-dialogue [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    align-self:flex-end; max-width:90%; width:fit-content; background:#e5f0e9; flex-direction:row-reverse;
}
.st-key-results-card, .st-key-welcome {background:#fff; border:1px solid #dfe7e1;
    border-radius:.85rem; padding:1rem;}
.st-key-example-questions button {background:#fff; border-color:#dfe7e1; text-align:left;}
.st-key-example-questions button:hover {border-color:#245c48; color:#173e35;}
.st-key-example-questions button p {width:100%; text-align:left;}
[data-testid="stExpander"] details, [data-testid="stForm"] {border-color:#dfe7e1; border-radius:.75rem;}
@media (max-width:850px) {
    .st-key-workbench > div > [data-testid="stHorizontalBlock"] {flex-direction:column; gap:1rem;}
    .st-key-workbench > div > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        width:100%; min-width:0; flex:1 1 100%;
    }
    [data-testid="stMainBlockContainer"] {padding:3.6rem .9rem 1.25rem;}
    [data-testid="stMarkdownContainer"] h1 {font-size:1.7rem;}
}
</style>
"""


@st.cache_resource
def request_window():
    return Lock(), deque()


def reserve_request():
    now = monotonic()
    session = st.session_state.setdefault("judge_requests", deque())
    while session and now - session[0] >= 600:
        session.popleft()
    if len(session) >= 10 or (session and now - session[-1] < 2):
        return False
    lock, shared = request_window()
    with lock:
        while shared and now - shared[0] >= 86400:
            shared.popleft()
        if len(shared) >= 180 or sum(now - t < 3600 for t in shared) >= 60:
            return False
        shared.append(now)
    session.append(now)
    return True


def model_key():
    try:
        return str(st.secrets.get("MODEL_API_KEY") or st.secrets.get("MAAS_API_KEY") or "").strip()
    except StreamlitSecretNotFoundError:
        return ""


def new_chat():
    st.session_state["judge_turns"] = []
    st.session_state[DRAFT] = ""
    st.session_state.pop("judge_pending_question", None)


def prefill(question):
    st.session_state[DRAFT] = question


def queue_question():
    if question := st.session_state[DRAFT].strip():
        st.session_state["judge_pending_question"] = question
        st.session_state[DRAFT] = ""


def badge(label, warning=False):
    style = " judge-chip-warn" if warning else ""
    st.markdown(f'<span class="judge-chip{style}">{escape(label)}</span>', unsafe_allow_html=True)


def sidebar(key, turns):
    with st.sidebar:
        with st.container(key="brand-logo"):
            st.image(str(LOGO), width=174)
        st.markdown("### 因空制宜")
        st.caption("低空经济决策助手")
        badge("评委体验")
        st.button("＋ 新建对话", on_click=new_chat, type="primary", width="stretch")
        st.markdown("### 历史问题")
        if not turns:
            st.caption("暂无问题")
        for i, turn in enumerate(reversed(turns[-6:])):
            question = escape(turn["question"], quote=True)
            style = " judge-history-current" if i == 0 else ""
            st.markdown(f'<div class="judge-history{style}" title="{question}">{question}</div>',
                        unsafe_allow_html=True)
        st.caption("仅保存在当前浏览器会话。")
        st.markdown("### 精选资料库")
        for short, source_id, metadata in FEATURED:
            row = SOURCE_INDEX[source_id]
            with st.expander(short):
                title = ("2024年黑龙江省低空经济发展重点项目和应用场景清单"
                         if source_id == "hlj-zhaodong" else row["title"])
                st.markdown(f"**{title}**")
                st.caption(metadata)
                st.caption("本体验版未随网页提供本地 PDF。")
                st.link_button("查看原文", row["url"])
        st.markdown("### 模型状态")
        badge("华为云模型已配置" if key else "华为云模型未配置", warning=not key)
        if not key:
            st.caption("当前使用确定性资料核查。")
        st.caption("体验范围：公开资料问答与定性分析。文件上传、OCR、正式数值评价和专业审核暂未开放。")


def render_sources(rows):
    if not rows:
        st.caption("暂无直接公开依据。")
    for row in rows:
        with st.expander(f"[{row['number']}] {row['title']}"):
            st.caption(row["locator"])
            st.markdown(row["text"])
            if row["url"]:
                st.link_button("查看原文", row["url"])


def render_reply(turn):
    view, status = turn["view"], turn["result"]["status"]
    badge(view["route"])
    if status in MODEL_FAILURES:
        st.error("华为云模型暂不可用。" + MODEL_FAILURES[status])
    elif status == "RATE_LIMIT":
        st.warning("本次未调用模型。体验调用额度暂时用完，请稍后重试。")
    if status not in {"CONNECTED", "CATALOG"}:
        st.caption("以下为系统能力说明。" if view["general"] else "以下为确定性资料核查。")
    st.markdown(view["body"])
    if view["sources"] and status != "CATALOG":
        with st.expander("查看公开依据"):
            for row in view["sources"][:4]:
                st.markdown(f"**[{row['number']}] {row['title']}**")
                st.caption(row["locator"])
                st.markdown(row["text"])
                if row["url"]:
                    st.link_button("查看原文", row["url"])
    with st.expander("处理过程"):
        for i, step in enumerate(view["steps"], 1):
            st.markdown(f"{i}. {step}")


def submit(key, turns, prompt):
    route = route_for(prompt, turns)
    turn = catalog_response(prompt)
    if turn is None:
        blocked = bool(key) and not reserve_request()
        turn = answer(key, prompt, turns, use_local=not key or blocked)
        if blocked:
            turn["result"]["status"] = "RATE_LIMIT"
    view = make_outcome(turn, route)
    if not view["general"] and view["core"]:
        view["brief"] = build_brief(prompt, view)
        view["steps"].append("整理当前分析简报")
    turn["view"] = view
    turns.append(turn)


def render_session_summary(turns):
    findings, pending, _ = conversation_summary(turns)
    if not findings and not pending:
        return
    with st.expander("本轮会话总结"):
        for item in findings:
            st.text(item["question"])
            st.markdown(item["note"])
        if pending:
            st.caption("以下问题尚未取得模型结论")
            for question in pending:
                st.text(question)


def results_panel(turn):
    with st.container(key="results-card"):
        st.markdown("## 对话成果")
        if turn is None or turn["view"]["general"]:
            st.caption("提出具体问题后，这里会显示当前结论、依据和简报。")
            return
        view = turn["view"]
        conclusion, sources, status = st.tabs(["结论", "依据", "状态"])
        with conclusion:
            badge(view["label"], warning=view["label"] == "证据不足")
            if view["core"]:
                st.markdown(view["core"])
            for title, field in (("建议先做什么", "suggestions"), ("仍需补齐", "pending")):
                if view[field]:
                    st.markdown(f"**{title}**")
                    for item in view[field]:
                        st.markdown(f"- {item}")
        with sources:
            render_sources(view["sources"])
        with status:
            if view["numeric"] is not None:
                badge("数值未计算", warning=True)
                st.markdown("\n".join(f"- **{field}** 未计算" for field in view["numeric"]))
                st.markdown("\n".join(f"- {limit}" for limit in LIMITS))
                st.caption("null 不等于 0。")
            else:
                st.caption("本题按公开资料问答处理。")
        if brief := view.get("brief"):
            with st.expander("报告预览"):
                st.markdown(brief)
            st.download_button("下载 Markdown", brief, "因空制宜_低空经济分析简报.md", "text/markdown",
                               key="download-md", on_click="ignore")
            st.download_button("下载 Word", word_report(brief), "因空制宜_低空经济分析简报.docx",
                               "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               key="download-word", on_click="ignore")


def main():
    st.set_page_config(page_title="因空制宜 Agent", page_icon=str(LOGO), layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)
    turns = st.session_state.setdefault("judge_turns", [])
    key = model_key()
    st.markdown('<div class="judge-eyebrow">评委体验 · 公开资料</div>', unsafe_allow_html=True)
    st.markdown("# 因空制宜 Agent")
    with st.container(key="workbench"):
        center, right = st.columns([2.4, 1.3], gap="large")
        with center:
            if prompt := st.session_state.pop("judge_pending_question", ""):
                message = "正在检索资料并请求华为云模型…" if key else "正在核查精选公开资料…"
                with st.spinner(message):
                    submit(key, turns, prompt)
            if not turns:
                with st.container(key="welcome"):
                    with st.container(key="welcome-logo"):
                        st.image(str(LOGO), width=200)
                    st.markdown("## 从业务问题到可核查建议")
                    st.markdown("说说你想判断的地区、场景或材料问题。我们会查阅精选公开资料，整理可以确认的依据和仍需核实的条件。")
            else:
                st.markdown("## 对话")
            with st.container(key="dialogue"):
                for turn in turns:
                    with st.chat_message("user"):
                        st.text(turn["question"])
                    with st.chat_message("assistant"):
                        render_reply(turn)
            render_session_summary(turns)
            with st.container(key="example-questions"):
                st.caption("试试这些问题")
                for i, sample in enumerate(EXAMPLES):
                    st.button(sample, key=f"example-{i}", width="stretch", on_click=prefill, args=(sample,))
            with st.form("question-form", border=False):
                st.text_input(
                    "问题", key=DRAFT, label_visibility="collapsed", max_chars=MAX_QUESTION,
                    placeholder="例如：黑龙江哪些低空应用场景值得优先开展受控试点？",
                )
                st.form_submit_button("发送", type="primary", on_click=queue_question)
        with right:
            results_panel(turns[-1] if turns else None)
    sidebar(key, turns)


if __name__ == "__main__":
    main()
