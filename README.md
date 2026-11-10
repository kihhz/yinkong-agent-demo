# 因空制宜 Agent · 评委体验版

基于 GitHub 与 Streamlit Community Cloud 的聊天工作台。资料检索使用内置公开资料，模型由服务端华为云 MaaS 的 deepseek-v4.1-flash-1017 提供。

[评委体验入口](https://yinkong-agent-demo-wozfzuu5gmiya8njztqgsy.streamlit.app/)

## 使用

1. 在底部输入问题，或点击示例填入问题后再发送。对话区独立滚动，可在同一会话追问。
2. 右栏固定显示当前回答的结论、依据与简报。窄屏使用「查看对话成果」切换。对话区可展开整场会话总结。
3. 左栏按地区展示资料库与最近问题。可直接引用内置资料及其中的有来源数值，生成定性比较和建议。会话保存在当前浏览器会话中。
4. 点输入框左侧的「＋」添加附件，最多 3 个，每个不超过 3 MB。支持文本型 PDF、Word（DOCX）、Excel（XLSX）和 CSV。发送后，系统提取相关片段并交由华为云模型处理。上传一批新附件会替换当前附件，点击「清除附件」可从后续提问中移除它们。

附件回答可定位到 PDF 页码、Word 段落或表格行、Excel 工作表与行号。扫描 PDF 需要先做 OCR，旧版 DOC 和 XLS 可另存为 DOCX 和 XLSX。大文件仅提取部分内容，Excel 公式读取文件中已保存的结果。

提供全国政策及黑龙江、福建、安徽、云南、吉林、广东、四川的地方资料，也可查询 31 个省级地区的 2024 年人口和城镇化数据。询问“资料库覆盖哪些省份”会返回目录。交接包的公开案例材料通过摘要和原文链接接入，包括黑龙江与广州项目清单、云南首批需求清单及黑龙江统计公报。模型启用时，问题及匹配到的公开资料摘要由华为云处理。刷新、断线或重启可能丢失对话。

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
