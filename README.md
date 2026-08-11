# 每日资讯 AI 精读流水线（4 源 · 含金量排序 · HTML + 企业微信推送版）

每天自动采集 **虎嗅APP / 36氪 / 晚点LatePost / 钛媒体** 在**前一日 08:40 ~ 当日 08:40（北京时间）**的推送 → **AI 逐篇精读全文**，生成 **AI 提炼标题** + **内容摘要（≤200字）** + **关键词** + **AI 读后感（≤200字）** + **分类** + **含金量评分（0-100）** → 合成「今日总览」→ 生成**分板块、按含金量倒序**的 HTML 日报（**≤30 篇**）→ 通过企业微信在**每天 08:45** 推送给你的群。

> 产出的是 AI 对资讯的**精读与评点**：每篇不沿用原标题，由 AI 重新拟题；给出 200 字内的内容摘要与关键词；额外附一段「AI 读后感」——提炼方法论、行业分析框架或新闻联动影响；并按含金量（重磅程度/行业影响/信息增量）打分排序，先读最值得读的。

## 工作流程

```
RSS 源（虎嗅APP / 36氪 / 晚点LatePost / 钛媒体）
   ↓ 固定窗口采集：前一日 08:40 ~ 当日 08:40（北京时间）
AI 预筛选（>30 篇时选最重要 30 篇）→ 逐篇精读：AI标题 + 摘要(≤200字) + 关键词 + 读后感(≤200字) + 分类 + 含金量分(0-100)
   ↓
AI 合成「今日总览」（整体主题 + 今日要点）
   ↓
生成 HTML 日报：分板块（📊金融 / 💻信息 / 🏭商业 / 📋宏观 / 📌其他），板块内与板块间均按含金量倒序
   ↓
企业微信推送（板块列表 + ⭐/含金量分 + AI标题 + 一句话 + 链接，自动分块不超限）
```

## 前置条件

- Python 3.10+（已用隔离环境装好 feedparser / requests / pyyaml）
- **免费的 RSS 源**（全部官方/公共免费源，无需付费服务）
- 一个**大模型 API Key**（OpenAI 兼容即可，见第 2 步）
- **企业微信**（推荐推送渠道，个人可免费注册）

## 配置步骤

### 1. 拿到 RSS 链接（全程免费，无需付费服务）

**当前已配置的四个源：**

| 媒体 | RSS 链接 | 说明 |
|------|----------|------|
| **虎嗅APP** | `https://rss.huxiu.com/` | 官方专用域名，内容最全；拉不到时换 RSSHub 镜像 `rsshub.umzzz.com/huxiu/article`（config 注释里） |
| **36氪** | `https://www.36kr.com/feed` | 官方免费 RSS（⚠️ 必须带 www：裸域 `36kr.com/feed` 已被反爬 JS 挑战拦截，返回空） |
| **晚点LatePost** | `https://rsshub.app/latepost` | RSSHub 官方路由（UTC 时间，脚本自动转北京时间；本机网络可能超时，GitHub Actions 海外运行正常） |
| **钛媒体** | `https://www.tmtpost.com/rss` | 官方免费 RSS（只保留最近 16 条，早上运行时窗口内覆盖有限） |

> 采集窗口固定为**前一日 08:40 ~ 当日 08:40（北京时间）**（`settings.window_end: "08:40"`），脚本对所有源的时间统一转北京时间后过滤。某源网络抖动会自动重试 3 次，仍失败则跳过该源、不影响其他源。

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

- 每篇文章**不显示原媒体标题**，改用 AI 生成的 `ai_title`。
- **内容摘要**（`refined`）：≤200 字，背景/问题 → 核心观点/发现 → 结论/启示，连贯成段。
- **关键词**（`keywords`）：每篇 2-4 个。
- **AI 读后感**（`takeaway`）：≤200 字，提炼方法论、行业分析框架、新闻联动影响等，附在每篇卡片底部。
- **自动分类**：每篇归入 金融财经 / 信息技术 / 商业企业 / 宏观政策 / 其他 之一。
- **含金量评分**（`score`，0-100）：综合重磅程度/行业影响/信息增量；**板块内按分数降序，板块间按最高分降序**，整体阅读顺序即含金量递减。
- **重要性标注**：重大政策/突发/行业转折标为「★ 重磅」。
- 顶部「AI 今日总览」为跨文章的全局合成。
- **HTML 日报**分板块展示，每篇含：AI标题（可点击原文）+ 来源/发布时间 + 摘要 + 关键词 + AI读后感 + 阅读原文按钮。
- **企业微信推送**为精简板块列表：板块标题 + ⭐/含金量分 + AI标题 + 一句话摘要 + 阅读链接，自动分块不超 4096 字节限制。

## 定时自动化

### GitHub Actions（推荐，云端运行，电脑关机也照推）
- 仓库已配置 `.github/workflows/daily-digest.yml`，每天北京时间 **08:45** 自动运行。
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
- WorkBuddy 定时任务（ID `automation-1785765420226`），每天 08:45 本机运行。
- 需电脑开机 + WorkBuddy 运行中。

## 多设备同步

| 内容 | 同步方式 | 说明 |
|------|----------|------|
| 项目代码 | GitHub 仓库 | 任何电脑 `git clone` 即可 |
| 项目上下文 | `PROJECT_CONTEXT.md`（入库） | 任何 WorkBuddy 实例可读 |
| WorkBuddy 对话记录 | 云端自动同步 | 任何登录设备可查看历史对话 |
| 每日 HTML 日报 | GitHub Pages | 手机浏览器/WorkBuddy小程序均可打开 |
| Actions 运行记录 | GitHub Actions 页面 | 任何浏览器可查看 |
