"""Public regional evidence. The figures below are background, separate from formal evaluation."""

import re


STATS_URL = "https://www.stats.gov.cn/sj/ndsj/2025/html/C02-07.jpg"
STATS_TITLE = "国家统计局《中国统计年鉴 2025》表 2-7"
STATS_YEAR = 2024
REGIONS = {
    "北京": (2183, 88.22),
    "天津": (1364, 86.01),
    "河北": (7378, 63.42),
    "山西": (3446, 66.32),
    "内蒙古": (2388, 70.73),
    "辽宁": (4155, 74.18),
    "吉林": (2317, 65.78),
    "黑龙江": (3029, 68.05),
    "上海": (2480, 89.85),
    "江苏": (8526, 75.53),
    "浙江": (6670, 75.46),
    "安徽": (6123, 62.57),
    "福建": (4193, 71.80),
    "江西": (4502, 63.77),
    "山东": (10080, 66.48),
    "河南": (9785, 59.22),
    "湖北": (5834, 66.35),
    "湖南": (6539, 62.07),
    "广东": (12780, 75.91),
    "广西": (5013, 57.39),
    "海南": (1048, 63.08),
    "重庆": (3190, 72.14),
    "四川": (8364, 60.10),
    "贵州": (3860, 56.65),
    "云南": (4655, 54.11),
    "西藏": (370, 39.68),
    "陕西": (3953, 66.14),
    "甘肃": (2458, 56.83),
    "青海": (593, 63.86),
    "宁夏": (729, 68.22),
    "新疆": (2623, 60.36),
}
PROVINCE_PATTERN = re.compile("|".join(REGIONS))
HLJ_CASE = ("肇东", "呼玛", "冻结", "零需求", "未计算")
STATS_TERMS = ("人口", "城镇化", "城镇比重", "城乡")
LOW_ALTITUDE = ("低空", "政策", "场景", "物流", "文旅", "应急", "适飞", "落地", "承载",
                "航线", "植保", "评分", "指标")
SOURCE_TERMS = ("依据", "来源", "出处", "哪一页", "哪一年", "哪来的")
POLICIES = {
    "云南": {
        "title": "云南省有序拓展低空经济应用场景实施方案",
        "url": "https://yncoop.yn.gov.cn/zfxxgk/zdgknr/wjtz/szfwj/202606/t20260615_3053131.html",
        "year": 2026,
        "summary": "方案把低空观光和航空运动列为消费场景，提出建设主题观光航线、拓展航空研学。",
        "kind": "省级实施方案",
    },
    "吉林": {
        "title": "吉林省低空经济应用场景能力和需求两张清单（2026 年）",
        "url": "https://jldrc.jl.gov.cn/tzgg/202605/t20260511_3629923.html",
        "year": 2026,
        "summary": "省发改委分别发布能力和需求清单，用于产需对接。两类条目按各自清单理解。",
        "kind": "省级场景清单发布页",
    },
    "黑龙江": {
        "title": "黑龙江省加快推动低空经济发展实施方案及场景清单",
        "url": "https://drc.hlj.gov.cn/drc/c111428/202409/c00_31773334.shtml",
        "year": 2024,
        "summary": "省发改委公布实施方案及重点项目和应用场景清单。网页已有肇东农林植保、呼玛短途运输两项证据可查。",
        "kind": "省级实施方案与场景清单",
    },
    "广东": {
        "title": "广东省推动低空经济高质量发展行动方案（2024—2026 年）",
        "url": "https://www.sg.gov.cn/bmpdlm/fgw/zcfg/content/post_2664120.html",
        "year": 2024,
        "summary": "行动方案提出完善低空基础设施、扩大应用场景，按各地场景需求推进无人机应用所需的低空智联网。",
        "kind": "省级行动方案",
    },
    "四川": {
        "title": "四川省人民政府办公厅关于促进低空经济发展的指导意见",
        "url": "https://www.sc.gov.cn/10462/zfwjts/2024/6/4/c881971dfb524140861701724c4e276e/files/%E5%B7%9D%E5%8A%9E%E5%8F%9124%E5%8F%B7%E5%85%AC%E5%BC%80%E7%89%88.pdf",
        "year": 2024,
        "summary": "指导意见提出加快低空基础设施和航线网络建设，推进低空空域管理改革试点，增强飞行服务保障。",
        "kind": "省级指导意见",
    },
}


def lookup_region(prompt, previous=None):
    names = tuple(dict.fromkeys(PROVINCE_PATTERN.findall(prompt)))
    if not names or names == ("黑龙江",):
        if any(word in prompt for word in HLJ_CASE):
            return None
    if names == ("黑龙江",) and any(word in prompt for word in ("植保", "航线", "短途", "评价指标")):
        return None
    stats_requested = any(word in prompt for word in STATS_TERMS)
    low_altitude = any(word in prompt for word in LOW_ALTITUDE)
    source_requested = any(word in prompt for word in SOURCE_TERMS)
    if not names and previous and (stats_requested or low_altitude or source_requested):
        names = previous["region_names"]
        if source_requested and not (stats_requested or low_altitude):
            low_altitude = previous["regional_topic"] == "policy"
    if not names:
        return None

    facts = [
        {"省级地区": name, "数据年": STATS_YEAR, "年末人口（万人）": REGIONS[name][0],
         "城镇人口比重（%）": REGIONS[name][1]}
        for name in names
    ]
    sources = [{"region": name, **POLICIES[name]} for name in names if name in POLICIES] if low_altitude else []
    paragraphs = []
    if stats_requested or (source_requested and not low_altitude):
        years = set(re.findall(r"(?<!\d)20\d{2}(?!\d)", prompt))
        if "最新" in prompt or years - {str(STATS_YEAR)}:
            paragraphs.append(f"资料库目前只接入 {STATS_YEAR} 年的同口径统计。")
        paragraphs.extend(
            f"{name} {STATS_YEAR} 年末人口 {REGIONS[name][0]:,} 万人，城镇人口比重 {REGIONS[name][1]:.2f}%。"
            for name in names
        )
        if len(names) == 2:
            first, second = names
            population_gap = abs(REGIONS[first][0] - REGIONS[second][0])
            urban_gap = abs(REGIONS[first][1] - REGIONS[second][1])
            paragraphs.append(f"两地人口相差 {population_gap:,} 万人，城镇人口比重相差 {urban_gap:.2f} 个百分点。")
    if low_altitude:
        paragraphs.extend(f"{item['region']}（{item['year']} 年）。{item['summary']}" for item in sources)
        missing = [name for name in names if name not in POLICIES]
        if missing:
            paragraphs.append(f"{'、'.join(missing)}目前只有统计背景，低空政策和场景资料待补。")
        if sources:
            paragraphs.append("项目是否运营、航线能否飞行及是否获批，仍需核对项目级材料。")
    if not paragraphs:
        paragraphs.append(f"{'、'.join(names)}目前可查 {STATS_YEAR} 年人口和城镇化。可以继续问低空政策或场景。")
    return {
        "title": " / ".join(names) + (" · 低空资料" if low_altitude else " · 统计背景"),
        "summary": "\n\n".join(paragraphs),
        "region_names": names,
        "regional_topic": "policy" if low_altitude else "stats",
        "facts": facts,
        "regional_sources": sources,
    }
