#!/usr/bin/env python3
"""生成 GitHub Pages 归档索引页。在 CI 中调用。"""
import glob
import os

files = sorted(glob.glob("output/digest_*.html"), reverse=True)

links = "\n".join(
    '<li><a href="{name}">{date}</a></li>'.format(
        name=os.path.basename(f),
        date=os.path.basename(f).replace("digest_", "").replace(".html", ""),
    )
    for f in files
)

html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>公众号每日摘要 - 历史归档</title>
<style>
body{font-family:system-ui;max-width:680px;margin:40px auto;padding:0 16px;color:#333}
h1{font-size:1.4em}
li{margin:8px 0}
a{color:#0969da;text-decoration:none}
a:hover{text-decoration:underline}
</style>
</head>
<body>
<h1>公众号每日摘要 - 历史归档</h1>
<p>最新日报：<a href="index.html">点击查看</a></p>
<h2>历史归档</h2>
<ul>
{links}
</ul>
</body>
</html>""".format(links=links)

with open("output/archive.html", "w", encoding="utf-8") as f:
    f.write(html)

print("archive.html generated with", len(files), "entries")
