# 因空制宜 Agent｜黑龙江演示

此版本提供肇东农林植保、呼玛短途运输、证据检索和省级冻结状态。黑龙江统计和任务资料基准年为 2024。Q2 读取 C v2 随包的 B 本地运行状态摘要，保留各指标空值和原因。当前网页只读，不运行正式评分。

左栏可新建和切换对话、查看资料库。中栏可选择三个示例或直接提问，并显示实际处理步骤。右栏保留当前对话最新的结论、证据和 Markdown 下载。对话记录仅保存在当前浏览器会话中。

## 本地运行

推荐 Python 3.14。在项目目录执行：

```powershell
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

## Community Cloud

从 GitHub 仓库的 `main` 分支创建应用，入口填 `streamlit_app.py`，在 Advanced settings 选择 Python 3.14。部署后用无痕窗口打开生成的 `streamlit.app` 网址，依次运行 Q1、Q2 和 Q3。Q1 应显示植保条件和证据，Q2 的 N/D/S/G/T 均为未计算，Q3 应找到清单第 2 页的呼玛短途运输并显示计划年未证实。切换网络再检查一次评审链接。

## 模型联调

评委直接使用中间聊天框，无需联调码。勾选同意后，应用只发送本条输入和当前案例标识，请模型选择白名单中的只读工具；资料与工具结果留在应用内。未勾选时走本地规则。公开聊天限每个浏览器会话 12 次模型请求、每个服务实例每小时 60 次，超限后可继续用本地规则。

页面默认可直接使用三个只读演示问题。需要验证模型时，由账号持有人在应用的 **Settings → Secrets** 填写配置，再开启左栏「模型联调」并选一个合成问题。联调码至少 16 个字符，与模型 API Key 分开。下面用 DeepSeek 作配置示例：

```toml
MODEL_BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-flash"
MODEL_API_KEY = ""
MODEL_DEMO_CODE = ""
```

如果使用华为云 MaaS 上已开通的 DeepSeek-V4.1-Flash-1017，改用以下地址和模型，并填该平台生成的 MaaS API Key。

```toml
MODEL_BASE_URL = "https://api.modelarts-maas.com/v2"
MODEL_NAME = "deepseek-v4.1-flash-1017"
```

本版也接受 OpenAI `https://api.openai.com/v1` 和 Anthropic `https://api.anthropic.com`，模型名和凭证按各自账号填写。Secrets 的实际值只留在云端设置或本地忽略的 `.streamlit/secrets.toml`。每轮合成联调最多两次模型请求，分别理解问题和解释工具结果。页面显示「模型已返回」并列出已执行工具才算闭环成功。联调间隔至少 30 秒，模型输出不写磁盘。用量取自接口回传，扣费以供应商账单为准。

模型只收到固定合成问题及同一合成夹具的只读工具返回。真实对话文本、案例检索、来源及冻结状态留在应用进程内。模型超时、返回非法计划或解释校验失败时，真实案例仍可使用。
