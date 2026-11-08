import hmac
import os
from threading import Lock
from time import monotonic

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from core import DemoService, HandoffError
from model_demo import QUESTIONS as SYNTHETIC_QUESTIONS, run_synthetic


CASES = {"hlj-production": "肇东农林植保", "hlj-transport": "呼玛短途运输"}
QUESTIONS = (
    "Q1 · 植保有何地区条件？能判断落地吗？",
    "Q2 · 历史指标为何为空？是不是零需求？",
    "Q3 · 呼玛航线依据在哪？计划年怎么填？",
)
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
        st.caption("黑龙江 2024 · 公开资料")
        sources = {}
        for case_id, label in CASES.items():
            st.write(f"• {label}")
            for source in service.evidence_query(case_id)["sources"]:
                sources[source["id"]] = source
        with st.expander("查看资料来源", expanded=True):
            for source in sources.values():
                st.markdown(f"[{source['title']}]({source['url']})")
        model_mode = st.toggle("模型联调")
    return state.chats[state.active_chat], model_mode


def resolve_question(prompt, case_id):
    text = prompt.casefold()
    if any(word in text for word in ("q2", "指标", "评分", "零需求", "空值", "d/s/g/t", "dsgt", "未计算")):
        return "history", case_id or PRODUCTION, ""
    if any(word in text for word in ("q3", "呼玛", "短途", "航线", "载人")):
        return "case", TRANSPORT, "短途运输"
    if any(word in text for word in ("q1", "植保", "肇东")):
        return "case", PRODUCTION, ""
    if case_id and any(word in text for word in ("依据", "来源", "补", "能否", "落地", "计划年")):
        return "case", case_id, "短途运输" if case_id == TRANSPORT else ""
    return None


def answer_question(service, chat, prompt):
    route = resolve_question(prompt, chat.get("case_id"))
    if route is None:
        return "目前可查询黑龙江的肇东植保、呼玛航线和历史评价状态。请点一个示例，或在提问里写明案例。", []

    mode, case_id, query = route
    steps = [f"识别问题 · {'历史评价状态' if mode == 'history' else CASES[case_id]}"]
    with st.status("正在处理问题", expanded=True) as status:
        st.write(steps[0])
        try:
            if mode == "history":
                history = service.call_tool("explain_evaluation", {"case_id": case_id})["result"]
                steps.append("读取冻结历史结果 · explain_evaluation")
                summary = "N、D、S、G、T 均为未计算。评估范围尚未签发，需求审核和合格承载数据也未齐。缺失值不能解释为零需求。"
                result = {"title": "黑龙江历史评价状态", "summary": summary, "history": history}
            else:
                evidence = service.call_tool("evidence_query", {"case_id": case_id, "query": query})
                steps.append(f"检索公开资料 · evidence_query · 命中 {len(evidence['hits'])} 条")
                st.write(steps[-1])
                analysis = service.call_tool("analyze_region", {"case_id": case_id})
                steps.append("生成核验建议 · analyze_region")
                if case_id == TRANSPORT:
                    summary = "清单记载呼玛通用机场于 2024 年启用，并列出推进固定短途航线的安排。航线计划年和运行状态仍待核实。"
                else:
                    summary = "黑龙江统计公报和肇东植保清单可用于核查需求。判断能否落地，还缺作业记录、适用空域和运行许可。"
                result = {"title": CASES[case_id], "summary": summary, "analysis": analysis, "evidence": evidence}
            st.write(steps[-1])
        except HandoffError as exc:
            status.update(label="处理未完成", state="error", expanded=False)
            return f"资料暂不可用（{exc.code}）。", steps
        chat.update(case_id=case_id, result=result)
        status.update(label="处理完成", state="complete", expanded=False)
    return summary, steps


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
            st.table([{"指标": label, "结果": "未计算" if value is None else str(value)}
                      for label, value in metrics.items()])
            st.caption(f"冻结历史快照 · {history['model_version']} · {history['data_version']}")
            lines.extend(["", f"计算版本 {history['model_version']}，数据版本 {history['data_version']}。"])
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
        else:
            st.caption("来源为已有 B 引擎历史快照的展示字段，页面执行只读查询。")
    st.download_button("下载本次成果", "\n".join(lines) + "\n", "因空制宜_对话成果.md",
                       mime="text/markdown", width="stretch", on_click="ignore")


@st.cache_resource
def model_throttle():
    return Lock(), [0.0]


def render_model():
    st.subheader("大模型与工具联调")
    st.caption("模型只收到选定的合成问题和对应的合成工具结果。真实案例问答在本地只读模式运行。")
    try:
        secret_values = st.secrets.to_dict()
    except StreamlitSecretNotFoundError:
        secret_values = {}
    names = ("MODEL_BASE_URL", "MODEL_NAME", "MODEL_API_KEY", "MODEL_DEMO_CODE")
    config = {name: str(secret_values.get(name, os.environ.get(name, ""))) for name in names}
    code = config["MODEL_DEMO_CODE"]
    if len(code) < 16 or not all(config[name] for name in names[:-1]):
        st.info("云端模型暂未启用。其他三个演示问题可直接体验。")
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
    st.caption("黑龙江 2024 · 比赛演示 · 只读规则工具与冻结结果")
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
        with st.expander("试试这三个示例", expanded=True):
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
        typed = st.chat_input("例如：呼玛航线计划年有证据吗？", max_chars=300,
                              key=f"composer-{st.session_state.active_chat}")
        prompt = (example or typed or "").strip()
        if prompt:
            with history:
                with st.chat_message("user"):
                    st.text(prompt)
                with st.chat_message("assistant"):
                    answer, steps = answer_question(service, chat, prompt)
                    st.write(answer)
            chat.setdefault("title", prompt[:18] + ("…" if len(prompt) > 18 else ""))
            chat["messages"].append({"prompt": prompt, "answer": answer, "steps": steps})
            chat["messages"] = chat["messages"][-16:]
    with right:
        with st.container(border=True):
            render_results(chat.get("result"))


if __name__ == "__main__":
    main()
