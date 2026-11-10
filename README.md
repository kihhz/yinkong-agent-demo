# 因空制宜 Agent · 评委体验版

基于现有 GitHub 与 Streamlit Community Cloud，界面按 C 的 V0.11.4 评委体验设计调整。资料检索使用本仓库精选公开摘要，模型由服务端华为云 MaaS 的 deepseek-v4.1-flash-1017 提供。该版本提供定性研判。

[评委体验入口](https://yinkong-agent-demo-wozfzuu5gmiya8njztqgsy.streamlit.app/)

## 使用

1. 在中栏输入问题，或点击示例填入问题后再发送。可在同一会话继续追问。
2. 右栏显示当前回答的结论、公开依据和计算状态，可预览和下载同一份 Markdown 或 Word 简报。对话区可展开整场会话总结。
3. 左栏可查看五个精选入口和最近问题。会话保存在当前浏览器会话中。

提供全国政策及黑龙江、福建、安徽、云南、吉林、广东、四川的精选地方资料，也可查询 31 个省级地区的 2024 年人口和城镇化基础数据。询问“资料库覆盖哪些省份”会直接返回目录。模型启用时，问题及匹配到的公开资料摘要由华为云处理。刷新、断线或重启可能丢失对话。公开版检索限内置资料，文件上传、OCR、正式定量评价和专业审核暂未开放。

## 部署

在 Streamlit Cloud 使用现有仓库 `kihhz/yinkong-agent-demo`、`main` 分支、入口 `streamlit_app.py`。依赖见 `requirements.txt`。

在 App settings → Secrets 保留现有 `MODEL_API_KEY`。新增时填写下列模板并替换占位文本。云端应用亦兼容 `MAAS_API_KEY`。

```toml
MODEL_API_KEY = "填入可用的华为云 MaaS API Key"
```

模型与地址由代码固定为华为云 MaaS 中国站。调用失败时显示状态，并保留已检出的公开资料。每条问题最多一次模型调用，20 秒网络超时，1,350 输出 token 上限。每会话每 10 分钟最多 10 次，间隔至少 2 秒。单进程每小时最多 60 次、滚动 24 小时最多 180 次，进程重启后计数重置。用量与扣费可在华为云控制台核对。

[Streamlit Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management) · [华为云模型接入](https://support.huaweicloud.com/bestpractice-maas/bestpractice_maas_0014_02.html) · [华为云计费说明](https://support.huaweicloud.com/price-maas/price-maas-0002.html)

## 本地运行

```sh
python -m pip install -r requirements.txt
python -m unittest -v test_judge_core
python -m streamlit run streamlit_app.py
```

本地真实联调可在 .streamlit/secrets.toml 配置凭证。该文件受 .gitignore 保护。

## 和 C 本地版同步

每轮从 C 获取版本号、变更清单、验收案例和可公开资料的出处。将核实的公开摘要加到 `demo_data/judge_sources.json`，从同一数据构造引用和导出；`report_docx.py` 复用 C 的 Markdown 到 Word 版式转换。优先同步验证过的交互、证据标识和报告结构。只在获得适合公网的已验收服务后另行接入正式测度。
