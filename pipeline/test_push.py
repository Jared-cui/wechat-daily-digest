#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键测试推送：填好 config.yaml 里的企业微信 webhook（或自建应用）后，
运行本脚本即可向企业微信发送一条测试消息，立即验证推送链路是否打通。

用法：
  python test_push.py
"""
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(ROOT))

from run_digest import load_config, push_wecom, log  # noqa: E402


def main():
    cfg = load_config()
    wc = (cfg or {}).get("wechat", {})
    w = wc.get("wecom", {})

    # 校验是否已配置
    if wc.get("type") != "wecom" or not w:
        log("config.yaml 未配置企业微信（wechat.type 应为 wecom，且 wechat.wecom 需填写）。")
        return
    mode = (w.get("mode") or "webhook").lower()
    if mode == "webhook" and not w.get("webhook"):
        log("未填写 wechat.wecom.webhook。请先在企业微信建群 → 添加群机器人 → 复制 webhook 地址填入。")
        return
    if mode == "app" and not (w.get("corpid") and w.get("corpsecret") and w.get("agentid")):
        log("mode=app 但未填齐 corpid/corpsecret/agentid，请补全自建应用凭据。")
        return

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    digest = {
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "headline": "推送连通性自测",
        "synthesis": {
            "overview": "这是一次推送连通性自测，内容无需关注。若你收到了这条消息，说明企业微信推送链路已打通 ✅。",
            "highlights": ["若收到本消息，说明企业微信推送已配置成功 ✅"],
        },
        "articles": [{
            "ai_title": "推送测试消息",
            "author": "WorkBuddy",
            "link": "https://example.com",
            "refined": f"这是一条于 {now} 发送的推送连通性测试消息，用于确认 webhook 配置正确。看到它即代表成功。",
            "tags": ["测试"],
        }],
    }

    log("开始发送测试推送…")
    ok = push_wecom(cfg, digest)
    if ok:
        log("✅ 测试推送成功！去企业微信看看是否收到了「推送测试消息」。")
    else:
        log("❌ 测试推送失败，请检查 webhook 地址或网络后重试。")


if __name__ == "__main__":
    main()
