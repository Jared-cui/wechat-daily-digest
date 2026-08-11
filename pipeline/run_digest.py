#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号每日摘要流水线（AI 阅读 · 分类精炼 · 企业微信推送版）

流程：
  1. 采集 RSS 源的新文章
  2. AI 逐篇阅读全文：生成 AI 标题 + 论文式摘要 + 一句话摘要 + 分类 + 重要性
  3. AI 合成「今日总览」（整体主题 + 今日要点）
  4. 生成按分类分组的 HTML 日报
  5. 推送：企业微信（默认，稳定）或公众号客服消息（需48h互动）

运行：
  python run_digest.py            # 正常模式
  python run_digest.py --demo     # 演示模式（内置样例，不推送）
  python run_digest.py --no-push  # 生成 HTML 但不推送
"""
import argparse, json, re, os, time, datetime
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None
try:
    import feedparser
except ImportError:
    feedparser = None
try:
    import requests
except ImportError:
    requests = None

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
CONFIG_PATH = ROOT / "config.yaml"
STATE_PATH = ROOT / "state.json"
_h = __import__("html")
esc = lambda s: _h.escape(str(s or ""))

# ---------- 分类体系 ----------
CATEGORIES = ["金融财经", "信息技术", "商业企业", "宏观政策", "其他"]
CAT_EMOJI = {
    "金融财经": "📊",
    "信息技术": "💻",
    "商业企业": "🏭",
    "宏观政策": "📋",
    "其他": "📌",
}
CAT_ORDER = {c: i for i, c in enumerate(CATEGORIES)}


# ---------- 工具 ----------
def log(msg):
    print(f"[{datetime.datetime.now():%H:%M:%S}] {msg}", flush=True)


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<script.*?</script>", "", s, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", "", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = _h.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def plain_text(s, limit=4000):
    return strip_html(s)[:limit]


def is_configured(cfg):
    if not cfg:
        return False
    feeds = cfg.get("feeds") or []
    if not feeds:
        return False
    for f in feeds:
        u = (f.get("url") or "")
        if (not u) or ("xxxx" in u) or ("yyyy" in u):
            return False
    return True


def normalize_category(cat):
    """把 AI 返回的分类归入标准分类。"""
    if not cat:
        return "其他"
    cat = cat.strip()
    for c in CATEGORIES:
        if c in cat or cat in c:
            return c
    # 常见同义词
    syn = {"金融": "金融财经", "财经": "金融财经", "股市": "金融财经", "证券": "金融财经",
           "科技": "信息技术", "互联网": "信息技术", "AI": "信息技术", "技术": "信息技术", "IT": "信息技术",
           "产业": "商业企业", "商业": "商业企业", "企业": "商业企业", "消费": "商业企业",
           "宏观": "宏观政策", "政策": "宏观政策", "政府": "宏观政策"}
    for k, v in syn.items():
        if k in cat:
            return v
    return "其他"


# ---------- 配置 ----------
def load_config():
    if not CONFIG_PATH.exists():
        return None
    if yaml is None:
        raise SystemExit("缺少 pyyaml，请先 pip install pyyaml")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------- 文章采集 ----------
def parse_feed_date(entry):
    """从 feedparser entry 解析发布时间，返回 datetime 或 None。"""
    for field in ("published_parsed", "updated_parsed"):
        tp = entry.get(field)
        if tp:
            try:
                import time as _time
                return datetime.datetime(*tp[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                pass
    # 尝试从 published 字符串解析
    for field in ("published", "updated"):
        s = entry.get(field, "")
        if s:
            try:
                import email.utils as _eu
                dt = _eu.parsedate_to_datetime(s)
                if dt:
                    return dt
            except Exception:
                pass
    return None


BJ_TZ = datetime.timezone(datetime.timedelta(hours=8))  # 北京时间


def parse_feed_date_bj(entry):
    """解析发布时间并转换为北京时间（aware datetime），失败返回 None。"""
    dt = parse_feed_date(entry)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(BJ_TZ)


def compute_window(cutoff_time="08:40", lookback_hours=24):
    """计算固定采集窗口 [start, end)（北京时间）。

    默认窗口 = [昨日 08:40, 今日 08:40]，即「前一日 8:40 至当日 8:40 的推送」。
    """
    now = datetime.datetime.now(BJ_TZ)
    try:
        hh, mm = (int(x) for x in str(cutoff_time).split(":"))
    except Exception:
        hh, mm = 8, 40
    end = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < end:
        end -= datetime.timedelta(days=1)  # 当前还没到当日截止点，窗口整体顺延一天
    start = end - datetime.timedelta(hours=int(lookback_hours or 24))
    return start, end


def in_window(entry, start_bj, end_bj):
    """判断文章发布时间是否落在 [start_bj, end_bj) 内（北京时间）。无日期信息时默认保留。"""
    dt = parse_feed_date_bj(entry)
    if dt is None:
        return True  # 无法解析日期，保留
    return start_bj <= dt < end_bj


def fetch_feed(name, url, retries=3):
    """拉取 RSS 内容，网络抖动时自动重试（默认最多 3 次）。"""
    if requests is None:
        raise SystemExit("缺少 requests")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    last_ex = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=20, headers=headers)
            if resp.status_code == 200:
                resp.encoding = resp.apparent_encoding or "utf-8"
                return resp.text
            last_ex = RuntimeError(f"HTTP {resp.status_code}")
            log(f"  「{name}」第 {attempt + 1} 次请求返回 HTTP {resp.status_code}，重试...")
        except Exception as ex:
            last_ex = ex
            log(f"  「{name}」第 {attempt + 1} 次请求失败（{type(ex).__name__}），重试...")
        if attempt < retries - 1:
            time.sleep(2)
    raise last_ex


def parse_feed(name, raw):
    if feedparser is None:
        raise SystemExit("缺少 feedparser")
    d = feedparser.parse(raw)
    items = []
    for e in d.entries:
        content = (e.get("content") and e["content"][0].get("value")) or e.get("description") or ""
        items.append({
            "title": e.get("title", "").strip(),
            "link": e.get("link", "").strip(),
            "author": (e.get("author") or name).strip(),
            "published": e.get("published", ""),
            "content": content,
            "guid": e.get("id") or e.get("guid") or e.get("link", ""),
        })
    return items


# ---------- AI 工具：带重试的 LLM 调用 ----------
def _llm_chat(llm_cfg, messages, temperature=0.3, retries=3, timeout=90):
    """调用 OpenAI 兼容接口，带超时重试。返回回复的文本内容，全部失败则抛异常。

    重试覆盖网络抖动/超时；402（余额不足）不重试。
    """
    if not (llm_cfg and llm_cfg.get("enabled") and requests):
        raise RuntimeError("LLM 未启用")
    url = f"{llm_cfg['base_url'].rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {llm_cfg['api_key']}", "Content-Type": "application/json"}
    payload = {"model": llm_cfg.get("model", "deepseek-chat"),
               "messages": messages,
               "response_format": {"type": "json_object"},
               "temperature": temperature}
    last_ex = None
    for attempt in range(retries):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 402:
                raise RuntimeError("DeepSeek 余额不足（402），请充值")
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as ex:
            last_ex = ex
            log(f"  LLM 调用失败（{attempt + 1}/{retries}）：{type(ex).__name__}，重试...")
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise last_ex


# ---------- AI 预筛选：从大量文章中选出最具新闻价值的 N 篇 ----------
def prescreen_articles(articles, llm_cfg, max_count=20):
    """AI 预筛选：从大量候选文章中选出最具新闻价值的 N 篇。
    返回 (selected_articles, reasoning_string)。"""
    if len(articles) <= max_count:
        return articles, "文章数未超上限，全部保留"

    if not (llm_cfg and llm_cfg.get("enabled") and requests):
        log(f"  LLM 不可用，取前 {max_count} 篇")
        return articles[:max_count], "LLM不可用，取前N篇"

    article_list = "\n\n".join(
        f"[{i}] {a['author']} | {a['title']}\n    {plain_text(a['content'], 120)}"
        for i, a in enumerate(articles)
    )

    sys_p = (
        f"你是资深财经科技主编。以下有 {len(articles)} 篇候选文章，请从中选出最重要的 {max_count} 篇。\n"
        "选择标准（按优先级）：\n"
        "1. 重大政策/市场变动（降息/降准/监管/地缘/突发）→ 最优先\n"
        "2. 行业趋势性事件或突破性技术进展 → 次优先\n"
        "3. 独家深度分析或头部公司重大动态 → 再次\n"
        "4. 一般资讯/软文/广告/低信息量 → 不选\n\n"
        "输出 JSON：\n"
        '{"selected": [0, 3, 5, ...], "reasoning": "筛选逻辑简述（20字内）"}\n'
        "只输出 JSON，不要多余文字。"
    )

    user_p = f"候选文章：\n\n{article_list}"

    try:
        content = _llm_chat(llm_cfg,
                            [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
                            temperature=0.2)
        obj = json.loads(content)
        indices = obj.get("selected", [])
        reasoning = obj.get("reasoning", "")
        selected = [articles[i] for i in indices if 0 <= i < len(articles)]
        if len(selected) > max_count:
            selected = selected[:max_count]
        log(f"  AI 预筛选：{len(articles)} → {len(selected)} 篇（{reasoning}）")
        return selected, reasoning
    except Exception as ex:
        log(f"  AI 预筛选失败，取前 {max_count} 篇：{ex}")
        return articles[:max_count], ""


# ---------- AI 阅读：AI 标题 + 论文式摘要 + 分类 ----------
def summarize(article, llm_cfg):
    if not (llm_cfg and llm_cfg.get("enabled") and requests):
        return fallback_summary(article)
    sys_p = (
        "你是一个严谨的研究助理。请阅读这篇公众号文章，输出 JSON：\n"
        "{\n"
        '  "ai_title": "由你凝练生成的标题（8-20字，概括文章主旨，不要照抄原标题）",\n'
        '  "refined": "内容摘要（180字以内，先点明背景/问题，再给出核心观点或发现，最后给出结论或启示，连贯成一段）",\n'
        '  "keywords": ["2到4个关键词"],\n'
        '  "takeaway": "AI读后感（180字以内）：提炼方法论、行业分析框架、新闻可能引发的联动影响等，要有洞察、不空泛",\n'
        '  "one_liner": "一句话核心摘要（15-30字，用于推送列表，精炼抓人）",\n'
        '  "category": "分类，必须是以下之一：金融财经、信息技术、商业企业、宏观政策、其他",\n'
        '  "importance": "重要 或 一般（重大政策/突发/行业转折=重要，日常资讯/分析=一般）",\n'
        '  "score": "内容含金量评分（整数0-100，综合重磅程度/行业影响/信息增量评定，越大越值得读）"\n'
        "}\n只输出 JSON，不要多余文字。"
    )
    user_p = f"原标题：{article['title']}\n来源：{article['author']}\n正文：\n{plain_text(article['content'], 3500)}"
    try:
        content = _llm_chat(llm_cfg,
                            [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
                            temperature=0.3)
        obj = json.loads(content)
        try:
            score = int(float(obj.get("score", 0) or 0))
        except (TypeError, ValueError):
            score = 0
        return {
            "ai_title": obj.get("ai_title", ""),
            "refined": obj.get("refined", ""),
            "keywords": obj.get("keywords", []) or [],
            "takeaway": obj.get("takeaway", ""),
            "one_liner": obj.get("one_liner", ""),
            "category": normalize_category(obj.get("category", "其他")),
            "importance": "重要" if "重" in (obj.get("importance") or "") else "一般",
            "score": max(0, min(100, score)),
        }
    except Exception as ex:
        log(f"  LLM 逐篇总结失败，降级：{ex}")
        return fallback_summary(article)


def fallback_summary(article):
    full = plain_text(article["content"], 9999)
    short = plain_text(article["content"], 200)
    refined = short + ("..." if len(full) > 200 else "")
    ai_title = "资讯速读：" + short[:16]
    return {
        "ai_title": ai_title,
        "refined": refined,
        "keywords": [],
        "takeaway": "",
        "one_liner": short[:25] + ("..." if len(short) > 25 else ""),
        "category": "其他",
        "importance": "一般",
        "score": 0,
    }


# ---------- AI 合成：今日总览 ----------
def synthesize(articles, llm_cfg):
    if not (llm_cfg and llm_cfg.get("enabled") and requests):
        return fallback_synth(articles)
    briefs = "\n\n".join(f"[{a.get('ai_title') or a['title']}]({a['author']})\n分类:{a.get('category','其他')} | {a.get('one_liner','')}"
                         for a in articles)
    sys_p = ("你是一个资深编辑，负责把多篇文章浓缩成一份「今日总览」。只输出 JSON："
             "{\"overview\": \"一段150-220字的总览，归纳今天阅读的整体主题与最值得关注的1-2个结论\", "
             "\"highlights\": [\"2到4条要点，每条一句话并注明来源\"]}。"
             "只输出 JSON，不要多余文字。")
    user_p = f"今天阅读了以下 {len(articles)} 篇文章：\n\n{briefs}"
    try:
        content = _llm_chat(llm_cfg,
                            [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
                            temperature=0.3)
        return json.loads(content)
    except Exception as ex:
        log(f"  LLM 全局总览失败，降级：{ex}")
        return fallback_synth(articles)


def fallback_synth(articles):
    alltags = []
    for a in articles:
        alltags += a.get("keywords", [])
    overview = (f"今日共阅读 {len(articles)} 篇文章，涉及：{', '.join(alltags[:8]) or '多个主题'}。"
                "各篇精炼总结见下方。")
    highlights = [(f"{(a.get('refined') or a.get('summary',''))[:42]}...({a['author']})") for a in articles[:4]]
    return {"overview": overview, "highlights": highlights}


# ---------- 组装 & 渲染 ----------
def _score(a):
    try:
        return int(a.get("score", 0) or 0)
    except (TypeError, ValueError):
        return 0


def group_by_category(articles):
    """按分类分组，组内按含金量 score 降序；返回 (grouped, cat_order)。

    cat_order 按「板块内最高含金量」降序排列，空板块排最后，
    使整体阅读顺序即为含金量递减。
    """
    grouped = {}
    for cat in CATEGORIES:
        grouped[cat] = []
    for a in articles:
        cat = a.get("category", "其他")
        if cat not in grouped:
            cat = "其他"
        grouped[cat].append(a)
    for cat in grouped:
        grouped[cat].sort(key=_score, reverse=True)
    cat_order = sorted(CATEGORIES, key=lambda c: max((_score(a) for a in grouped[c]), default=-1), reverse=True)
    cat_order = [c for c in cat_order if grouped[c]] + [c for c in CATEGORIES if not grouped[c]]
    return grouped, cat_order


def build_digest(articles, synthesis):
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    sources = ", ".join(sorted({a["author"] for a in articles}))
    headline = f"今日 AI 阅读 {len(articles)} 篇 - 来源：{sources}"
    grouped, cat_order = group_by_category(articles)
    # 统计各分类篇数
    cat_stats = {cat: len(grouped[cat]) for cat in CATEGORIES if grouped[cat]}
    return {
        "date": date,
        "headline": headline,
        "articles": articles,
        "grouped": grouped,
        "cat_order": cat_order,
        "cat_stats": cat_stats,
        "synthesis": synthesis,
    }


def _fmt_pub(a):
    """把发布时间格式化为 'MM-DD HH:MM'（北京时间），无则返回空串。"""
    dt = a.get("pub_dt")
    if not dt:
        return ""
    try:
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return ""


def render_html(digest):
    syn = digest.get("synthesis", {})
    overview = syn.get("overview", "")
    highlights = syn.get("highlights", [])
    hl_html = "".join(f"<li>{esc(h)}</li>" for h in highlights)
    grouped = digest.get("grouped", {})
    cat_order = digest.get("cat_order", CATEGORIES)

    # 统计重要/一般文章数
    imp_count = sum(1 for a in digest["articles"] if a.get("importance") == "重要")
    gen_count = len(digest["articles"]) - imp_count

    # 按板块生成卡片（组内已按含金量降序）
    sections = []
    for cat in cat_order:
        arts = grouped.get(cat, [])
        if not arts:
            continue
        emoji = CAT_EMOJI.get(cat, "")
        avg_score = sum(_score(a) for a in arts) / len(arts)
        cards = []
        for a in arts:
            title = a.get("ai_title") or a.get("title")
            link = esc(a["link"])
            pub = esc(_fmt_pub(a))
            score = _score(a)
            meta_parts = [f"来源：{esc(a['author'])}"]
            if pub:
                meta_parts.append(f"发布于 {pub}")
            if a.get("importance") == "重要":
                meta_parts.append('<span class="star">★ 重磅</span>')
            meta_parts.append(f'<span class="score">含金量 {score}</span>')
            meta_html = " · ".join(meta_parts)
            keywords = a.get("keywords") or []
            kw_html = "".join(f'<span class="tag">{esc(k)}</span>' for k in keywords)
            refined = a.get("refined") or ""
            takeaway = a.get("takeaway") or ""
            takeaway_html = (
                f'<div class="takeaway"><span class="tk-label">💡 AI 读后感</span>{esc(takeaway)}</div>'
                if takeaway else ""
            )
            cards.append(f"""
        <article class="card">
          <div class="card-inner">
            <h3><a href="{link}" target="_blank">{esc(title)}</a></h3>
            <div class="meta">{meta_html}</div>
            <p class="refined">{esc(refined)}</p>
            <div class="tags">{kw_html}</div>
            {takeaway_html}
            <a class="read-more" href="{link}" target="_blank">阅读原文 →</a>
          </div>
        </article>""")
        cards_html = "\n".join(cards)
        sections.append(f"""
      <section class="cat-section">
        <div class="cat-header">{emoji} {cat}<span class="cat-count">{len(arts)} 篇 · 均分 {avg_score:.0f}</span></div>
        {cards_html}
      </section>""")
    sections_html = "\n".join(sections)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>资讯日报 {digest['date']}</title>
</head>
<body>
<div class="wrap">
  <header>
    <div class="date">{digest['date']}</div>
    <h1>📮 每日资讯 AI 精读</h1>
    <p class="sub">{esc(digest['headline'])} · 精选 {len(digest['articles'])} 篇（重磅 {imp_count} 篇）</p>
  </header>

  <section class="synthesis">
    <div class="syn-title">🧠 AI 今日总览</div>
    <p class="overview">{esc(overview)}</p>
    <div class="syn-sub">今日要点</div>
    <ul class="highlights">{hl_html}</ul>
  </section>

  {sections_html}

  <footer>由 WorkBuddy 自动生成 · 共 {len(digest['articles'])} 篇（🌟 重磅 {imp_count} · 📄 速览 {gen_count}）· 按含金量倒序</footer>
</div>
<style>
  body{{margin:0;background:#f2f3f5;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",Arial,sans-serif;color:#1f1f1f;}}
  .wrap{{max-width:720px;margin:0 auto;padding:16px;}}
  header{{text-align:center;padding:18px 0 4px;}}
  .date{{color:#fa5151;font-weight:700;letter-spacing:1px;}}
  h1{{font-size:22px;margin:6px 0;}}
  .sub{{color:#888;font-size:13px;margin:0;}}
  .synthesis{{background:linear-gradient(135deg,#fff,#fff7f7);border:1px solid #ffe0e0;border-radius:16px;padding:16px 18px;margin:14px 0;}}
  .syn-title{{font-weight:700;color:#fa5151;font-size:15px;margin-bottom:8px;}}
  .overview{{font-size:14.5px;line-height:1.75;margin:0 0 12px;color:#222;}}
  .syn-sub{{font-size:13px;color:#999;margin-bottom:4px;}}
  .highlights{{margin:0;padding-left:18px;}}
  .highlights li{{font-size:14px;line-height:1.7;margin:5px 0;color:#333;}}
  .cat-section{{margin:16px 0;}}
  .cat-header{{font-size:17px;font-weight:700;color:#1a1a1a;padding:10px 14px;background:#fff;border-radius:10px;border-left:4px solid #fa5151;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;}}
  .cat-count{{font-size:12px;color:#999;font-weight:400;background:#f2f3f5;padding:2px 8px;border-radius:10px;}}
  .card{{background:#fff;border-radius:14px;margin:10px 0;box-shadow:0 2px 10px rgba(0,0,0,.05);}}
  .card-inner{{padding:14px 16px;}}
  .card h3{{font-size:16px;margin:0 0 4px;line-height:1.4;}}
  .card h3 a{{color:#1a1a1a;text-decoration:none;}}
  .card h3 a:hover{{color:#fa5151;}}
  .meta{{font-size:12px;color:#999;margin-bottom:6px;}}
  .star{{color:#fa5151;font-weight:600;background:#fff0f0;padding:1px 6px;border-radius:8px;}}
  .score{{color:#b8860b;font-weight:600;background:#fff8e1;padding:1px 6px;border-radius:8px;}}
  .refined{{font-size:14px;color:#333;line-height:1.8;margin:8px 0;}}
  .tags{{margin-top:4px;}}
  .tag{{display:inline-block;background:#f2f3f5;color:#576b95;font-size:12px;padding:2px 8px;border-radius:10px;margin-right:6px;}}
  .takeaway{{margin-top:10px;padding:10px 12px;background:#f6f8ff;border-left:3px solid #576b95;border-radius:6px;font-size:13.5px;color:#444;line-height:1.7;}}
  .tk-label{{font-weight:700;color:#576b95;margin-right:6px;}}
  .read-more{{display:inline-block;margin-top:10px;font-size:12.5px;color:#fa5151;text-decoration:none;font-weight:600;}}
  .read-more:hover{{text-decoration:underline;}}
  footer{{text-align:center;color:#bbb;font-size:12px;padding:20px 0;}}
</style>
</body>
</html>"""


# ---------- 推送：公众号客服消息 ----------
def push_wechat(cfg, digest):
    wc = cfg.get("wechat", {})
    if not (wc.get("appid") and wc.get("appsecret") and wc.get("openid")):
        log("未配置微信公众号凭据，跳过推送。")
        return False
    if requests is None:
        raise SystemExit("缺少 requests")
    r = requests.get("https://api.weixin.qq.com/cgi-bin/token",
                    params={"grant_type": "client_credential", "appid": wc["appid"], "secret": wc["appsecret"]},
                    timeout=20).json()
    if "access_token" not in r:
        log(f"获取 access_token 失败：{r}")
        return False
    token = r["access_token"]
    date = digest["date"]
    base = (wc.get("public_base_url") or "").rstrip("/")
    if base:
        url = f"{base}/digest_{date}.html"
        articles = [{"title": f"公众号日报 {date}", "description": digest["headline"], "url": url, "picurl": ""}]
        payload = {"touser": wc["openid"], "msgtype": "news", "news": {"articles": articles}}
    else:
        lines = [f"📮 公众号日报 {date}", digest["headline"], "", "【AI 今日总览】",
                 digest["synthesis"].get("overview", ""), "", "【今日要点】"]
        for h in digest["synthesis"].get("highlights", []):
            lines.append(f"- {h}")
        for a in digest["articles"]:
            t = a.get("ai_title") or a.get("title")
            lines.append(f"\n- {t}({a['author']})\n  {(a.get('refined') or a.get('summary',''))[:80]}")
        payload = {"touser": wc["openid"], "msgtype": "text", "text": {"content": "\n".join(lines)}}
    r2 = requests.post("https://api.weixin.qq.com/cgi-bin/message/custom/send",
                      params={"access_token": token}, json=payload, timeout=20).json()
    if r2.get("errcode") == 0:
        log("客服消息推送成功")
        return True
    else:
        log(f"客服消息推送失败：{r2}（注意：客服消息要求 48 小时内用户曾与公众号互动）")
        return False


# ---------- 推送：企业微信（精简分类版）----------
WECOM_MD_LIMIT = 3800  # 企业微信 markdown 单条上限 4096 字节，留余量


def _blocks_for_wecom(digest):
    """精简分类版：总览一条 + 按分类列表（标题+一句话+链接），每块 <4096 字节。"""
    syn = digest.get("synthesis", {})
    grouped = digest.get("grouped", {})
    blocks = []

    # 第 1 块：标题 + 今日总览 + 要点
    head = [f"# 📮 公众号日报 {digest['date']}", digest["headline"], "",
            "**🧠 AI 今日总览**", syn.get("overview", ""), "", "**📌 今日要点**"]
    for h in syn.get("highlights", []):
        head.append(f"> {h}")
    blocks.append("\n".join(head))

    # 后续块：按板块列出（板块顺序按含金量、板块内按含金量降序），重要文章完整（标题+一句话+链接），一般文章精简（标题+链接）
    cat_order = digest.get("cat_order", CATEGORIES)
    for cat in cat_order:
        arts = grouped.get(cat, [])
        if not arts:
            continue
        emoji = CAT_EMOJI.get(cat, "")
        cat_lines = [f"### {emoji} {cat}（{len(arts)}篇）"]
        for a in arts:
            title = a.get("ai_title") or a.get("title")
            score = _score(a)
            if a.get("importance") == "重要":
                one_liner = a.get("one_liner") or (a.get("refined") or "")[:25]
                cat_lines.append(f"⭐[{score}] **{title}**\n{one_liner}\n[→阅读]({a['link']})")
            else:
                cat_lines.append(f"•[{score}] **{title}** [→阅读]({a['link']})")
        cat_text = "\n".join(cat_lines)

        # 如果加上当前块会超限，先保存当前块再开新块
        if len(cat_text.encode("utf-8")) > WECOM_MD_LIMIT:
            # 单个分类就超限，拆分该分类
            chunks = [cat_lines[0]]  # header
            for line in cat_lines[1:]:
                if len("\n".join(chunks + [line]).encode("utf-8")) > WECOM_MD_LIMIT:
                    blocks.append("\n".join(chunks))
                    chunks = [f"### {emoji} {cat}（续）", line]
                else:
                    chunks.append(line)
            if len(chunks) > 1:
                blocks.append("\n".join(chunks))
        elif blocks and len("\n".join([blocks[-1], "", cat_text]).encode("utf-8")) <= WECOM_MD_LIMIT:
            # 可以追加到上一块
            blocks[-1] = "\n".join([blocks[-1], "", cat_text])
        else:
            blocks.append(cat_text)

    return [b for b in blocks if b.strip()]


def build_wecom_markdown(digest):
    """兼容旧接口：返回合并后的完整 markdown（仅供预览/测试）。"""
    return "\n\n".join(_blocks_for_wecom(digest))


def _send_wecom_markdown(w, content):
    """发送单条 markdown，返回企业微信响应 dict。"""
    mode = (w.get("mode") or "webhook").lower()
    if mode == "app" and w.get("corpid") and w.get("corpsecret") and w.get("agentid"):
        tok = requests.get("https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                           params={"corpid": w["corpid"], "corpsecret": w["corpsecret"]}, timeout=20).json()
        if "access_token" not in tok:
            return {"errcode": -1, "errmsg": f"gettoken failed: {tok}"}
        return requests.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={tok['access_token']}",
            json={"touser": w.get("touser", "@all"), "msgtype": "markdown",
                  "agentid": int(w["agentid"]), "markdown": {"content": content}},
            timeout=20).json()
    elif w.get("webhook"):
        return requests.post(w["webhook"], json={"msgtype": "markdown", "markdown": {"content": content}},
                             timeout=20).json()
    return None


def push_wecom(cfg, digest):
    w = (cfg.get("wechat") or {}).get("wecom", {})
    if not w:
        log("未配置企业微信凭据，跳过推送。")
        return False
    if requests is None:
        raise SystemExit("缺少 requests")
    if not (w.get("webhook") or (w.get("corpid") and w.get("corpsecret") and w.get("agentid"))):
        log("未填写企业微信 webhook 或自建应用凭据，跳过推送。")
        return False
    blocks = _blocks_for_wecom(digest)
    try:
        ok_all = True
        for i, block in enumerate(blocks, 1):
            r = _send_wecom_markdown(w, block)
            if r is None:
                log("未填写企业微信 webhook 或自建应用凭据，跳过推送。")
                return False
            if r.get("errcode") == 0:
                log(f"企业微信推送成功 ({i}/{len(blocks)})")
            else:
                ok_all = False
                log(f"企业微信推送失败 ({i}/{len(blocks)})：{r}")
        return ok_all
    except Exception as ex:
        log(f"企业微信推送异常：{ex}")
        return False


# ---------- 演示数据（含金量版）----------
DEMO_ARTICLES = [
    {
        "title": "(原标题)央行降准0.5个百分点",
        "author": "36氪",
        "link": "https://example.com/a1",
        "pub_dt": datetime.datetime(2026, 8, 10, 8, 20, tzinfo=BJ_TZ),
        "ai_title": "央行降准0.5个百分点释放长期资金约1万亿",
        "refined": "央行宣布全面降准0.5个百分点，预计释放长期资金约1万亿元，有助于降低金融机构资金成本，进而引导LPR下行，支持实体经济融资需求。结合近期经济数据偏弱，此次操作体现了货币政策加大逆周期调节力度的意图。流动性环境将进一步宽松，对债市构成利好，股市流动性预期改善。",
        "keywords": ["央行", "降准", "流动性"],
        "takeaway": "这是一次典型的政策信号解读：降准影响的不只是资金量，更在预期管理。可以观察随后LPR是否联动下调、银行净息差压力，以及地产链的资金敏感度——政策利率的传导链条比数字本身更值得跟踪。",
        "one_liner": "央行降准0.5个百分点，释放长期资金约1万亿",
        "category": "宏观政策",
        "importance": "重要",
        "score": 96,
    },
    {
        "title": "(原标题)大模型推理成本一年降了10倍",
        "author": "虎嗅APP",
        "link": "https://example.com/a2",
        "pub_dt": datetime.datetime(2026, 8, 10, 8, 5, tzinfo=BJ_TZ),
        "ai_title": "推理成本一年降约九成：AI从奢侈品走向水电煤",
        "refined": "过去一年主流大模型每token推理成本断崖式下降，驱动来自推理芯片产能释放叠加模型蒸馏与量化，单位成本降幅约90%；中小团队得以跑起可用的大模型应用，创业门槛被显著拉低，并倒逼应用层创新，Agent与端侧部署成为新热点。成本下探正在把AI从'奢侈品'变为'基础设施'。",
        "keywords": ["大模型", "推理成本", "Agent"],
        "takeaway": "成本下降类新闻最值得用「S曲线」框架读：当某项技术的单位成本骤降，通常预示渗透率拐点。可以对比历史上光伏、存储芯片的价格崩塌如何改写行业格局，并留意应用层哪些场景先跑通商业闭环。",
        "one_liner": "推理成本一年降90%，AI从奢侈品走向基础设施",
        "category": "信息技术",
        "importance": "重要",
        "score": 90,
    },
    {
        "title": "(原标题)某新能源车企Q3财报超预期",
        "author": "钛媒体",
        "link": "https://example.com/a3",
        "pub_dt": datetime.datetime(2026, 8, 9, 20, 10, tzinfo=BJ_TZ),
        "ai_title": "新能源车企Q3营收同比增65%，毛利率首破20%",
        "refined": "某头部新能源车企发布Q3财报，营收同比增长65%超市场预期，毛利率首次突破20%，主要受益于电池成本下降和交付量提升。公司同时上调全年交付指引。新能源汽车行业盈利能力正在改善，规模效应逐步显现，但竞争格局仍在加剧。",
        "keywords": ["新能源", "财报", "毛利率"],
        "takeaway": "毛利率突破20%是规模效应的里程碑信号。读财报时可以把「毛利率」和「交付量增速」对照：若毛利率提升由规模摊薄驱动而非涨价，说明行业竞争仍烈，价格战风险未消。",
        "one_liner": "新能源车企Q3营收增65%，毛利率首破20%",
        "category": "金融财经",
        "importance": "一般",
        "score": 72,
    },
    {
        "title": "(原标题)白酒行业库存危机加剧",
        "author": "晚点LatePost",
        "link": "https://example.com/a4",
        "pub_dt": datetime.datetime(2026, 8, 9, 22, 40, tzinfo=BJ_TZ),
        "ai_title": "白酒渠道库存高企，经销商资金链承压",
        "refined": "白酒行业渠道库存持续攀升，部分品牌库存周期超过6个月，经销商资金链承压，部分已开始低价甩货，导致终端价格倒挂。厂商虽然控量稳价，但效果有限。白酒行业进入深度调整期，去库存可能持续2-3个季度，期间品牌分化将进一步加剧。",
        "keywords": ["白酒", "库存", "消费"],
        "takeaway": "渠道库存是消费品行业的『先行指标』：终端动销数据往往滞后，但渠道库存与价格倒挂会提前暴露周期拐点。可把它与居民消费数据、餐饮景气度做交叉验证，判断消费板块的真实水位。",
        "one_liner": "白酒渠道库存高企，经销商资金链承压",
        "category": "商业企业",
        "importance": "一般",
        "score": 78,
    },
    {
        "title": "(原标题)为什么你的RAG检索总是不准",
        "author": "钛媒体",
        "link": "https://example.com/a5",
        "pub_dt": datetime.datetime(2026, 8, 9, 19, 30, tzinfo=BJ_TZ),
        "ai_title": "RAG不准的三处基本功：切分、混合召回与重排",
        "refined": "许多RAG系统检索质量不佳，常被归咎于模型。根因往往在工程基本功——切分粒度太粗导致语义混杂、仅用向量召回缺BM25混合使长尾query失效、缺少重排（rerank）让相关结果沉底。应先以行为数据评估召回率再谈生成，把基础环节做扎实，而非一味更换模型。",
        "keywords": ["RAG", "检索", "工程"],
        "takeaway": "这篇文章给了一个工程方法论：问题定位先于方案替换。『换模型』是直觉反应，但系统性排查（数据切分→召回→重排→评估）才是ROI最高的路径——这套思路同样适用于任何系统优化的排障过程。",
        "one_liner": "RAG不准的根因在切分、混合召回与重排三处基本功",
        "category": "信息技术",
        "importance": "一般",
        "score": 65,
    },
]

DEMO_SYNTHESIS = {
    "overview": "今天五篇文章横跨宏观、科技、金融与产业四大领域。最值得关注的是央行降准释放万亿流动性，叠加AI推理成本骤降90%推动应用落地——宏观宽松与科技降本正在形成共振。新能源汽车Q3盈利能力改善验证了规模效应，白酒库存危机则提醒消费端仍存压力。RAG工程基本功的讨论为技术团队提供了实操参考。",
    "highlights": [
        "央行降准0.5个百分点，释放长期资金约1万亿，流动性进一步宽松（36氪）。",
        "AI推理成本一年降约90%，应用创业门槛显著拉低（虎嗅APP）。",
        "白酒渠道库存高企，行业进入深度调整期（晚点LatePost）。",
        "新能源车企Q3毛利率首破20%，规模效应逐步显现（钛媒体）。",
    ],
}


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    cfg = load_config()

    # 环境变量覆盖密钥（优先级高于 config.yaml，用于 GitHub Actions / CI）
    if cfg:
        env_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("LLM_API_KEY")
        if env_key:
            cfg.setdefault("llm", {})["api_key"] = env_key
        env_base = os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("LLM_BASE_URL")
        if env_base:
            cfg.setdefault("llm", {})["base_url"] = env_base
        env_model = os.environ.get("DEEPSEEK_MODEL") or os.environ.get("LLM_MODEL")
        if env_model:
            cfg.setdefault("llm", {})["model"] = env_model
        env_webhook = os.environ.get("WECOM_WEBHOOK")
        if env_webhook:
            cfg.setdefault("wechat", {}).setdefault("wecom", {})["webhook"] = env_webhook

    demo = args.demo or not is_configured(cfg)
    if demo and not args.demo:
        log("未检测到有效 feeds 配置，进入演示模式（生成样例 HTML，不推送）。")

    if demo:
        articles = DEMO_ARTICLES
        synthesis = DEMO_SYNTHESIS
    else:
        # 读取去重状态（CI 环境可能没有，容错处理）
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {"seen": []}
            seen = set(state["seen"])
        except Exception:
            seen = set()
        maxn = (cfg.get("settings") or {}).get("max_articles", 30)
        settings = cfg.get("settings") or {}
        window_end_cfg = settings.get("window_end", "08:40")
        window_start, window_end = compute_window(window_end_cfg, settings.get("lookback_hours", 24))
        log(f"采集窗口（北京时间）：{window_start:%Y-%m-%d %H:%M} ~ {window_end:%Y-%m-%d %H:%M}")
        articles = []
        for f in cfg["feeds"]:
            try:
                raw = fetch_feed(f["name"], f["url"])
                d = feedparser.parse(raw)
                for e in d.entries:
                    if not in_window(e, window_start, window_end):
                        continue
                    guid = e.get("id") or e.get("guid") or e.get("link", "")
                    if guid in seen:
                        continue
                    content = (e.get("content") and e["content"][0].get("value")) or e.get("description") or ""
                    it = {
                        "title": e.get("title", "").strip(),
                        "link": e.get("link", "").strip(),
                        "author": (e.get("author") or f["name"]).strip(),
                        "published": e.get("published", ""),
                        "pub_dt": parse_feed_date_bj(e),
                        "content": content,
                        "guid": guid,
                    }
                    articles.append(it)
                    seen.add(guid)
            except Exception as ex:
                log(f"  采集「{f['name']}」失败，已跳过：{ex}")
        log(f"采集到 {len(articles)} 篇新文章（窗口 {window_start:%H:%M} ~ {window_end:%H:%M}，北京时间）")
        # AI 预筛选：从大量文章中选出最具新闻价值的 N 篇
        if len(articles) > maxn:
            log(f"文章数({len(articles)})超上限({maxn})，启动 AI 预筛选...")
        articles, screening_reason = prescreen_articles(articles, cfg.get("llm"), maxn)
        log(f"筛选后保留 {len(articles)} 篇，开始 AI 逐篇深度阅读与总结...")
        for i, a in enumerate(articles, 1):
            a.update(summarize(a, cfg.get("llm")))
            cat = a.get("category", "其他")
            imp = a.get("importance", "一般")
            log(f"  [{i}/{len(articles)}] {a.get('ai_title','')[:30]}... [{cat}/{imp}]")
        synthesis = synthesize(articles, cfg.get("llm"))
        # 写入去重状态（CI 环境可能无法写，容错处理）
        try:
            seen_list = list(seen)[-500:]
            STATE_PATH.write_text(json.dumps({"seen": seen_list}, ensure_ascii=False), encoding="utf-8")
        except Exception:
            log("  去重状态写入失败（CI 环境正常，不影响运行）")

    articles = articles[: (cfg.get("settings", {}).get("max_articles", 30) if cfg else 30)]
    digest = build_digest(articles, synthesis)

    # 打印分类统计
    for cat in CATEGORIES:
        n = digest["cat_stats"].get(cat, 0)
        if n:
            log(f"  {CAT_EMOJI.get(cat,'')} {cat}: {n} 篇")

    out = WORKSPACE / "output"
    out.mkdir(exist_ok=True)
    path = out / f"digest_{digest['date']}.html"
    path.write_text(render_html(digest), encoding="utf-8")
    log(f"HTML 已生成：{path}")

    if not args.no_push and not demo:
        wtype = (cfg.get("wechat") or {}).get("type", "official")
        if wtype == "wecom":
            push_wecom(cfg, digest)
        else:
            push_wechat(cfg, digest)


if __name__ == "__main__":
    main()
