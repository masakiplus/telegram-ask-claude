# telegram-ask-claude — 自動化の通知に「🤖 Claudeに投げる」ボタンを付ける

cron や launchd で回している自動化の通知を Telegram に送り、そのメッセージに「🤖 Claudeに投げる」ボタンを付ける小さな送信スクリプトです。
ボタンを押すと claude.ai の新規チャットが開き、**通知の本文と「原因と対処を教えて」などの依頼文が入力欄に入った状態**になります。スマホで通知を見て、そのまま Claude に相談できます。

A tiny Telegram notifier for your cron jobs. Every message gets an "Ask Claude" button that opens claude.ai with the notification and a request prefilled.

## できること

- **ボタン1つで相談に移れる**。飛び先は `https://claude.ai/new?q=…`。入力欄に入るだけで送信はしないので、読んで直してから送れる
- **依頼文を中身で変える**。本文に障害っぽい語（⚠️ 失敗 エラー timeout FAIL など）があれば「状況を確認し、原因と対処を教えてほしい」、無ければ「この定期レポートについて相談したい。気になる点と次の一手を教えてほしい」。`--claude-prompt` で差し替えられる
- **ボタンのせいで通知を落とさない**。URL が長すぎる等でボタン付きの送信が失敗したら、ボタンなしで1回だけ送り直す。通信の瞬断（空応答）は 5 秒・20 秒あけて2回までやり直す
- **長文でも壊れない**。Telegram の 4096 字とボタン URL の長さ制限に合わせて、文字単位で切る（`LANG=C` の cron でも日本語の途中で切らない）
- **依存が少ない**。bash・curl・python3（標準ライブラリだけ）

## 使い方

1. [@BotFather](https://t.me/BotFather) で bot を作ってトークンを受け取り、その bot に自分から1度話しかけておく
2. chat id を調べる（`https://api.telegram.org/bot<トークン>/getUpdates` の `message.chat.id`）
3. 設定を置く

```bash
git clone https://github.com/masakiplus/telegram-ask-claude.git
cd telegram-ask-claude
mkdir -p ~/.config/telegram-ask-claude
cp .env.example ~/.config/telegram-ask-claude/.env
chmod 600 ~/.config/telegram-ask-claude/.env   # TELEGRAM_BOT_TOKEN と TELEGRAM_CHAT_ID を書く
```

送る:

```bash
bash tg_send.sh "✅ 夜間バックアップ 完了（12.3GB・4分）"
bash tg_send.sh "⚠️ 夜間バックアップ 失敗: rsync exit 23"
some_report_command | bash tg_send.sh --stdin
bash tg_send.sh --html "<b>週次レポート</b>
支出は先週より 3% 少ない"
bash tg_send.sh --claude-prompt "このログから原因を推測して、次に見るべきファイルを教えて" "$(tail -50 job.log)"
bash tg_send.sh --document report.pdf "今月のレポート"
bash tg_send.sh --dry-run "本文"     # 送らずに送信内容（ボタンの URL を含む）を表示
```

cron で失敗したときだけ知らせる例:

```bash
0 3 * * * /path/to/backup.sh >> /tmp/backup.log 2>&1 || bash /path/to/tg_send.sh "⚠️ backup.sh 失敗 $(tail -5 /tmp/backup.log)"
```

## オプション

| オプション | 意味 |
|---|---|
| `--stdin` | 本文を標準入力から読む（複数行の本文はこちらが安全） |
| `--html` | `parse_mode=HTML` で送る。使えるタグは `<b> <i> <u> <s> <a> <code> <pre>`。ボタン側ではタグを剥がす |
| `--claude-prompt "<依頼文>"` | ボタンに入る前置きの依頼文を差し替える |
| `--no-claude` | ボタンを付けない |
| `--document <file>` | ファイルを添付する（複数回指定できる）。本文は最初の添付の caption になる。1024 字を超える本文は先に単独で送る |
| `--chat-id <id>` / `--token <token>` | 設定ファイルや環境変数より優先する |
| `--silent` | 成功時の1行を出さない |
| `--dry-run` | 送らずに、送る内容を JSON で表示する |

オプションは本文より前に置きます（本文の後ろのオプションは本文の一部として扱われず、無視されます）。`-h` / `--help` で使い方を表示します。

終了コードは 0 送信成功・1 Telegram API エラー・2 引数や設定の誤り。

`--html` の本文が長くて切り詰めるときは、タグが途中で切れて送れなくなるのを避けるため、タグを剥がして素の文字で送ります。

## 設定

| 変数 | 既定 | 意味 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | なし | 環境変数で渡すか、下の設定ファイルに書く |
| `TG_SEND_ENV` | `~/.config/telegram-ask-claude/.env` | 設定ファイルの場所。`source` せず、上の2キーの行だけを読む |
| `TG_SEND_PYTHON` | `python3` | 使う python。launchd から呼ぶときは `/usr/bin/python3` などに固定すると安定する |
| `CLAUDE_BUTTON_MAX_URL` | `1900` | ボタン URL の上限。これを超える本文は途中で切ってボタンに載せる |
| `TELEGRAM_API_BASE` | `https://api.telegram.org` | テスト用に偽サーバーへ向けるときだけ変える |

ボタンの URL は `claude_button_url.py` が組み立てます。単体でも使えます。入力は環境変数で、`MSG`（本文。無ければ標準入力）・`PM`（`HTML` ならタグを剥がす）・`KIND`（`alert` / `report`。空なら本文から推定）・`LEAD`（前置きの依頼文）。

```bash
MSG="⚠️ ディスク使用率 95%" python3 claude_button_url.py
```

bot のトークンは curl の引数に載せず、設定として標準入力から渡しているので、同じマシンの `ps` には出ません。

## 仕組みと、ハマったところ

- `claude.ai/new?q=` に渡した文字列は入力欄に入るが、`+` が空白に、`%` が壊れた文字になる。ボタンの中身だけ `＋` `％` に置き換えている
- Telegram のボタン URL は長すぎると、メッセージごと送信が失敗する。日本語は URL エンコードで1字約9バイトになるので、本文の長さを二分探索で詰めて上限に収めている
- `${#MESSAGE}` と `${MESSAGE:0:N}` は bash のロケール依存。`LANG=C` の cron ではバイト単位で数えて日本語の途中で切ってしまい、Telegram が `text must be encoded in UTF-8` を返す。スクリプトの頭で UTF-8 ロケールを強制している
- ボタンの成否と通知の到達を切り離す。ボタン付きで失敗したら、ボタンなしで送り直す
- Telegram の 4096 字は UTF-16 で数える。絵文字が多い本文だと 3900 字で切っても超えることがある

## 広げるなら

- 長い本文は URL に入りきらない。自分の DB やメモに全文を書いて、ボタンにはその ID と「これを読んで対応して」だけを載せると、全文を Claude に渡せる（作者の環境ではそうしている）
- ボタンを自前の短縮 URL 経由にすると、どの通知のボタンが押されたかを数えられる。押されない通知は止めてよい、という判断材料になる

## テスト

```bash
python3 tests/test_tg_send.py   # 偽の Telegram サーバーを立てて送る。ネットには出ない
```

## ライセンス

MIT
