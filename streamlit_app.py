"""Public Streamlit workbench for judges."""
from collections import deque
from hashlib import sha256
from threading import Lock
from time import monotonic
from uuid import uuid4

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from huawei_maas import MAAS_MODEL
from judge_core import MAX_QUESTION, PUBLIC_SOURCES, SCOPE, answer, read_pdf, report
from report_docx import build as word_report

RELEASE = "评委体验版 0.11.4-web.1"
EXAMPLES = (
    ("黑龙江政策", "黑龙江有哪些低空经济政策？请标注出处。"),
    ("黑龙江场景", "请结合黑龙江公开政策和场景清单，分析适合优先调研的场景，说明依据和待补条件。"),
    ("福建与安徽", "比较福建与安徽低空经济应用场景的政策方向和试点前提。"),
)
ERRORS = {
    "NOT_CONFIGURED": "管理员尚未配置华为云模型。请稍后重试。",
    "UNAVAILABLE": "华为云 MaaS 暂未响应，可能是网络异常或超时。请稍后重新发送。",
    "HTTP_ERROR": "华为云 MaaS 返回请求错误。请稍后重试。",
    "EMPTY_RESPONSE": "华为云 MaaS 返回空内容。请稍后重试。",
    "RESPONSE_TOO_LARGE": "华为云 MaaS 响应超过本版上限。请缩小问题范围。",
    "INVALID_RESPONSE": "未能读取华为云 MaaS 的响应。请稍后重试。",
    "EVIDENCE_VALIDATION_FAILED": "华为云已返回，但引用或评分边界校验未通过。请明确地区和问题后重试。",
    "RATE_LIMIT": "体验调用额度暂时用完。请稍后重试。",
    "PDF_CONSENT": "若要基于附件回答，请勾选允许发送相关片段后重新发送。",
}
CSS = """
<style>
[data-testid="stAppViewContainer"] {background: #f7f8fb;}
[data-testid="stSidebar"] {border-right: 1px solid #e3e8ef;}
[data-testid="stHeadingWithActionElements"] h1 {color:#183256; font-size:2rem;}
[data-testid="stChatMessage"] {background:#fff; border-radius:14px; padding:.6rem;}
.yk-brand {display:flex; align-items:center; gap:.65rem; margin-bottom:.7rem;}
.yk-brand strong {font-size:1.16rem; color:#183256;}
.yk-logo {color:white; background:#244e7a; border-radius:10px; padding:.36rem .55rem; font-weight:700;}
.yk-brand small {display:block; color:#566987;}
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
    chats = st.session_state.setdefault("chats", {})
    if len(chats) >= 8:
        del chats[next(iter(chats))]
    key = uuid4().hex
    chats[key] = {"name": "新分析", "turns": [], "pdf": None}
    st.session_state["current_chat"] = key


def update_pdf(chat, uploaded):
    if uploaded is None:
        chat["pdf"] = None
        return
    raw = uploaded.getvalue()
    digest = sha256(raw).hexdigest()
    if chat["pdf"] and chat["pdf"]["key"] == (digest, uploaded.name):
        return
    record = {"key": (digest, uploaded.name), "name": uploaded.name, "pages": []}
    try:
        record["pages"] = read_pdf(raw, uploaded.name)
    except ValueError as error:
        record["error"] = str(error)
    chat["pdf"] = record


def sidebar(cid, chat):
    with st.sidebar:
        st.markdown(
            '<div class="yk-brand"><span class="yk-logo">空</span><div>'
            '<strong>因空制宜</strong><small>低空经济决策助手</small></div></div>',
            unsafe_allow_html=True,
        )
        st.button("＋ 新建会话", on_click=new_chat, width="stretch")
        st.subheader("会话历史")
        for key, item in reversed(list(st.session_state["chats"].items())):
            if st.button(item["name"], key="chat-" + key, width="stretch",
                         type="primary" if key == cid else "secondary"):
                if key != cid:
                    st.session_state["current_chat"] = key
                    st.rerun()
        st.subheader("我的资料")
        widget = st.file_uploader("上传文本型 PDF", type=["pdf"], max_upload_size=3, key="pdf-" + cid)
        update_pdf(chat, widget)
        pdf = chat["pdf"]
        if pdf and pdf.get("error"):
            st.warning(pdf["error"])
        elif pdf:
            st.success(f"已提取 {len(pdf['pages'])} 页文字")
            st.text(pdf["name"])
        with st.expander("精选公开资料"):
            for entry in PUBLIC_SOURCES:
                st.link_button(entry["title"], entry["url"], width="stretch")
        st.caption("会话和附件临时保存。刷新页面或会话断开后，记录可能丢失，请及时下载。")


def render_sources(rows):
    if not rows:
        st.caption("本轮没有引用资料。")
    for row in rows:
        with st.expander(f"[{row['number']}] {row['title']}"):
            st.caption(row["locator"])
            st.text(row["text"])
            if row["url"]:
                st.link_button("打开官方原文", row["url"])
            else:
                st.caption("来自当前会话上传的 PDF。")


def render_reply(turn):
    outcome = turn["result"]
    if outcome["status"] == "CONNECTED":
        st.markdown(outcome["answer"])
        if outcome.get("finish_reason") == "length":
            st.caption("模型达到本轮输出上限，可继续追问。")
    else:
        detail = f" HTTP {outcome['http_code']}。" if outcome.get("http_code") else ""
        st.error(ERRORS.get(outcome["status"], "模型未完成本轮回答。") + detail)
    with st.expander("处理过程"):
        st.write(f"本轮选取 {len(turn['sources'])} 条资料，实际引用 {len(turn['cited'])} 条。")
        st.write(f"模型状态 {outcome['status']}")
        if outcome.get("http_code"):
            st.write(f"华为云 MaaS · {MAAS_MODEL} · HTTP {outcome['http_code']}")
        if outcome.get("elapsed_seconds") is not None:
            st.write(f"模型耗时 {outcome['elapsed_seconds']} 秒")
        usage = outcome.get("usage", {})
        if usage:
            st.write(
                f"输入 {usage.get('prompt_tokens', usage.get('input_tokens', '未返回'))} tokens，"
                f"输出 {usage.get('completion_tokens', usage.get('output_tokens', '未返回'))} tokens"
            )


def submit(key, chat, prompt, allow_pdf):
    pdf = chat["pdf"]
    if pdf and pdf["pages"] and not allow_pdf:
        # General questions may proceed without the attachment. Requests that explicitly reference it
        # should wait for the user's permission instead of pretending it was read.
        if any(term in prompt for term in ("附件", "上传", "这个文件", "这份", "PDF", "pdf")):
            status = "PDF_CONSENT"
        else:
            pdf = None
            status = ""
    else:
        status = ""
    if not status and not key:
        status = "NOT_CONFIGURED"
    if not status and not reserve_request():
        status = "RATE_LIMIT"
    if status:
        return {"question": prompt, "regions": (), "sources": [], "cited": [],
                "result": {"status": status}, "uses_pdf": False}
    with st.spinner("正在检索资料并请求华为云 MaaS…"):
        return answer(key, prompt, chat["turns"],
                      pdf["pages"] if pdf and allow_pdf else (),
                      pdf["name"] if pdf and allow_pdf else "")


def results_panel(turn):
    st.subheader("对话成果")
    if not turn:
        st.info("提出问题后，这里将显示结论、来源和报告。")
        return
    conclusion, sources, preview = st.tabs(["结论", "来源引用", "报告预览"])
    outcome = turn["result"]
    with conclusion:
        if outcome["status"] == "CONNECTED":
            st.markdown(outcome["answer"])
        else:
            st.caption("本轮未形成模型结论。请查看对话中的状态。")
    with sources:
        render_sources(turn["cited"])
        other = [row for row in turn["sources"] if row not in turn["cited"]]
        if other:
            st.caption("以下资料在本轮检索命中，未作为结论引用。")
            render_sources(other)
    with preview:
        if outcome["status"] == "CONNECTED":
            content = report(turn)
            st.markdown(content)
            st.download_button("下载 Markdown", content, "因空制宜_分析报告.md", "text/markdown",
                               key="download-md", on_click="ignore")
            st.download_button("下载 Word", word_report(content), "因空制宜_分析报告.docx",
                               "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               key="download-word", on_click="ignore")
        else:
            st.caption("模型成功返回后可预览和下载报告。")


def main():
    st.set_page_config(page_title="因空制宜 Agent", page_icon="🧭", layout="wide",
                       initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)
    if "current_chat" not in st.session_state:
        new_chat()
    cid = st.session_state["current_chat"]
    chat = st.session_state["chats"][cid]
    sidebar(cid, chat)
    key = model_key()
    st.title("因空制宜 Agent")
    st.caption(f"{RELEASE}  ·  {SCOPE}")
    if not key:
        st.warning("华为云 MaaS 尚未配置。仍可查看公开资料。")
    center, right = st.columns([1.75, 1], gap="large")
    with center:
        st.subheader("对话与处理进程")
        prompt = None
        if not chat["turns"]:
            st.caption("输入地区、场景或想核实的政策。也可试试下面的问题。")
            for column, (label, sample) in zip(st.columns(3), EXAMPLES):
                if column.button(label, key="example-" + label, width="stretch"):
                    prompt = sample
        for turn in chat["turns"]:
            with st.chat_message("user"):
                st.text(turn["question"])
            with st.chat_message("assistant"):
                render_reply(turn)
        pdf = chat["pdf"]
        allow_pdf = False
        if pdf and pdf["pages"]:
            allow_pdf = st.checkbox(
                "允许将这份 PDF 的相关文字片段发送给华为云 MaaS",
                key=f"pdf-consent-{cid}-{pdf['key'][0]}",
            )
        st.caption("提问内容由华为云 MaaS 处理。附件仅在同意后发送相关片段。")
        entered = st.chat_input("输入问题并发送", max_chars=MAX_QUESTION)
        if prompt := (entered or prompt):
            prompt = prompt.strip()
            if prompt:
                turn = submit(key, chat, prompt, allow_pdf)
                if not chat["turns"]:
                    chat["name"] = prompt[:22]
                chat["turns"] = [*chat["turns"][-19:], turn]
                st.rerun()
    with right:
        results_panel(chat["turns"][-1] if chat["turns"] else None)


if __name__ == "__main__":
    main()
