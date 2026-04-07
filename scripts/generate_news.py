#!/usr/bin/env python3
"""Daily Japan + Global Startup News Generator"""

import anthropic
import os
import sys
import re
import html as html_module
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

JST = timezone(timedelta(hours=9))
now = datetime.now(JST)
date_str = now.strftime("%Y%m%d")
year = now.strftime("%Y")
month = now.strftime("%m")
day = now.strftime("%d")
weekdays_ja = ["月", "火", "水", "木", "金", "土", "日"]
weekday_ja = weekdays_ja[now.weekday()]


def clean_html_text(text):
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = html_module.unescape(clean)
    return clean.strip()[:300]


def fetch_rss(url, max_items=15):
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; startup-news-bot/1.0)"}
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
            pub = item.findtext("pubDate", "")
            if title and link:
                items.append({"title": title, "link": link, "desc": desc, "pub": pub})
        if not items:
            atom_ns = "http://www.w3.org/2005/Atom"
            for entry in root.findall(f".//{{{atom_ns}}}entry")[:max_items]:
                title = clean_html_text(entry.findtext(f"{{{atom_ns}}}title", ""))
                link_el = entry.find(f"{{{atom_ns}}}link[@rel='alternate']")
                if link_el is None:
                    link_el = entry.find(f"{{{atom_ns}}}link")
                link = link_el.get("href", "") if link_el is not None else ""
                desc = clean_html_text(
                    entry.findtext(f"{{{atom_ns}}}summary", "") or
                    entry.findtext(f"{{{atom_ns}}}content", "")
                )
                pub = entry.findtext(f"{{{atom_ns}}}updated", "")
                if title and link:
                    items.append({"title": title, "link": link, "desc": desc, "pub": pub})
        return items
    except Exception as e:
        print(f"  Warning: Failed to fetch {url}: {e}")
        return []


FEEDS = [
    # Japan
    {"name": "StartupTimes (日本)", "url": "https://startup-times.jp/feed", "region": "japan"},
    {"name": "Coral Capital", "url": "https://coralcap.co/feed/", "region": "japan"},
    {"name": "Techable (日本)", "url": "https://techable.jp/feed", "region": "japan"},
    {"name": "BRIDGE (日本)", "url": "https://thebridge.jp/feed/", "region": "japan"},
    # Global
    {"name": "TechCrunch", "url": "https://techcrunch.com/category/startups/feed/", "region": "global"},
    {"name": "VentureBeat", "url": "https://venturebeat.com/feed/", "region": "global"},
    {"name": "Crunchbase News", "url": "https://news.crunchbase.com/feed/", "region": "global"},
    {"name": "The Information", "url": "https://www.theinformation.com/feed", "region": "global"},
    {"name": "Bloomberg Technology", "url": "https://feeds.bloomberg.com/technology/news.rss", "region": "global"},
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
  .footer { text-align: center; padding: 32px 16px; color: #aaa; font-size: 0.85em; }
  .back-link { display: inline-block; margin-top: 24px; color: #0066cc; text-decoration: none; font-size: 0.9em; }
  .back-link:hover { text-decoration: underline; }
"""


def format_for_prompt(articles, max_items=20):
    lines = []
    for i, a in enumerate(articles[:max_items], 1):
        lines.append(f"\n{i}. {a['title']}")
        lines.append(f"   出典: {a['source']}")
        lines.append(f"   URL: {a['link']}")
        if a["desc"]:
            lines.append(f"   概要: {a['desc']}")
    return "\n".join(lines) if lines else "（本日の記事なし）"


def main():
    print(f"Generating startup news for {year}/{month}/{day} ({weekday_ja})")
    print("\nFetching RSS feeds...")
    all_articles = []
    for feed in FEEDS:
        articles = fetch_rss(feed["url"])
        print(f"  {feed['name']}: {len(articles)} articles")
        for a in articles:
            a["source"] = feed["name"]
            a["region"] = feed["region"]
        all_articles.extend(articles)

    japan_articles = [a for a in all_articles if a["region"] == "japan"]
    global_articles = [a for a in all_articles if a["region"] == "global"]
    print(f"\nTotal: Japan {len(japan_articles)}, Global {len(global_articles)}")

    prompt = (
        f"以下のRSSから取得したニュース記事を元に、{year}年{month}月{day}日（{weekday_ja}曜日）の"
        "スタートアップニュースHTMLページを生成してください。\n\n"
        f"## 日本のスタートアップニュース\n{format_for_prompt(japan_articles)}\n\n"
        f"## 世界のスタートアップニュース\n{format_for_prompt(global_articles)}\n\n"
        "## 生成ルール\n"
        "1. 完全なHTMLファイルのみ出力（<!DOCTYPE html>から</html>まで）\n"
        "2. HTMLのみ出力。説明文やマークダウン記号(```)は一切含めない\n"
        "3. スタートアップに無関係な記事は除外する\n"
        "4. 各記事をカテゴリ分類: 資金調達 / 新サービス・プロダクト / M&A・業界動向\n"
        "5. 英語記事は日本語に翻訳して表示する\n"
        "6. サマリーは4〜5文\n\n"
        f"## CSS（styleタグ内に使用）\n{HTML_CSS}\n\n"
        "## HTML構造テンプレート\n"
        f"<!DOCTYPE html><html lang=\"ja\"><head><meta charset=\"UTF-8\">"
        f"<title>スタートアップニュース - {year}年{month}月{day}日</title>"
        "<style>/* 上記CSSをここに */</style></head><body>"
        "<div class=\"header\"><h1>\U0001f4f0 スタートアップニュース</h1>"
        f"<div class=\"date\">{year}年{month}月{day}日（{weekday_ja}曜日）</div></div>"
        "<div class=\"container\">"
        "<div class=\"summary-box\"><h2>\U0001f4cb 本日のサマリー</h2><p>[サマリー]</p></div>"
        "<div class=\"region-header\"><h2>\U0001f1ef\U0001f1f5 日本のスタートアップ</h2>"
        "<div class=\"region-divider\"></div></div>"
        "[日本ニュースカード - section-titleで区切ってカテゴリ別に]"
        "<div class=\"region-header\"><h2>\U0001f30d 世界のスタートアップ</h2>"
        "<div class=\"region-divider\"></div></div>"
        "[グローバルニュースカード - カテゴリ別、region-badgeで国旗+国名付き]"
        "<a href=\"https://fitersowner-a11y.github.io/startup-news/\" class=\"back-link\">"
        "\u2190 ニュース一覧に戻る</a></div>"
        f"<div class=\"footer\">自動収集・生成 by Claude AI \uff5c {year}年{month}月{day}日</div>"
        "</body></html>"
    )

    print("\nCalling Claude API...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )

    html_output = ""
    for block in response.content:
        if hasattr(block, "text"):
            text = block.text.strip()
            # Strip markdown code fences if present
            if "```" in text:
                m = re.search(r"```(?:html)?\s*(<!DOCTYPE.*?</html>)", text, re.DOTALL | re.IGNORECASE)
                if m:
                    html_output = m.group(1)
                    break
            if "<!doctype html>" in text.lower():
                start = text.lower().find("<!doctype html>")
                end = text.lower().rfind("</html>") + len("</html>")
                if start != -1 and end > start:
                    html_output = text[start:end]
                    break

    if not html_output or len(html_output) < 500:
        print(f"ERROR: No valid HTML generated (length: {len(html_output)})")
        sys.exit(1)

    print(f"HTML: {len(html_output)} chars")
    output_dir = Path(date_str)
    output_dir.mkdir(exist_ok=True)
    (output_dir / "index.html").write_text(html_output, encoding="utf-8")
    print(f"Saved: {date_str}/index.html")

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
    print(f"\nDone! {url_out}")
    print(f"\n[Teams]\n\U0001f4f0 本日のスタートアップニュースまとめ（{month}/{day}）\U0001f1ef\U0001f1f5 日本 + \U0001f30d グローバル\n\U0001f449 {url_out}")


if __name__ == "__main__":
    main()
