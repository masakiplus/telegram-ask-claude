#!/usr/bin/env python3
"""「🤖 Claudeに投げる」ボタンの URL を組み立てる（tg_send.sh から呼ばれる。単体でも使える）。

飛び先は https://claude.ai/new?q=… で、通知の本文と前置きの依頼文を入力欄に入れた新規チャットが開く。
送信はしないので、押した人が読んで直してから送れる。

入力は環境変数（tg_send.sh が渡す）:
  MSG   ボタンに載せる本文（Telegram 用に切り詰める前の全文）
  PM    parse_mode。"HTML" ならタグを剥がして実体参照を戻す
  KIND  "alert" | "report"。空なら本文から推定する
  LEAD  前置きの依頼文。空なら KIND で決める
stdout に URL を1行出す。

  MSG="⚠️ バックアップが失敗しました" python3 claude_button_url.py
"""
import html
import os
import re
import sys
import urllib.parse

BASE = "https://claude.ai/new?q="
# Telegram のボタン URL は長すぎると sendMessage ごと失敗する（2000 前後で落ちるのを実測）。余裕を持たせる
MAX_URL = int(os.environ.get("CLAUDE_BUTTON_MAX_URL") or 1900)

# 障害っぽい語。これが入っていれば「対処してほしい」、無ければ「相談したい」の前置きにする
ALERT_RE = re.compile(
    r"⚠️|❌|🚨|失敗|異常|エラー|障害|(^|[^A-Za-z])NG([^A-Za-z]|$)|できず|できない|できません"
    r"|見つからない|見つかりません|止まって|停止|途絶|timeout|タイムアウト"
    r"|[Ee]rror|ERROR|\b[Ff]ail(s|ed|ure)?\b|\bFAIL(ED|URE)?\b|WARN|落ちた|落ちて")

LEADS = {
    "alert": "自動化から次の通知が来た。状況を確認し、原因と対処を教えてほしい。",
    "report": "自動化から次の定期レポートが届いた。この内容について相談したい。気になる点と次の一手を教えてほしい。",
}


def classify(text):
    return "alert" if ALERT_RE.search(text) else "report"


def fix(t):
    # claude.ai/new?q= 側で「+」が空白に、「%」が壊れた文字になるので、ボタンの中身だけ全角にする
    return t.replace("%", "％").replace("+", "＋")


def url(t):
    return BASE + urllib.parse.quote(fix(t), safe="")


def fit(prefix, text, suffix="", limit=None):
    """prefix + text[:n] + suffix が limit（既定 MAX_URL）に収まる最大の n で組み立てる（日本語は1字で約9バイトになる）。"""
    limit = limit or MAX_URL
    if len(url(prefix + text + suffix)) <= limit:
        return prefix + text + suffix
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(url(prefix + text[:mid] + "…" + suffix)) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return prefix + (text[:lo] + "…" if lo else "") + suffix


def strip_html(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def build(body, parse_mode="", kind="", lead=""):
    if parse_mode.upper() == "HTML":
        body = strip_html(body)
    lead = lead or LEADS[kind or classify(body)]
    if len(url(lead)) > MAX_URL // 2:
        lead = fit("", lead, limit=MAX_URL // 2)
    if len(url(lead + "\n\n" + body)) <= MAX_URL:
        return url(lead + "\n\n" + body)
    return url(fit(lead + "\n\n", body, "\n\n（本文が長いので途中で切っている）"))


def main():
    body = os.environ.get("MSG")
    if body is None:
        body = sys.stdin.read()
    print(build(body, os.environ.get("PM", ""), os.environ.get("KIND", ""), os.environ.get("LEAD", "")))


if __name__ == "__main__":
    main()
