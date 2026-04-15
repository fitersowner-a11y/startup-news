#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daily Japan + Global Startup News Generator with deduplication"""

import anthropic
import os
import sys
import re
import json
import html as html_module
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request
import xml.etree.ElementTree as ET

JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
date_str = now.strftime("%Y%m%d")
year = now.strftime("%Y")
month = now.strftime("%m")
day = now.strftime("%d")
weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
weekday_ja = weekdays_ja[now.weekday()]

SEEN_FILE = Path("seen_articles.json")
KEEP_DAYS = 30
MAX_PER_REGION = 20  # プロンプトに渡す記事の上限


def load_seen_urls():
    if not SEEN_FILE.exists():
        return {}
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        cutoff = (now - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
        return {url: d for url, d in data.items() if d >= cutoff}
    except Exception as e:
        print(f"  Warning: Could not load seen_articles.json: {e}")
        return {}


def save_seen_urls(seen: dict, new_urls: list):
    for url in new_urls:
        seen[url] = date_str
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Saved {len(new_urls)} new URLs (total seen: {len(seen)})")


def clean_html_text(text):
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = html_module.unescape(clean)
    return clean.strip()[:200]


def fetch_rss(url, max_items=20):
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read()
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            content_str = content.decode("utf-8", errors="ignore")
            content_str = re.sub(r"<\?xml[^>]+\?>", "", content_str)
            root = ET.fromstring(content_str)
        items = []
        for item in root.findall(".//item")[:max_items]:
            title = clean_html_text(item.findtext("title", ""))
            link = item.findtext("link", "").strip()
            desc = clean_html_text(item.findtext("description", ""))
            if title and link:
                items.append({"title": title, "link": link, "desc": desc})
        if not items:
            atom_ns = "http://www.w3.org/2005/Atom"
            for entry in root.findall(f".//{{{atom_ns}}}entry")[:max_items]:
                title = clean_html_text(entry.findtext(f"{{{atom_ns}}}title", ""))
                link_el = entry.find(f"{{{atom_ns}}}link[@rel='alternate']") or entry.find(f"{{{atom_ns}}}link")
                link = link_el.get("href", "") if link_el is not None else ""
                desc = clean_html_text(entry.findtext(f"{{{atom_ns}}}summary", "") or entry.findtext(f"{{{atom_ns}}}content", ""))
                if title and link:
                    items.append({"title": title, "link": link, "desc": desc})
        return items
    except Exception as e:
        print(f"  Warning: {url}: {e}")
        return []


FEEDS = [
    # 日本（Bot制限が少ないフィードを優先）
    {"name": "Coral Capital",    "url": "https://coralcap.co/feed/",                                   "region": "japan"},
    {"name": "INITIAL",          "url": "https://initial.inc/feed",                                    "region": "japan"},
    {"name": "Startup DB",       "url": "https://startupdb.net/feed",                                  "region": "japan"},
    {"name": "PR Times IT",      "url": "https://prtimes.jp/rss/topics/technology/new/index.rdf",      "region": "japan"},
    {"name": "ITmedia News",     "url": "https://www.itmedia.co.jp/rss/subtop/news/index.xml",         "region": "japan"},
    {"name": "Impress Watch",    "url": "https://www.watch.impress.co.jp/data/rss/1.0/ipw/feed.rdf",   "region": "japan"},
    # グローバル（上限を絞る）
    {"name": "TechCrunch",       "url": "https://techcrunch.com/category/startups/feed/",              "region": "global"},
    {"name": "Crunchbase News",  "url": "https://news.crunchbase.com/feed/",                           "region": "global"},
    {"name": "VentureBeat",      "url": "https://venturebeat.com/category/business/feed/",             "region": "global"},
    {"name": "Bloomberg Tech",   "url": "https://feeds.bloomberg.com/technology/news.rss",             "region": "global"},
]

HTML_CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif; background: #f5f7fa; color: #333; }
  .header { background: linear-gradient(135deg, #0066cc, #004499); color: white; padding: 32px 20px; text-align: center; }
  .header h1 { font-size: 1.8em; margin-bottom: 8px; }
  .header .date { opacity: 0.85; font-size: 1em; }
  .container { max-width: 900px; margin: 32px auto; padding: 0 16px; }
  .summary-box { background: white; border-radius: 12px; padding: 20px 24px; margin-bottom: 28px; box-shadow: 0 2px 8px rgba(0,0,0,0.07); border-left: 4px solid #0066cc; }
  .summary-box h2 { font-size: 1em; color: #0066cc; margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.05em; }
  .summary-box p { line-height: 1.7; color: #555; }
  .region-header { display: flex; align-items: center; gap: 10px; margin: 32px 0 16px; }
  .region-header h2 { font-size: 1.3em; font-weight: bold; color: #222; white-space: nowrap; }
  .region-divider { flex: 1; height: 2px; background: linear-gradient(to right, #0066cc, transparent); }
  .section-title { font-size: 1em; font-weight: bold; color: #444; margin: 20px 0 10px; padding-left: 10px; border-left: 3px solid #0066cc; }
  .news-card { background: white; border-radius: 10px; padding: 18px 20px; margin-bottom: 12px; box-shadow: 0 1px 6px rgba(0,0,0,0.06); transition: box-shadow 0.2s; }
  .news-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.12); }
  .news-card .meta { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
  .news-card .company { font-size: 0.78em; font-weight: bold; color: #0066cc; background: #e8f0fb; padding: 2px 8px; border-radius: 20px; }
  .news-card .region-badge { font-size: 0.72em; padding: 2px 7px; border-radius: 12px; background: #f0f0f0; color: #666; }
  .news-card h3 { font-size: 1em; margin-bottom: 6px; line-height: 1.5; }
  .news-card h3 a { color: #222; text-decoration: none; }
  .news-card h3 a:hover { color: #0066cc; text-decoration: underline; }
  .news-card .summary { font-size: 0.9em; color: #666; line-height: 1.6; }
  .news-card .source { font-size: 0.78em; color: #aaa; margin-top: 8px; }
  .tag { display: inline-block; font-size: 0.72em; padding: 1px 7px; border-radius: 12px; font-weight: bold; }
  .tag-funding { background: #d4edda; color: #155724; }
  .tag-product { background: #d1ecf1; color: #0c5460; }
  .tag-ma { background: #f8d7da; color: #721c24; }
  .tag-other { background: #e2e3e5; color: #383d41; }
  .no-news { background: white; border-radius: 10px; padding: 24px; text-align: center; color: #999; margin-bottom: 12px; font-size: 0.95em; }
  .footer { text-align: center; padding: 32px 16px; color: #aaa; font-size: 0.85em; }
  .back-link { display: inline-block; margin-top: 24px; color: #0066cc; text-decoration: none; font-size: 0.9em; }
  .back-link:hover { text-decoration: underline; }
"""


def format_articles(articles):
    if not articles:
        return "（新着記事なし）"
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. [{a['source']}] {a['title']}")
        lines.append(f"   URL: {a['link']}")
        if a["desc"]:
            lines.append(f"   概要: {a['desc']}")
    return "\n".join(lines)


def build_prompt(japan_articles, global_articles):
    return f"""以下の新着ニュース記事を使って、{year}年{month}月{day}日（{weekday_ja}曜日）のスタートアップニュースページのHTMLを生成してください。

## 日本の新着ニュース（{len(japan_articles)}件）
{format_articles(japan_articles)}

## 世界の新着ニュース（{len(global_articles)}件）
{format_articles(global_articles)}

## ルール
- スタートアップ・テック・ビジネスに関係ない記事は除外
- 各記事をカテゴリ分類: 資金調達 / 新サービス・プロダクト / M&A・業界動向
- 英語記事は日本語に翻訳
- 新着なしの場合は「本日の新着ニュースはありません」と表示
- サマリーは3〜4文

## 出力形式
<!DOCTYPE html>のみ出力（説明文・```不要）

## HTML/CSS
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>スタートアップニュース - {year}年{month}月{day}日</title>
<style>{HTML_CSS}</style>
</head>
<body>
<div class="header">
  <h1>📰 スタートアップニュース</h1>
  <div class="date">{year}年{month}月{day}日（{weekday_ja}曜日）</div>
</div>
<div class="container">
  <div class="summary-box">
    <h2>📋 本日のサマリー</h2>
    <p>【ここにサマリー】</p>
  </div>

  <div class="region-header"><h2>🇯🇵 日本のスタートアップ</h2><div class="region-divider"></div></div>
  <div class="section-title">💰 資金調達</div>
  【日本・資金調達カード or <div class="no-news">新着なし</div>】

  <div class="section-title">🚀 新サービス・プロダクト</div>
  【日本・新サービスカード】

  <div class="section-title">🤝 M&A・業界動向</div>
  【日本・M&Aカード】

  <div class="region-header"><h2>🌍 世界のスタートアップ</h2><div class="region-divider"></div></div>
  <div class="section-title">💰 資金調達</div>
  【グローバル・資金調達カード】

  <div class="section-title">🚀 新サービス・プロダクト</div>
  【グローバル・新サービスカード】

  <div class="section-title">🤝 M&A・業界動向</div>
  【グローバル・M&Aカード】

  <a href="https://fitersowner-a11y.github.io/startup-news/" class="back-link">← ニュース一覧に戻る</a>
</div>
<div class="footer">自動収集・生成 by Claude AI ｜ {year}年{month}月{day}日</div>
</body>
</html>

## ニュースカード形式
<div class="news-card">
  <div class="meta">
    <span class="company">企業名</span>
    <span class="tag tag-funding">資金調達</span>
    <span class="region-badge">🇺🇸 米国</span>
  </div>
  <h3><a href="URL" target="_blank" rel="noopener">タイトル（日本語）</a></h3>
  <div class="summary">概要1〜2文</div>
  <div class="source">出典: メディア名</div>
</div>"""


def extract_html(text):
    """レスポンスからHTMLを抽出"""
    text = text.strip()
    # コードブロック内のHTMLを探す
    m = re.search(r"```(?:html)?\s*(<!DOCTYPE.*?</html>)", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1)
    # 直接HTMLを探す
    low = text.lower()
    start = low.find("<!doctype html>")
    if start == -1:
        start = low.find("<html")
    end = low.rfind("</html>")
    if start != -1 and end != -1 and end > start:
        return text[start:end + len("</html>")]
    return ""


def main():
    print(f"Generating startup news for {year}/{month}/{day} ({weekday_ja}曜日)")

    seen_urls = load_seen_urls()
    print(f"  Loaded {len(seen_urls)} seen URLs")

    print("\nFetching RSS feeds...")
    all_articles = []
    for feed in FEEDS:
        articles = fetch_rss(feed["url"])
        new = [a for a in articles if a["link"] not in seen_urls]
        skipped = len(articles) - len(new)
        status = f"{len(articles)}件取得"
        if skipped:
            status += f", {skipped}件重複除外"
        status += f" → {len(new)}件新着"
        print(f"  {feed['name']}: {status}")
        for a in new:
            a["source"] = feed["name"]
            a["region"] = feed["region"]
        all_articles.extend(new)

    japan_articles = [a for a in all_articles if a["region"] == "japan"][:MAX_PER_REGION]
    global_articles = [a for a in all_articles if a["region"] == "global"][:MAX_PER_REGION]
    print(f"\n新着: 日本 {len(japan_articles)}件, グローバル {len(global_articles)}件")

    print("\nCalling Claude API...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        messages=[{"role": "user", "content": build_prompt(japan_articles, global_articles)}],
    )

    html_output = ""
    for block in response.content:
        if hasattr(block, "text") and block.text:
            html_output = extract_html(block.text)
            if html_output:
                break

    if not html_output or len(html_output) < 500:
        # デバッグ用: レスポンス内容を出力
        print("ERROR: Could not extract valid HTML")
        for block in response.content:
            if hasattr(block, "text"):
                print(f"Response preview: {block.text[:300]}")
        sys.exit(1)

    print(f"HTML generated: {len(html_output)} chars")

    output_dir = Path(date_str)
    output_dir.mkdir(exist_ok=True)
    (output_dir / "index.html").write_text(html_output, encoding="utf-8")
    print(f"Saved: {date_str}/index.html")

    # 掲載済みURLを記録
    published_urls = [a["link"] for a in japan_articles + global_articles]
    save_seen_urls(seen_urls, published_urls)

    # トップページ更新
    index_path = Path("index.html")
    if index_path.exists():
        idx = index_path.read_text(encoding="utf-8")
        new_link = f'  <li><a href="./{date_str}/">{year}年{month}月{day}日（{weekday_ja}曜日）のニュース</a></li>\n'
        if date_str not in idx:
            if "ニュースは毎朝自動的に追加されます。" in idx:
                idx = idx.replace("  <li>ニュースは毎朝自動的に追加されます。</li>", new_link.rstrip())
            else:
                idx = idx.replace('<ul class="news-list" id="news-list">\n', f'<ul class="news-list" id="news-list">\n{new_link}')
            index_path.write_text(idx, encoding="utf-8")
            print("Updated index.html")

    url_out = f"https://fitersowner-a11y.github.io/startup-news/{date_str}/"
    print(f"\n✅ 完了! {url_out}")
    print(f"\n[Teams]\n📰 本日のスタートアップニュースまとめ（{month}/{day}）🇯🇵 日本 + 🌍 グローバル\n👉 {url_out}")


if __name__ == "__main__":
    main()
