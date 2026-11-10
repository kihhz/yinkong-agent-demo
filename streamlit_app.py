"""Public Streamlit workbench for judges."""
from collections import deque
from html import escape
from pathlib import Path
from threading import Lock
from time import monotonic
from uuid import uuid4

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from judge_attachments import FILE_TYPES, MAX_FILE_MB, MAX_FILES, display_name, read_attachment
from judge_evidence import (
    MAX_QUESTION, PUBLIC_SOURCES, REGIONS, STATS_URL, STATS_YEAR,
    answer, catalog_response, conversation_summary, is_greeting, read_pdf,
)
from judge_results import build_brief, make_outcome, route_for
from report_docx import build as word_report

LOGO = Path(__file__).parent / "assets" / "yinkong-logo.jpg"
EXAMPLES = (
    "黑龙江低空经济适合优先核查哪些场景？",
    "现有资料能否说明呼玛短途运输已经运营？",
    "黑龙江农林植保政策如何落到具体任务？",
)
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
[data-testid="stMain"]:has(.st-key-viewport) {overflow:hidden;}
[data-testid="stMainBlockContainer"] {padding:3.3rem clamp(.85rem, 2vw, 2.4rem) .6rem;}
.stElementContainer:has(.judge-style-anchor) {display:none;}
[data-testid="stLayoutWrapper"]:has(> .st-key-viewport) {height:calc(100dvh - 3.9rem); flex:none;}
.st-key-viewport {height:100%; min-height:0; gap:.65rem;}
.st-key-viewport [data-testid="stHeading"] h1 {padding:0;}
.st-key-page-title {flex:none; gap:.15rem;}
.st-key-viewport > [data-testid="stLayoutWrapper"]:has(> .st-key-workbench),
.st-key-workbench > [data-testid="stLayoutWrapper"],
.st-key-chat-shell > [data-testid="stLayoutWrapper"]:has(> .st-key-dialogue) {
    flex:1 1 0; min-height:0;
}
.st-key-workbench {height:100%; min-height:0;}
.st-key-workbench [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-chat-shell) {
    height:100%; min-height:0; align-items:stretch; gap:clamp(.75rem, 1.6vw, 1.5rem);
}
.st-key-workbench [data-testid="stColumn"]:has(.st-key-chat-shell),
.st-key-workbench [data-testid="stColumn"]:has(.st-key-results-card) {height:100%; min-height:0; min-width:0;}
.st-key-workbench [data-testid="stColumn"] > [data-testid="stVerticalBlock"],
.st-key-workbench [data-testid="stColumn"] [data-testid="stLayoutWrapper"]:has(> :is(.st-key-chat-shell, .st-key-results-card)) {
    height:100%; min-height:0; flex:1 1 0;
}
.st-key-chat-shell {height:100%; min-height:0; gap:.5rem;}
.st-key-chat-shell .st-key-dialogue {height:100%; min-height:0; max-height:none; overflow:auto;
    overscroll-behavior:contain; padding:.35rem clamp(.1rem, 2vw, 2rem) .65rem; scrollbar-width:thin;}
.st-key-chat-shell > [data-testid="stLayoutWrapper"]:has(> .st-key-composer) {flex:none;}
.st-key-composer {background:#f4f6f2; padding:.2rem clamp(.1rem, 2vw, 2rem) .2rem;}
.st-key-composer [data-testid="stChatInput"] {border-radius:1.2rem; background:#fff; box-shadow:0 2px 14px #173e3514;}
.st-key-mobile-results {display:none;}
.stMarkdown p, .stMarkdown li {font-size:.94rem; line-height:1.75; overflow-wrap:anywhere;}
[data-testid="stMarkdownContainer"] h1 {font-size:2rem; line-height:1.2; color:#173e35;}
[data-testid="stMarkdownContainer"] h2 {font-size:1.45rem; color:#173e35;}
[data-testid="stMarkdownContainer"] h3 {font-size:1.15rem; color:#173e35;}
.judge-chip {display:inline-block; padding:.2rem .64rem; margin-bottom:.25rem; border-radius:999px;
    background:#e7f1e9; color:#245c48; font-weight:650; font-size:.78rem;}
.judge-chip-warn {background:#f8ebd7; color:#775018;}
.judge-history {white-space:nowrap; overflow:hidden; text-overflow:ellipsis; padding:.3rem .6rem;
    font-size:.9rem; color:#50695e;}
.judge-history-current {background:#e7f1e9; color:#173e35; border-radius:.55rem; font-weight:650;}
.st-key-brand-logo img {border-radius:.75rem;}
.st-key-dialogue [data-testid="stChatMessage"] {background:transparent; padding:.6rem .2rem; max-width:100%;}
.st-key-dialogue [data-testid="stChatMessageContent"] {min-width:0;}
.st-key-dialogue [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    align-self:flex-end; max-width:84%; width:fit-content; margin-left:auto; background:#e5f0e9;
    padding:.65rem .95rem; border-radius:1.2rem 1.2rem .35rem 1.2rem;
}
.st-key-dialogue [data-testid="stChatMessageAvatarUser"] {display:none;}
.st-key-dialogue [data-testid="stText"] {white-space:pre-wrap; overflow-wrap:anywhere;}
.st-key-results-card, .st-key-welcome {background:#fff; border:1px solid #dfe7e1;
    border-radius:.85rem; padding:1rem;}
.st-key-workbench .st-key-results-card {height:100%; max-height:none; min-height:0; overflow:auto;
    overscroll-behavior:contain; scrollbar-width:thin;}
.st-key-example-questions button {background:#fff; border-color:#dfe7e1; text-align:left;}
.st-key-example-questions button:hover {border-color:#245c48; color:#173e35;}
.st-key-example-questions button p {width:100%; text-align:left;}
[data-testid="stExpander"] details, [data-testid="stForm"] {border-color:#dfe7e1; border-radius:.75rem;}
@media (max-width:930px) {
    .st-key-mobile-results {display:block;}
    .st-key-workbench [data-testid="stColumn"]:has(.st-key-chat-shell),
    .st-key-workbench [data-testid="stColumn"]:has(.st-key-results-card) {width:100%; flex:1 1 100%;}
    .st-key-viewport:not(:has(.st-key-mobile-results input:checked)) [data-testid="stColumn"]:has(.st-key-results-card),
    .st-key-viewport:has(.st-key-mobile-results input:checked) [data-testid="stColumn"]:has(.st-key-chat-shell) {
        display:none;
    }
    [data-testid="stMarkdownContainer"] h1 {font-size:1.7rem;}
}
</style>
<span class="judge-style-anchor" hidden></span>
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
    st.session_state["judge_composer_id"] = uuid4().hex
    st.session_state["show-results"] = False
    st.session_state.pop("judge_pending_question", None)
    clear_attachments()


def clear_attachments():
    st.session_state.pop("judge_attachments", None)
    st.session_state.pop("judge_attachment_group", None)


def prefill(question, draft_key):
    st.session_state[draft_key] = question


def queue_question(draft_key):
    submission = st.session_state[draft_key]
    if submission is not None:
        question = submission.text.strip()
        if question or submission.files:
            st.session_state["judge_pending_question"] = (question, submission.files)


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
        st.markdown("### 资料库")
        for region in dict.fromkeys(row["region"] for row in PUBLIC_SOURCES):
            with st.expander(region):
                for row in PUBLIC_SOURCES:
                    if row["region"] == region:
                        st.markdown(f"- [{row['title']}]({row['url']})")
        with st.expander(f"{len(REGIONS)} 个省级地区基础统计"):
            st.caption(f"{STATS_YEAR} 年人口和城镇化，可直接在对话中按省查询。")
            st.link_button("查看统计来源", STATS_URL)
        st.markdown("### 模型状态")
        badge("华为云模型已配置" if key else "华为云模型未配置", warning=not key)
        if not key:
            st.caption("当前使用确定性资料核查。")


def render_sources(rows):
    if not rows:
        st.caption("暂无直接依据。")
    for row in rows:
        with st.expander(f"[{row['number']}] {row['title']}"):
            st.caption(row["locator"])
            if row["url"]:
                st.markdown(row["text"])
                st.link_button("查看原文", row["url"])
            else:
                st.text(row["text"])


def render_reply(turn):
    view, status = turn["view"], turn["result"]["status"]
    badge(view["route"])
    for message in turn.get("upload_notes", ()):
        st.warning(message)
    if status == "ATTACHMENT_ERROR":
        return
    if status in MODEL_FAILURES:
        st.error("华为云模型暂不可用。" + MODEL_FAILURES[status])
    elif status == "RATE_LIMIT":
        st.warning("本次未调用模型。体验调用额度暂时用完，请稍后重试。")
    if status not in {"CONNECTED", "CATALOG"}:
        st.caption("以下为已提取的资料。" if not view["general"] else "以下为系统能力说明。")
    st.markdown(view["body"])
    if view["sources"] and status != "CATALOG":
        with st.expander("查看依据"):
            for row in view["sources"]:
                st.text(f"[{row['number']}] {row['title']}")
                st.caption(row["locator"])
                if row["url"]:
                    st.markdown(row["text"])
                    st.link_button("查看原文", row["url"])
                else:
                    st.text(row["text"])
    with st.expander("处理过程"):
        for i, step in enumerate(view["steps"], 1):
            st.markdown(f"{i}. {step}")


def store_attachments(files):
    clear_attachments()
    documents, notes = [], []
    if len(files) > MAX_FILES:
        return [f"一次最多可上传 {MAX_FILES} 个文件。请减少附件后重新发送。"]
    for upload in files:
        try:
            item = read_attachment(upload.getvalue(), upload.name, read_pdf)
        except ValueError as error:
            notes.append(f"{display_name(upload.name)}：{error}")
        else:
            documents.append(item)
            if item.truncated:
                notes.append(f"{item.name}：文件内容较多，本次按可读取范围提取片段。")
    if documents:
        st.session_state["judge_attachments"] = tuple(documents)
        st.session_state["judge_attachment_group"] = uuid4().hex
    return notes


def submit(key, turns, prompt, files=()):
    notes = store_attachments(files) if files else []
    attachments = st.session_state.get("judge_attachments", ())
    if files and not attachments:
        turns.append({
            "question": prompt, "regions": (), "cited": [],
            "result": {"status": "ATTACHMENT_ERROR"}, "upload_notes": notes,
            "view": {"route": "会话附件", "general": True},
        })
        return
    route = "会话附件" if attachments and not is_greeting(prompt) else route_for(prompt, turns)
    turn = catalog_response(prompt, has_attachment=bool(attachments)) if not files else None
    if turn is None:
        blocked = bool(key) and not reserve_request()
        turn = answer(key, prompt, turns, use_local=not key or blocked,
                      attachments=attachments if not is_greeting(prompt) else (),
                      attachment_group=st.session_state.get("judge_attachment_group")
                      if not is_greeting(prompt) else None)
        if blocked:
            turn["result"]["status"] = "RATE_LIMIT"
    view = make_outcome(turn, route)
    if not view["general"] and view["core"]:
        view["brief"] = build_brief(prompt, view)
        view["steps"].append("整理当前分析简报")
    turn["view"] = view
    turn["upload_notes"] = notes
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
    with st.container(key="results-card", height=500, border=False, autoscroll=False):
        st.markdown("## 对话成果")
        if turn is None or turn["view"]["general"]:
            st.caption("提出具体问题后，这里会显示当前结论、依据和简报。")
            return
        view = turn["view"]
        conclusion, sources, report_tab = st.tabs(["结论", "依据", "简报"])
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
        with report_tab:
            if brief := view.get("brief"):
                st.download_button("下载 Markdown", brief, "因空制宜_低空经济分析简报.md", "text/markdown",
                                   key="download-md", on_click="ignore")
                st.download_button("下载 Word", word_report(brief), "因空制宜_低空经济分析简报.docx",
                                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                   key="download-word", on_click="ignore")
                st.markdown(brief)


def main():
    st.set_page_config(page_title="因空制宜 Agent", page_icon=str(LOGO), layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)
    turns = st.session_state.setdefault("judge_turns", [])
    draft_key = DRAFT + st.session_state.get("judge_composer_id", "")
    key = model_key()
    with st.container(key="viewport"):
        with st.container(key="page-title"):
            st.markdown("# 因空制宜 Agent")
            with st.container(key="mobile-results"):
                st.toggle("查看对话成果", key="show-results")
        with st.container(key="workbench"):
            center, right = st.columns([2.4, 1.3])
            with center, st.container(key="chat-shell"):
                with st.container(key="dialogue", height=500, border=False, autoscroll=True):
                    if not turns and not st.session_state.get("judge_pending_question"):
                        with st.container(key="welcome"):
                            st.markdown("## 从业务问题到可核查建议")
                            st.markdown("直接询问地区、应用场景或政策。回答会附上所用资料。")
                        with st.container(key="example-questions"):
                            st.caption("试试这些问题")
                            for i, sample in enumerate(EXAMPLES):
                                st.button(sample, key=f"example-{i}", width="stretch",
                                          on_click=prefill, args=(sample, draft_key))
                    for turn in turns:
                        render_turn(turn)
                    if submission := st.session_state.pop("judge_pending_question", None):
                        prompt, files = submission
                        if not prompt or (files and is_greeting(prompt)):
                            prompt = "请概括上传附件的主要内容，并标明依据。"
                        with st.chat_message("user"):
                            st.text(prompt)
                        with st.chat_message("assistant"):
                            with st.spinner("正在查找资料并整理回答…"):
                                submit(key, turns, prompt, files)
                            render_reply(turns[-1])
                    render_session_summary(turns)
                    if turns:
                        with st.expander("示例问题"):
                            for i, sample in enumerate(EXAMPLES):
                                st.button(sample, key=f"example-{i}", on_click=prefill, args=(sample, draft_key))
                with st.container(key="composer"):
                    if attachments := st.session_state.get("judge_attachments"):
                        st.text("当前附件 · " + "、".join(item.name for item in attachments))
                        st.button("清除附件", on_click=clear_attachments)
                    st.chat_input("输入问题，按 Enter 发送", key=draft_key, max_chars=MAX_QUESTION,
                                  accept_file="multiple", file_type=FILE_TYPES, max_upload_size=MAX_FILE_MB,
                                  on_submit=queue_question, args=(draft_key,))
                    st.caption("点输入框左侧的 ＋ 添加 PDF、DOCX、XLSX 或 CSV。发送后，相关片段由华为云模型处理。")
            with right:
                results_panel(turns[-1] if turns else None)
    sidebar(key, turns)


def render_turn(turn):
    with st.chat_message("user"):
        st.text(turn["question"])
    with st.chat_message("assistant"):
        render_reply(turn)


if __name__ == "__main__":
    main()
