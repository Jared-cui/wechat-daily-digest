# 项目上下文 — 公众号每日摘要流水线

> 本文件供任何 WorkBuddy 实例快速理解项目全貌。更新于 2026-08-03。

## 定位

微信公众号「每日文章 AI 阅读摘要」自动化：采集 RSS → DeepSeek AI 分类+精炼 → 生成 HTML 日报 → 企业微信群机器人推送。

## 架构决策

| 维度 | 决策 | 理由 |
|------|------|------|
| 文章来源 | 免费 RSS（媒体站官方 RSS + wechatrss.waytomaster.com 免费额度） | 不依赖付费服务 |
| AI 提炼 | DeepSeek（api.deepseek.com/v1, model=deepseek-chat） | 逐篇生成 AI标题+论文式摘要+分类+重要性+一句话 |
| 推送方式 | 企业微信群机器人 webhook | 稳定，不受 48h 互动限制 |
| 运行平台 | **GitHub Actions 为主**（云端，每天 08:30 BJ） | 电脑关机也能跑 |
| 本地备选 | **WorkBuddy 自动化**（ID automation-1785765420226，每天 09:00 BJ） | GitHub 故障时兜底；需电脑开机 |
| 仓库 | Jared-cui/wechat-daily-digest（私有） | 密钥通过 GitHub Secrets 注入 |

## 关键约束

1. **企业微信 markdown 单条上限 4096 字节** → 必须分块推送（已实现 `_blocks_for_wecom`）。
2. **DeepSeek 402** = 余额不足（非代码问题），需充值。
3. **webhook 地址**必须是 `qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...` 格式。
4. **虎嗅 RSS**：原 `www.huxiu.com/rss/0.xml` 超时，已替换为 `rss.huxiu.com/`（官方专用域名，141篇，已验证可用）。备用：`rsshub.umzzz.com/huxiu/article`（RSSHub 公共镜像，20篇）。

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
  daily-digest.yml     # GitHub Actions 定时任务
PROJECT_CONTEXT.md     # 本文件 — 项目上下文（入库）
README.md              # 完整说明文档
requirements.txt       # feedparser / requests / pyyaml
```

## 当前 RSS 源

| 公众号 | RSS 链接 | 状态 |
|--------|----------|------|
| 36氪 | `https://36kr.com/feed` | 免费，已验证 |
| 虎嗅APP | `https://rss.huxiu.com/` | 官方专用域名，141篇，已验证 |
| 虎嗅APP（备用） | `https://rsshub.umzzz.com/huxiu/article` | RSSHub 公共镜像，20篇 |
| Wind万得 | `TODO_REPLACE_WITH_WIND_RSS` | 待用户从 wechatrss.waytomaster.com 获取 |

## AI 分类体系

- 金融财经 📊 / 科技互联网 💻 / 产业商业 🏭 / 宏观政策 📋 / 其他 📌
- 重要性：⭐重要（重大政策/突发/行业转折）/ 一般
- 推送格式：分类列表 + ⭐标记 + AI标题 + 一句话 + 链接

## GitHub Secrets

| Secret 名 | 用途 |
|-----------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 |
| `WECOM_WEBHOOK` | 企业微信群机器人 webhook 地址 |

## GitHub Pages（每日 HTML 日报在线查看）

- 部署目标：`gh-pages` 分支
- 访问地址：`https://jared-cui.github.io/wechat-daily-digest/`
- `index.html` 始终为最新日报，历史日报以 `digest_YYYY-MM-DD.html` 归档
- **前提**：仓库需设为 Public（免费 GitHub Pages），或账户有 GitHub Pro（私有仓库 Pages）

## 本地运行

```bash
python pipeline/run_digest.py            # 正常模式
python pipeline/run_digest.py --no-push  # 只生成 HTML、不推送
python pipeline/run_digest.py --demo     # 演示模式（内置样例）
python pipeline/test_push.py             # 一键测试推送链路
```

依赖环境：`feedparser` / `requests` / `pyyaml`
