# 因空制宜 Agent｜黑龙江演示

此版本提供肇东农林植保、呼玛短途运输、证据检索和省级历史状态。黑龙江统计和任务资料基准年为 2024。历史指标保留空值，当前没有在线正式评分。数据包只包含演示需要的公开资料摘要、官网链接及省级历史状态投影。

## 本地运行

推荐 Python 3.14。在项目目录执行：

```powershell
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

## Community Cloud

从 GitHub 仓库的 `main` 分支创建应用，入口填 `streamlit_app.py`，在 Advanced settings 选择 Python 3.14。部署后用无痕窗口打开生成的 `streamlit.app` 网址，依次运行 Q1、Q2 和 Q3。Q1 应显示植保条件和证据，Q2 的 N/D/S/G/T 均为未计算，Q3 应找到清单第 2 页的呼玛短途运输并显示计划年未证实。切换网络再检查一次评审链接。

## 模型联调

页面默认可直接使用三个离线演示问题。需要验证模型时，由账号持有人在应用的 **Settings → Secrets** 填写配置，再使用页面上的「模型 · 合成例联调」。联调码至少 16 个字符，与模型 API Key 分开。下面用 DeepSeek 作配置示例：

```toml
MODEL_BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-flash"
MODEL_API_KEY = ""
MODEL_DEMO_CODE = ""
```

本版也接受 OpenAI `https://api.openai.com/v1` 和 Anthropic `https://api.anthropic.com`，模型名和凭证按各自账号填写。Secrets 的实际值只留在云端设置或本地忽略的 `.streamlit/secrets.toml`。仅在主动联调时请求模型，页面显示「模型已返回」才算真实连通。单实例限每 30 秒发起一次，模型输出不写磁盘。若使用计费密钥，请先在供应商账号设置额度。

模型只收到页面展示的固定合成例。案例检索、来源和历史结果都由本地规则工具返回。模型调用超时或失败时，离线案例继续可用。
