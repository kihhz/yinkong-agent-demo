"""Present the approved demo evidence as actionable case answers."""

from region_evidence_v1 import PROVINCE_PATTERN


HISTORY_REASONS = {
    "N": "评估范围尚未签发",
    "D": "子集未准入，缺已审核需求任务",
    "S": "合格承载数据发布未齐",
    "G": "合格承载数据发布未齐",
    "T": "合格承载数据发布未齐",
}
FOLLOW_UP_TOPICS = {
    "year": ("计划年", "年份", "哪年", "哪一年", "什么时候", "启用"),
    "next": ("补什么", "缺什么", "还缺", "缺哪", "补证", "先做", "先查", "怎么做", "下一步", "怎么验证", "材料"),
    "evidence": ("依据", "来源", "出处", "原文", "证据", "哪来的", "统计公报"),
    "decision": ("为什么", "所以", "可行", "可不可以", "能不能", "能否", "落地", "运营", "审批", "许可", "什么条件"),
}
METHOD_TOPICS = {
    "低空物流": (("物流", "配送", "快递"), "先核对货量、发货频率、起讫点和地面配送成本，找出能用试点验证的具体线路。"),
    "农林植保": (("植保", "农林作业"), "先选定地块，确认作物、作业窗口与合同需求，记录地面方式的成本和效果。"),
    "载人短途运输": (("短途运输", "载人"), "先比较具体起讫点的潜在客流、地面出行时间和机场保障条件。"),
    "低空文旅": (("文旅", "观光"), "先查景区客流、付费意愿和替代体验，划定季节和天气约束。"),
    "低空应用": (("低空", "无人机", "通航"), "先选定要解决的需求、受益人和现有替代方案，明确试点要验证什么。"),
}


def case_topic(prompt):
    return next((topic for topic, terms in FOLLOW_UP_TOPICS.items() if any(term in prompt for term in terms)), None)


def method_topic(prompt):
    if PROVINCE_PATTERN.search(prompt) or any(name in prompt for name in ("呼玛", "肇东")):
        return None
    if not any(word in prompt for word in ("怎么", "如何", "建议", "思路", "入手")):
        return None
    if not any(word in prompt for word in ("试点", "选址", "方案", "流程", "规划", "从哪", "起步")):
        return None
    return next((name for name, (terms, _) in METHOD_TOPICS.items() if any(term in prompt for term in terms)), None)


def method_reply(topic, model_steps=None):
    if model_steps is None:
        model_steps = (
            METHOD_TOPICS[topic][1],
            "在投入前列出运行条件、许可、风险和替代方案，逐项确定证据由谁提供。",
            "确定有条件开展后，从小规模试点开始，记录成本、服务表现和安全情况，再决定是否扩围。",
        )
    return (f"**{topic}试点可以这样拆解**\n\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(model_steps, 1))
            + "\n\n这些是通用方法。具体地点是否适用，需要再查当地资料和项目条件。")


def history_reply():
    return (
        "**这份黑龙江冻结结果的 N、D、S、G、T 都尚未计算。**"
        "空值表示当时缺少计算前提，无法据此判断需求为零或承载能力不足。\n\n"
        "- **N**：评估范围还没签发，需要先确认本次纳入哪些地区和任务。\n"
        "- **D**：需求子集还没准入，需要补齐经过审核的任务明细。\n"
        "- **S、G、T**：合格承载数据尚未发布齐全，暂时无法形成这些结果。\n\n"
        "**补齐顺序**：先定评估范围并审核需求，再补可用于同口径计算的承载数据。"
        "右栏可查看各项阻断原因和版本。"
    )


def case_reply(prompt, analysis, evidence):
    case = analysis["case"]
    transport = case["scene"] == "transport"
    topic = case_topic(prompt)
    evidence_by_kind = {}
    for item in evidence["hits"]:
        evidence_by_kind.setdefault(item["kind"], []).append(item)

    if transport:
        conclusion = "现有清单能支持继续核查呼玛短途运输方案。所选航线何时实施、是否获准或已运营仍待核实。"
        decision = "机场启用只说明设施的时间。确认这条航线的进度，要查到航线本身的计划文件、批准材料或实际运行记录。"
        priority = "先定位拟飞的起讫点和潜在客流，再对比地面替代交通。确认有需求后，核查机场保障和航线许可。"
        follow_up = "可以接着问「计划年怎么填？」或「哪份资料能确认航线已运营？」"
    else:
        conclusion = "肇东已有开展农林植保的业务基础，可以优先核查具体作业需求。所选任务能否落地还要核对地块、作业记录和许可条件。"
        decision = "省级粮食生产和播种面积说明植保值得进一步核查。具体地块的服务需求、作业安全和许可，需要项目级证据。"
        priority = "先拿到目标地块和服务合同或作业台账，再核对作业窗口、机型与安全记录，最后确认空域和运行许可。"
        follow_up = "可以接着问「先补哪几份材料？」或「统计公报能证明什么？」"

    evidence_lines = []
    for item in evidence_by_kind.get("public_task_excerpt", []):
        page = f"第 {item['page']} 页" if item.get("page") is not None else item["locator"]
        evidence_lines.append(f"- **省级项目清单（{page}）**：{item['quote']}")
    if not transport:
        stats = [item["quote"] for item in evidence_by_kind.get("public_statistics", [])
                 if item.get("dimension") in ("农业产业", "农业空间")]
        if stats:
            evidence_lines.append("- **黑龙江统计公报**：" + "".join(stats))
        if topic == "evidence":
            for item in evidence_by_kind.get("policy_direction", []):
                evidence_lines.append(f"- **国家实施方案（{item['locator']}）**：{item['quote']}")

    planned = case["planned_year"]
    planned_text = f"为 {planned} 年" if planned is not None else "未证实，填空（null）"
    years = f"资料年为 {case['data_year']} 年，设施启用年为 {case['facility_start_year']} 年。任务计划年{planned_text}。"
    sections = ["**我的判断**\n\n" + conclusion]
    if topic == "year":
        sections.append("**年份怎么填**\n\n" + years)
    if topic == "next":
        sections.append("**建议的核查顺序**\n\n" + priority + "\n\n" +
                        "\n".join(f"- {item}" for item in analysis["verification_needed"]))
    if evidence_lines:
        sections.append("**查到的依据**\n\n" + "\n".join(evidence_lines) + "\n\n原文链接见右栏「证据来源」。")
    sections.append("**这些资料能说明什么**\n\n" + decision)
    if topic != "next":
        sections.append("**建议先做什么**\n\n" + priority)
    if topic != "year" and transport:
        sections.append(years)
    sections.append(follow_up)
    return conclusion, "\n\n".join(sections)
