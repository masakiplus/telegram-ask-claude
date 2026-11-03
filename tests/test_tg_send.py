"""ネットにも Telegram にも出ないテスト。tg_send.sh はローカルの偽 Telegram サーバーに送る。

  python3 tests/test_tg_send.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
import claude_button_url as cb  # noqa: E402

SCRIPT = os.path.join(ROOT, "tg_send.sh")


# ---- claude_button_url.py

def q_of(u):
    assert u.startswith(cb.BASE)
    return urllib.parse.unquote(u[len(cb.BASE):])


def test_classify():
    assert cb.classify("⚠️ バックアップが失敗しました") == "alert"
    assert cb.classify("job timeout after 30s") == "alert"
    assert cb.classify("STATUS: NG") == "alert"
    assert cb.classify("今週の支出は先週より 3% 少ない") == "report"
    assert cb.classify("PNG を保存した") == "report"   # NG を単語の一部では拾わない
    assert cb.classify("Failover を切り替えた。負荷は落ち着いた") == "report"
    assert cb.classify("サーバーが落ちた") == "alert" and cb.classify("3 tests failed") == "alert"


def test_lead_and_body():
    q = q_of(cb.build("⚠️ disk full"))
    assert q.startswith(cb.LEADS["alert"]) and q.endswith("⚠️ disk full")
    q = q_of(cb.build("週報です", lead="これを要約して"))
    assert q == "これを要約して\n\n週報です"


def test_plus_and_percent_become_fullwidth():
    q = q_of(cb.build("a+b 50%"))
    assert "a＋b 50％" in q and "+" not in q and "%" not in q


def test_html_is_stripped():
    q = q_of(cb.build("<b>売上</b> &amp; 費用 &lt;速報&gt;", parse_mode="HTML"))
    assert q.endswith("売上 & 費用 <速報>")


def test_long_body_fits():
    long = "あいうえお、かきくけこ。" * 400
    u = cb.build(long)
    assert len(u) <= cb.MAX_URL
    assert "（本文が長いので途中で切っている）" in q_of(u)


def test_long_lead_still_fits():
    u = cb.build("本文", lead="これを読んで原因を推測して。" * 200)
    assert len(u) <= cb.MAX_URL


# ---- tg_send.sh（偽 Telegram サーバー相手）

class FakeTelegram(BaseHTTPRequestHandler):
    calls = []
    reject_buttons = False

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
        method = self.path.rsplit("/", 1)[-1]
        if "x-www-form-urlencoded" in (self.headers.get("Content-Type") or ""):
            fields = {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}
        else:
            fields = {"raw": body}
        FakeTelegram.calls.append((method, fields))
        has_button = "reply_markup" in fields or "reply_markup" in body
        ok = not (FakeTelegram.reject_buttons and has_button)
        resp = {"ok": ok} if ok else {"ok": False, "description": "Bad Request: wrong HTTP URL"}
        data = json.dumps(resp).encode()
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def run(args, stdin=None, env_extra=None):
    srv = HTTPServer(("127.0.0.1", 0), FakeTelegram)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = {k: v for k, v in os.environ.items() if not k.startswith("TELEGRAM_")}
    env.update({"TELEGRAM_API_BASE": "http://127.0.0.1:%d" % srv.server_port,
                "TELEGRAM_BOT_TOKEN": "123:TEST", "TELEGRAM_CHAT_ID": "42",
                "TG_SEND_ENV": "/nonexistent", "TG_SEND_PYTHON": sys.executable})
    env.update(env_extra or {})
    FakeTelegram.calls = []
    try:
        p = subprocess.run(["bash", SCRIPT] + args, input=stdin, env=env,
                           capture_output=True, text=True, timeout=30)
    finally:
        srv.shutdown()
    return p


def test_send_with_button():
    FakeTelegram.reject_buttons = False
    p = run(["⚠️ nightly backup failed"])
    assert p.returncode == 0, p.stderr
    (method, f), = FakeTelegram.calls
    assert method == "sendMessage" and f["chat_id"] == "42" and f["text"] == "⚠️ nightly backup failed"
    button = json.loads(f["reply_markup"])["inline_keyboard"][0][0]
    assert button["text"] == "🤖 Claudeに投げる" and button["url"].startswith(cb.BASE)


def test_retry_without_button_when_rejected():
    FakeTelegram.reject_buttons = True
    p = run(["本文"])
    FakeTelegram.reject_buttons = False
    assert p.returncode == 0, p.stderr
    assert [m for m, _ in FakeTelegram.calls] == ["sendMessage", "sendMessage"]
    assert "reply_markup" in FakeTelegram.calls[0][1] and "reply_markup" not in FakeTelegram.calls[1][1]


def test_stdin_html_no_claude():
    p = run(["--stdin", "--html", "--no-claude"], stdin="<b>週報</b>\n二行目")
    assert p.returncode == 0, p.stderr
    (_, f), = FakeTelegram.calls
    assert f["parse_mode"] == "HTML" and f["text"] == "<b>週報</b>\n二行目" and "reply_markup" not in f


def test_long_text_is_truncated_by_characters():
    p = run(["あ" * 5000], env_extra={"LANG": "C", "LC_ALL": "C"})
    assert p.returncode == 0, p.stderr
    (_, f), = FakeTelegram.calls
    assert f["text"] == "あ" * 3900 + "…(truncated)"


def test_document_caption():
    with tempfile.NamedTemporaryFile(suffix=".txt") as t:
        t.write(b"hello"); t.flush()
        p = run(["--document", t.name, "レポートを添付"])
    assert p.returncode == 0, p.stderr
    (method, f), = FakeTelegram.calls
    assert method == "sendDocument" and "レポートを添付" in f["raw"] and "reply_markup" in f["raw"]


def test_missing_config_exits_2():
    p = run(["本文"], env_extra={"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""})
    assert p.returncode == 2 and FakeTelegram.calls == []


def test_unknown_flag_exits_2():
    assert run(["--nope", "x"]).returncode == 2


def test_missing_flag_value_exits_2():
    p = run(["本文", "--chat-id"])   # 本文の後ろのフラグは解析されない（本文として扱う前に止まる）
    assert p.returncode == 0
    p = run(["--chat-id"])
    assert p.returncode == 2 and "needs a value" in p.stderr


def test_token_not_in_request_path_log():
    p = run(["本文"])
    assert p.returncode == 0 and "123:TEST" not in p.stdout + p.stderr


def test_long_html_is_sent_as_plain_text():
    p = run(["--html", "--no-claude", "<b>見出し</b>" + "あ&amp;" * 3000])
    assert p.returncode == 0, p.stderr
    (_, f), = FakeTelegram.calls
    assert "parse_mode" not in f and f["text"].startswith("見出しあ&あ&") and f["text"].endswith("…(truncated)")


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
            n += 1
    print("%d tests passed" % n)
