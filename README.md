# 因空制宜 Agent · 评委体验版

基于现有 GitHub 与 Streamlit Community Cloud。界面参照 C 的 V0.11.4 三栏工作台，网页版本为 0.11.4-web.1。资料检索使用本仓库精选公开摘要，回答由服务端华为云 MaaS 的 deepseek-v4.1-flash-1017 生成。该版本提供定性研判。

[评委体验入口](https://yinkong-agent-demo-wozfzuu5gmiya8njztqgsy.streamlit.app/)

## 使用

1. 在中栏输入问题，或点击首页示例。可在同一会话继续追问。
2. 右栏按会话汇总已讨论的问题、要点与引用，列出尚未完成的问题。可预览会话报告，下载 Markdown 或 Word。
3. 如需分析附件，在左栏上传小型文本 PDF。每份最多 3 MB、20 页。发送前勾选允许把所选文件的相关片段交给华为云，再发附件问题。

提供国家、黑龙江、福建、安徽精选政策与案例。资料库不等于全网搜索。用户提问由华为云处理，附件仅在选中授权后发送部分文本，问答与文件随会话保留，刷新、断线或重启可能丢失。扫描件不做 OCR。正式定量评价和专业审核在本地正式版执行。

## 部署

在 Streamlit Cloud 使用现有仓库 `kihhz/yinkong-agent-demo`、`main` 分支、入口 `streamlit_app.py`。依赖见 `requirements.txt`。

在 App settings → Secrets 保留现有 `MODEL_API_KEY`。新增时填写下列模板并替换占位文本。云端应用亦兼容 `MAAS_API_KEY`。

```toml
MODEL_API_KEY = "填入可用的华为云 MaaS API Key"
```

模型与地址由代码固定为华为云 MaaS 中国站。调用失败显示明确状态和可用的 HTTP 状态码。每条问题最多一次模型调用，20 秒网络超时，1,350 输出 token 上限。每会话每 10 分钟最多 10 次，间隔至少 2 秒。单进程每小时最多 60 次、滚动 24 小时最多 180 次，进程重启后计数重置。用量与扣费可在华为云控制台核对。

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
