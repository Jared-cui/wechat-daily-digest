# 微信公众号每日摘要流水线（AI 阅读 · 分类精炼 · 企业微信推送版）

每天自动采集公众号新文章 → **AI 逐篇阅读全文，生成「AI 标题」+「论文式摘要」+「分类」+「重要性」** → **合成「今日总览」** → 生成按分类分组的 HTML 日报 → **通过企业微信精简推送到你**（分类列表+一句话+链接，稳定不受 48 小时限制）。

> 产出的是 AI 对文章的**阅读与精炼**：每篇用 AI 重新拟标题（不沿用原公众号标题），给出论文式摘要，并自动分类（金融财经 / 科技互联网 / 产业商业 / 宏观政策 / 其他）和标注重要性（重要 / 一般）。推送精简为分类列表格式，一目了然。

## 工作流程

```
RSS 源（36氪 / 虎嗅APP / Wind万得 / …）
   ↓ 采集新文章
AI 逐篇阅读全文 → 生成「AI 标题」+「论文式摘要」+「分类」+「重要性」+「一句话摘要」
   ↓
AI 合成「今日总览」（整体主题 + 今日要点）
   ↓
生成分类分组 HTML 日报（📊金融 / 💻科技 / 🏭产业 / 📋宏观 / 📌其他）
   ↓
企业微信精简推送（分类列表 + ⭐重要标记 + 一句话 + 链接，自动分块不超限）
```

## 前置条件

- Python 3.10+（已用隔离环境装好 feedparser / requests / pyyaml）
- **免费的 RSS 源**（见第 1 步）——媒体站自带官方 RSS，或免费的 RSSHub，**无需任何付费服务**
- 一个**大模型 API Key**（OpenAI 兼容即可，见第 2 步）
- **企业微信**（推荐推送渠道，个人可免费注册）

## 配置步骤

### 1. 拿到 RSS 链接（全程免费，无需付费服务）

**三种免费获取方式，按需选用：**

| 类型 | 方式 | 示例 | 费用 |
|------|------|------|------|
| 媒体站官方 RSS | 直接填官网 RSS | 36氪 `https://36kr.com/feed`、虎嗅 `https://www.huxiu.com/rss/0.xml` | 免费 |
| 公共 RSSHub 镜像 | 官方 RSS 拉不到时兜底 | `https://rsshub.rssforever.com/huxiu/article` | 免费 |
| WeChat RSS 服务 | 纯公众号（无官网 RSS）用这个 | wechatrss.waytomaster.com（2个免费额度） | 免费 |

**当前已配置的三个源：**
- **36氪** → `https://36kr.com/feed`（官方免费，已验证）
- **虎嗅APP** → `https://www.huxiu.com/rss/0.xml`（官方免费，拉不到时换 RSSHub 镜像，config 注释里有）
- **Wind万得** → 需去 wechatrss.waytomaster.com 免费注册后搜索"Wind万得"获取 RSS 链接（2个免费额度），拿到后替换 config.yaml 里的 `TODO_REPLACE_WITH_WIND_RSS`

> Wind万得等纯公众号没有官方 RSS，WeChat RSS 是目前最简单的免费方案。未配置时该源会自动跳过，不影响其他源正常运行。
> ❌ 不建议用 itchat/wechaty 等个人微信机器人——违反微信 ToS、极易封号。

### 2. 填大模型
在 `config.yaml` 的 `llm:` 填接口地址、Key、模型名（支持 DeepSeek / 通义 / 本地 Ollama 等 OpenAI 兼容接口）。
不填或调用失败时会自动降级为「抽取式摘要」，保证每天仍有产出。

### 3. 配置推送（默认企业微信 · 推荐群机器人 webhook）
在 `config.yaml` 的 `wechat.type` 设为 `wecom`，并把 `wechat.wecom.mode` 设为 `webhook`（推荐路径，零开发）：
- **群机器人（推荐，最简单）**：在企业微信里建一个群 → 右上角「…」→ 添加群机器人 → 复制 webhook 地址填到 `wechat.wecom.webhook`。推送会出现在这个群里。
- **自建应用（备选，更正式）**：把 `mode` 改为 `app`，在企业管理后台「应用管理 → 自建」创建应用，拿到 `corpid` / `corpsecret` / `agentid`，接收人填 `touser`（或 `@all`）。
> 若改回公众号客服消息，把 `type` 设为 `official` 并填 `appid`/`appsecret`/`openid`（注意 48 小时互动限制）。

### 4.（可选）托管 HTML，推送图文消息
企业微信 markdown 已能承载总览+要点+链接；若想点开就看排版好的 HTML，把 `output/` 托管到公开地址（GitHub Pages / 腾讯云 COS），把前缀填进 `wechat.public_base_url`（官方客服消息模式用）。

## 运行

```bash
python pipeline/run_digest.py            # 正常模式
python pipeline/run_digest.py --no-push  # 只生成 HTML、不推送
python pipeline/run_digest.py --demo     # 演示模式（内置样例，不读配置、不推送）
python pipeline/test_real.py             # 端到端测试（用真实36氪文章演示，不推送）
python pipeline/test_push.py             # 一键测试推送（填好 webhook 后运行，验证链路通不通）
```

### 一键验证推送链路
填好 `wechat.wecom.webhook` 后，先跑 `python pipeline/test_push.py`：它会向你的企业微信群机器人发一条"推送测试消息"。**收到即代表配置成功**，之后正式运行 `run_digest.py` 就会每天把日报推进去。未填 webhook 时脚本会提示你去哪里拿。

## 关键产物说明

- 每篇文章**不显示原公众号标题**，改用 AI 生成的 `ai_title`。
- 摘要为论文式：背景/问题 → 核心观点或发现 → 结论或启示，连贯成段。
- **自动分类**：每篇归入 金融财经 / 科技互联网 / 产业商业 / 宏观政策 / 其他 之一。
- **重要性标注**：重大政策/突发/行业转折标为「⭐ 重要」，日常资讯为「一般」，重要文章在分类内排前面。
- 顶部「AI 今日总览」为跨文章的全局合成。
- **HTML 日报**按分类分组展示，每类有独立 section header。
- **企业微信推送**为精简分类列表：分类标题 + ⭐/• 标记 + AI 标题 + 一句话摘要 + 阅读链接（不再发整段摘要），自动分块不超 4096 字节限制。

## 定时自动化

### GitHub Actions（推荐，云端运行，电脑关机也照推）
- 仓库已配置 `.github/workflows/daily-digest.yml`，每天北京时间 **08:30** 自动运行。
- 密钥通过 GitHub Secrets 注入（`DEEPSEEK_API_KEY`、`WECOM_WEBHOOK`），不入库。
- HTML 日报自动上传为 Artifact，保留 30 天。
- 支持手动触发（Actions 页面 → Run workflow）。

### GitHub Pages（每日 HTML 日报在线查看）
- 每次 Actions 运行后，HTML 日报自动部署到 GitHub Pages（`gh-pages` 分支）。
- 访问地址：`https://jared-cui.github.io/wechat-daily-digest/`（首页 `index.html` 始终为最新日报）。
- 历史归档：`https://jared-cui.github.io/wechat-daily-digest/archive.html`
- **前提**：仓库需设为 Public（免费 GitHub Pages），或账户有 GitHub Pro（私有仓库 Pages）。
- **启用步骤**：GitHub 仓库 → Settings → Pages → Source 选 `Deploy from branch` → 选 `gh-pages` 分支 → Save。

### WorkBuddy 本地自动化（备选）
- WorkBuddy 定时任务（ID `automation-1784725980164`），每天 08:30 本机运行。
- 需电脑开机 + WorkBuddy 运行中。

## 多设备同步

| 内容 | 同步方式 | 说明 |
|------|----------|------|
| 项目代码 | GitHub 仓库 | 任何电脑 `git clone` 即可 |
| 项目上下文 | `PROJECT_CONTEXT.md`（入库） | 任何 WorkBuddy 实例可读 |
| WorkBuddy 对话记录 | 云端自动同步 | 任何登录设备可查看历史对话 |
| 每日 HTML 日报 | GitHub Pages | 手机浏览器/WorkBuddy小程序均可打开 |
| Actions 运行记录 | GitHub Actions 页面 | 任何浏览器可查看 |
