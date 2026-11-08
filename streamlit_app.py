import hmac
import os
from threading import Lock
from time import monotonic

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from core import DemoService, HandoffError
from model_demo import EXAMPLE, run_synthetic


CASES = {"hlj-production": "肇东农林植保", "hlj-transport": "呼玛短途运输"}
QUESTIONS = [
    "Q1 · 植保有何地区条件？能判断落地吗？",
    "Q2 · 历史指标为何为空？是不是零需求？",
    "Q3 · 呼玛航线依据在哪？计划年怎么填？",
    "模型 · 合成例联调",
]


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


def render_case(service, case_id, query):
    analysis = service.call_tool("analyze_region", {"case_id": case_id})
    case = analysis["case"]
    st.subheader(CASES[case_id])
    years = st.columns(3)
    years[0].metric("资料基准年", str(case["data_year"]))
    years[1].metric("机场设施启用年", str(case["facility_start_year"]))
    years[2].metric("任务计划年", str(case["planned_year"] or "未证实"))
    if case_id == "hlj-transport":
        st.info("清单列有推进固定航线的计划。机场 2024 年启用，航线的计划年和运行状态仍待核实。")
    else:
        st.info("公报数据和植保场景支持进一步核实需求。落地判断还需要作业记录、适用空域和运行许可。")
    st.markdown("#### 待核建议")
    st.write(analysis["suggestion"])
    for item in analysis["verification_needed"]:
        st.markdown(f"- {item}")
    st.caption(case["coverage"])
    st.markdown("#### 证据")
    result = service.call_tool("evidence_query", {"case_id": case_id, "query": query})
    render_evidence(result)


def render_history(service):
    view = service.call_tool("explain_evaluation", {"case_id": "hlj-production"})
    history = view["result"]
    st.subheader("黑龙江省历史计算状态")
    st.caption("历史快照 · 两个案例共用 · 数据年 2024")
    st.info("历史需求输入未完整审核，当前缺少样本范围签发与合格承载发布。空值表示指标尚无法给出，不能据此判断零需求。")
    metrics = {"N": history["N"], "D": history["D"], **history["metrics"]}
    for col, (label, value) in zip(st.columns(len(metrics)), metrics.items()):
        col.metric(label, "未计算" if value is None else str(value))
    st.write(f"计算版本 `{history['model_version']}` · 数据版本 `{history['data_version']}`")
    st.caption("历史适飞变体用 2025 年度值作占位，场景适用空域仍缺证。")


@st.cache_resource
def model_throttle():
    return Lock(), [0.0]


def render_model():
    st.subheader("大模型接入测试")
    st.caption("只会发送页面下方的合成问题。模型回复独立展示。")
    st.write(EXAMPLE)
    try:
        secret_values = st.secrets.to_dict()
    except StreamlitSecretNotFoundError:
        secret_values = {}
    names = ("MODEL_BASE_URL", "MODEL_NAME", "MODEL_API_KEY", "MODEL_DEMO_CODE")
    config = {name: str(secret_values.get(name, os.environ.get(name, ""))) for name in names}
    code = config["MODEL_DEMO_CODE"]
    if len(code) < 16 or not all(config[name] for name in names[:-1]):
        st.info("云端模型暂未启用。其他三个演示问题可直接体验。")
        return
    supplied = st.text_input("模型联调码", type="password", max_chars=128)
    if not hmac.compare_digest(code.encode("utf-8"), supplied.encode("utf-8")):
        return
    if st.button("运行一次模型联调", type="primary"):
        lock, deadline = model_throttle()
        with lock:
            now = monotonic()
            if now < deadline[0]:
                st.warning("联调间隔为 30 秒，请稍后重试。")
                return
            deadline[0] = now + 30
        with st.spinner("等待模型返回…"):
            st.session_state["model_probe"] = run_synthetic(config)
    result = st.session_state.get("model_probe")
    if result:
        if result["status"] == "CONNECTED":
            st.success("模型已返回")
            st.text(result["answer"])
        else:
            http_code = result.get("http_code")
            status = result["status"]
            st.warning(f"模型调用未完成 · {status}" + (f" · HTTP {http_code}" if http_code else ""))


st.set_page_config(page_title="因空制宜 Agent", page_icon="🛩️", layout="centered")
st.title("因空制宜 Agent")
st.caption("黑龙江 2024 · 规则分析 / 资料检索 / 历史状态")
st.warning("比赛演示快照。在线正式评分暂未开放，场景分析供核查资料与准备评估。")
question = st.radio("选择一个示例", QUESTIONS)
if question == QUESTIONS[3]:
    render_model()
else:
    try:
        service = DemoService()
        if question == QUESTIONS[0]:
            render_case(service, "hlj-production", "")
        elif question == QUESTIONS[1]:
            render_history(service)
        else:
            query = st.text_input("本地证据关键词", value="短途运输", max_chars=200)
            render_case(service, "hlj-transport", query)
    except HandoffError as exc:
        st.error(f"演示数据暂不可用 · {exc.code}")
