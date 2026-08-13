# 项目上下文 — 每日资讯 AI 精读流水线

> 本文件供任何 WorkBuddy 实例快速理解项目全貌。更新于 2026-08-10。

## 定位

每日定时采集 4 家媒体（虎嗅APP/36氪/晚点LatePost/钛媒体）**前一日 08:40 ~ 当日 08:40（北京时间）** 的推送 → DeepSeek AI 逐篇精读（AI标题+摘要+关键词+读后感+含金量评分）→ 分板块按含金量倒序生成 HTML 日报（≤30 篇）→ **每天 08:45 企业微信群机器人推送**。

## 架构决策

| 维度 | 决策 | 理由 |
|------|------|------|
| 文章来源 | 免费 RSS：虎嗅 `rss.huxiu.com/`、36氪 `36kr.com/feed`、晚点 `rsshub.app/latepost`、钛媒体 `tmtpost.com/rss` | 全部官方/公共免费源，已验证 |
| 采集窗口 | 固定窗口 [昨日 08:40, 今日 08:40]（北京时间，`settings.window_end`） | 覆盖"前一日 8:40-当日 8:40 的推送" |
| AI 精读 | DeepSeek（api.deepseek.com/v1, model=deepseek-chat） | 超 30 篇先 AI 预筛选；逐篇生成 AI标题/摘要(≤200字)/关键词/读后感(≤200字)/分类/重要性/含金量分(0-100) |
| 排序规则 | 分板块（宏观政策/经济金融/信息科技/商业行业/其他），**板块按固定顺序展示，板块内按含金量分降序** | 2026-08-13 调整为固定板块顺序 |
| 推送方式 | **SMTP 邮箱**（163: smtp.163.com:465 SSL，HTML 日报作为正文整封发送） | 稳定不受 48h 限制，无大小限制；2026-08-12 由企微切换 |
| 运行平台 | **GitHub Actions 为主**（云端，每天 08:45 BJ） | 电脑关机也能跑 |
| 本地备选 | **WorkBuddy 自动化**（ID automation-1785765420226，每天 08:45 BJ） | GitHub 故障时兜底；需电脑开机 |
| 仓库 | Jared-cui/wechat-daily-digest（**已改 Public**，2026-08-12） | 密钥通过 GitHub Secrets 注入，仓库内无任何凭据 |

## 关键约束

1. **邮箱推送**：`push_email()` 用 SMTP 发送 HTML 日报正文；凭据在本地 `config.yaml`（gitignored）+ GitHub Secrets（EMAIL_* 环境变量），仓库内无凭据。
2. **DeepSeek 402** = 余额不足（非代码问题），需充值。
3. **SMTP 授权码**：163/QQ 邮箱开启 SMTP 服务后生成（不是登录密码），163 用 smtp.163.com:465 SSL。
4. **采集窗口是固定窗口**，不是滚动窗口：`compute_window()` 计算 [昨日 08:40, 今日 08:40]（北京时间），所有源的时间统一转北京时间比较；晚点 RSS 为 UTC 时间，钛媒体为 +0800，均已处理。
5. **AI 预筛选**：采集文章数超 max_articles(30) 时，先 AI 预筛选选出最具新闻价值 N 篇，再逐篇深度精读，节省 API 成本。
6. **每篇文章字段**：ai_title（AI提炼标题，不用原标题）/ refined（摘要≤200字）/ keywords（2-4个关键词）/ takeaway（AI读后感≤200字）/ score（含金量0-100）/ importance（重要/一般）。HTML 按板块+含金量倒序渲染。
7. **板块顺序**：`group_by_category()` 返回 (grouped, cat_order)，cat_order 按板块内最高含金量降序，空板块排最后。
8. **网络抖动处理**：`fetch_feed()` 每个源重试 3 次（间隔 2s）；`_llm_chat()` 所有 LLM 调用（预筛选/逐篇总结/总览）统一重试 3 次（指数退避，timeout 90s），402 余额不足不重试。单个源失败自动跳过，不影响其他源。

## 文件结构

```
pipeline/
  run_digest.py        # 主流水线脚本
  config.yaml          # 本地配置（含密钥，gitignored）
  config.example.yaml  # 配置模板（入库，CI 从环境变量读）
  test_push.py         # 一键测试推送
  test_real.py         # 端到端测试
output/                # HTML 日报产出（gitignored）
  digest_YYYY-MM-DD.html
state.json             # 去重状态（gitignored，CI 用 cache 持久化）
.github/workflows/
  daily-digest.yml     # GitHub Actions 定时任务（每天 08:45 BJ）
PROJECT_CONTEXT.md     # 本文件 — 项目上下文（入库）
README.md              # 完整说明文档
requirements.txt       # feedparser / requests / pyyaml
```

## 当前 RSS 源

| 媒体 | RSS 链接 | 状态 |
|--------|----------|------|
| 虎嗅APP | `https://rss.huxiu.com/` | 官方专用域名，141篇，已验证 |
| 虎嗅APP（备用） | `https://rsshub.umzzz.com/huxiu/article` | RSSHub 公共镜像，20篇 |
| 36氪 | `https://www.36kr.com/feed` | ⚠️ 必须带 www（2026-08-11 修复：裸域 `36kr.com/feed` 被反爬 JS 挑战拦截，返回空） |
| 晚点LatePost | `https://rsshub.app/latepost` | RSSHub 路由，UTC 时间，已验证；本机网络可能超时，GitHub Actions 海外正常 |
| 钛媒体 | `https://www.tmtpost.com/rss` | 官方免费，已验证；仅保留最近 16 条 |

## AI 分类体系（2026-08-13 更新）

- 板块（固定顺序）：宏观政策 📋 / 经济金融 📊 / 信息科技 💻 / 商业行业 🏭 / 其他 📌
- 重要性：⭐重磅（重大政策/突发/行业转折）/ 一般
- 含金量分：0-100 整数，综合重磅程度/行业影响/信息增量评定，板块内按此降序
- 推送格式：板块列表 + ⭐/含金量分 + AI标题 + 一句话 + 链接

## GitHub Secrets

| Secret 名 | 用途 |
|-----------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `EMAIL_SMTP_HOST` / `EMAIL_SMTP_PORT` | SMTP 服务器与端口（smtp.163.com / 465） |
| `EMAIL_SENDER` / `EMAIL_PASSWORD` | 发件邮箱与 SMTP 授权码 |
| `EMAIL_RECIPIENT` | 收件邮箱 |

## GitHub Pages（每日 HTML 日报在线查看）

- 部署目标：`gh-pages` 分支
- 访问地址：`https://jared-cui.github.io/wechat-daily-digest/`
- `index.html` 始终为最新日报，历史日报以 `digest_YYYY-MM-DD.html` 归档
- ✅ **已启用（2026-08-12）**：仓库已改 Public，Pages 已选 gh-pages 分支，全部页面 200 可访问

## 本地运行

```bash
python pipeline/run_digest.py            # 正常模式（08:45 定时任务同款命令）
python pipeline/run_digest.py --no-push  # 只生成 HTML、不推送
python pipeline/run_digest.py --demo     # 演示模式（内置样例）
python pipeline/test_push.py             # 一键测试推送链路
```

依赖环境：`C:\Users\CUI\.workbuddy\binaries\python\envs\default`（feedparser / requests / pyyaml）
