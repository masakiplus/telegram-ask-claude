#!/bin/bash
# tg_send.sh — 自動化の通知を Telegram に送り、「🤖 Claudeに投げる」ボタンを付ける
#
# 使い方（オプションは本文より前に置く）:
#   bash tg_send.sh "本文"
#   echo "本文" | bash tg_send.sh --stdin
#   bash tg_send.sh --html "<b>見出し</b>本文"
#   bash tg_send.sh --claude-prompt "このログを読んで原因を推測して" "本文"   # 前置きの依頼文を差し替える
#   bash tg_send.sh --no-claude "本文"                                       # ボタンを付けない
#   bash tg_send.sh --document report.pdf "本文"                              # ファイルを添付（本文は caption）
#   bash tg_send.sh --dry-run "本文"                                          # 送らずに送信内容を JSON で表示
#
# ボタンを押すと claude.ai/new?q=… が開き、前置きの依頼文と通知の本文が入力欄に入った新規チャットになる
# （送信はしない）。前置きは本文の中身で分かれる。障害っぽい語（⚠️ 失敗 エラー timeout など）があれば
# 「原因と対処を教えて」、無ければ「この定期レポートについて相談したい」。
#
# 設定（優先順）: 引数 --token / --chat-id > 環境変数 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
#   > $TG_SEND_ENV（既定 ~/.config/telegram-ask-claude/.env）の同名の行
#
# 終了コード: 0 送信成功 / 1 Telegram API エラー / 2 引数・設定の誤り

set -u

# ${#MESSAGE} と ${MESSAGE:0:N} はロケール依存。cron や launchd の LANG=C ではバイト単位で数えてしまい、
# 日本語の途中で切れて Telegram が "text must be encoded in UTF-8" を返す。文字単位で数えさせる
if locale -a 2>/dev/null | grep -Eqi '^c\.utf-?8$'; then
  export LC_ALL=C.UTF-8
else
  export LC_ALL=en_US.UTF-8
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${TG_SEND_PYTHON:-python3}"
ENV_FILE="${TG_SEND_ENV:-$HOME/.config/telegram-ask-claude/.env}"
API="${TELEGRAM_API_BASE:-https://api.telegram.org}"

PARSE_MODE=""
CHAT_ID_ARG=""
TOKEN_ARG=""
USE_STDIN=0
SILENT=0
DRY_RUN=0
CLAUDE_BUTTON=1
CLAUDE_LEAD=""
DOCS=()

need_value() { [ "$1" -ge 2 ] || { echo "[tg_send] $2 needs a value" >&2; exit 2; }; }

while [ $# -gt 0 ]; do
  case "$1" in
    --chat-id|--token|--document|--claude-prompt) need_value $# "$1" ;;
  esac
  case "$1" in
    --html) PARSE_MODE="HTML"; shift ;;
    --chat-id) CHAT_ID_ARG="$2"; shift 2 ;;
    --token) TOKEN_ARG="$2"; shift 2 ;;
    --stdin) USE_STDIN=1; shift ;;
    --silent) SILENT=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --document) DOCS+=("$2"); shift 2 ;;
    --claude-prompt) CLAUDE_LEAD="$2"; shift 2 ;;
    --no-claude) CLAUDE_BUTTON=0; shift ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --) shift; break ;;
    -*) echo "[tg_send] unknown flag: $1" >&2; exit 2 ;;
    *) break ;;
  esac
done

N_DOC=${#DOCS[@]}
i=0
while [ "$i" -lt "$N_DOC" ]; do
  [ -f "${DOCS[$i]}" ] || { echo "[tg_send] document not found: ${DOCS[$i]}" >&2; exit 2; }
  i=$((i + 1))
done

if [ "$USE_STDIN" -eq 1 ]; then MESSAGE="$(cat)"; else MESSAGE="${1:-}"; fi
if [ -z "$MESSAGE" ] && [ "$N_DOC" -eq 0 ]; then
  echo "[tg_send] empty message" >&2
  exit 2
fi

# .env から特定のキーだけを読む（source しないので、シェルとして読めない行があっても落ちない）
read_env_key() {
  [ -f "$1" ] || return 0
  awk -v K="$2" '$0 ~ "^"K"=" { sub("^"K"=", ""); gsub(/^["\047]|["\047]$/, ""); print; exit }' "$1"
}

BOT_TOKEN="${TOKEN_ARG:-${TELEGRAM_BOT_TOKEN:-}}"
CHAT_ID="${CHAT_ID_ARG:-${TELEGRAM_CHAT_ID:-}}"
[ -n "$BOT_TOKEN" ] || BOT_TOKEN="$(read_env_key "$ENV_FILE" TELEGRAM_BOT_TOKEN)"
[ -n "$CHAT_ID" ] || CHAT_ID="$(read_env_key "$ENV_FILE" TELEGRAM_CHAT_ID)"
if [ "$DRY_RUN" -eq 0 ] && { [ -z "$BOT_TOKEN" ] || [ -z "$CHAT_ID" ]; }; then
  echo "[tg_send] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set (env or $ENV_FILE)" >&2
  exit 2
fi

# Telegram の本文は 4096 字まで。余裕を見て 3900 で切る。ボタンには切る前の全文を渡す
FULL_MESSAGE="$MESSAGE"
MAX=3900
if [ "${#MESSAGE}" -gt "$MAX" ]; then
  if [ "$PARSE_MODE" = "HTML" ]; then
    MESSAGE="$(MSG="$MESSAGE" "$PY" -c 'import html, os, re, sys
sys.stdout.write(html.unescape(re.sub(r"<[^>]+>", "", os.environ["MSG"])))')"
    PARSE_MODE=""
  fi
  [ "${#MESSAGE}" -gt "$MAX" ] && MESSAGE="${MESSAGE:0:$MAX}…(truncated)"
fi

BUTTON_URL=""
if [ "$CLAUDE_BUTTON" -eq 1 ] && [ -n "$FULL_MESSAGE" ]; then
  BUTTON_URL="$(MSG="$FULL_MESSAGE" PM="$PARSE_MODE" LEAD="$CLAUDE_LEAD" "$PY" "$HERE/claude_button_url.py")"
  # URL が作れなくても通知は送る。黙って落とさず stderr に残す
  [ -n "$BUTTON_URL" ] || echo "[tg_send] WARN: button URL is empty; sending without button" >&2
fi

markup() {
  [ -n "$BUTTON_URL" ] || return 0
  URL="$BUTTON_URL" "$PY" -c 'import json, os
print(json.dumps({"inline_keyboard": [[{"text": "🤖 Claudeに投げる", "url": os.environ["URL"]}]]}, ensure_ascii=False))'
}

if [ "$DRY_RUN" -eq 1 ]; then
  CHAT="$CHAT_ID" TEXT="$MESSAGE" PM="$PARSE_MODE" MARKUP="$(markup)" DOC_N="$N_DOC" "$PY" -c 'import json, os
m = os.environ["MARKUP"]
print(json.dumps({"chat_id": os.environ["CHAT"], "text": os.environ["TEXT"],
                  "parse_mode": os.environ["PM"] or None, "documents": int(os.environ["DOC_N"]),
                  "reply_markup": json.loads(m) if m else None}, ensure_ascii=False, indent=1))'
  exit 0
fi


is_ok() {
  printf '%s' "$1" | "$PY" -c "import sys, json; print('1' if json.loads(sys.stdin.read() or '{}').get('ok') else '0')" 2>/dev/null || echo 0
}

# 応答が空（通信の瞬断）のときだけ、5秒・20秒あけて最大2回やり直す。
# Telegram が ok:false を返したとき（中身の誤り）はやり直さない。
# トークン入りの URL は引数に載せず（ps で見えるため）、curl の設定として標準入力から渡す。
curl_retry() {  # $1 = API のメソッド名、残りは curl の引数
  local method="$1" resp="" rc=0 wait
  shift
  for wait in 0 5 20; do
    [ "$wait" -gt 0 ] && sleep "$wait"
    resp=$(printf 'url = "%s/bot%s/%s"\n' "$API" "$BOT_TOKEN" "$method" | curl -K - "$@"); rc=$?
    [ -n "$resp" ] && break
    echo "[tg_send] empty response (curl rc=${rc}); retrying" >&2
  done
  printf '%s' "$resp"
  return "$rc"
}

send_text() {
  local args=(-s -X POST --max-time 30
    --data-urlencode "chat_id=${CHAT_ID}"
    --data-urlencode "text=${MESSAGE}"
    --data-urlencode "disable_web_page_preview=true")
  [ -n "$PARSE_MODE" ] && args+=(--data-urlencode "parse_mode=${PARSE_MODE}")
  [ -n "$BUTTON_URL" ] && args+=(--data-urlencode "reply_markup=$(markup)")
  curl_retry sendMessage "${args[@]}"
}

send_doc() {  # $1 = ファイル, $2 = caption
  local args=(-s -X POST --max-time 120
    -F "chat_id=${CHAT_ID}" -F "document=@$1")
  [ -n "$2" ] && args+=(-F "caption=$2")
  [ -n "$2" ] && [ -n "$PARSE_MODE" ] && args+=(-F "parse_mode=${PARSE_MODE}")
  [ -n "$BUTTON_URL" ] && args+=(-F "reply_markup=$(markup)")
  curl_retry sendDocument "${args[@]}"
}

# caption は 1024 字まで。長い本文や添付なしは先に本文だけを送る
CAPTION="$MESSAGE"
if [ "$N_DOC" -eq 0 ] || [ "${#MESSAGE}" -gt 1024 ]; then
  RESP=$(send_text)
  # ボタン付きで失敗したら（URL が長すぎる等）ボタンなしで1回だけ送り直す。通知の到達をボタンの成否に縛らない
  if [ "$(is_ok "$RESP")" != "1" ] && [ -n "$BUTTON_URL" ]; then
    echo "[tg_send] send with button failed (${RESP:-<empty>}); retrying without button" >&2
    BUTTON_URL=""
    RESP=$(send_text)
  fi
  [ "$(is_ok "$RESP")" = "1" ] || { echo "[tg_send] FAILED: ${RESP:-<empty>}" >&2; exit 1; }
  CAPTION=""
  BUTTON_URL=""   # ボタンは1通目にだけ付ける
fi

i=0
while [ "$i" -lt "$N_DOC" ]; do
  RESP=$(send_doc "${DOCS[$i]}" "$CAPTION")
  if [ "$(is_ok "$RESP")" != "1" ] && [ -n "$BUTTON_URL" ]; then
    echo "[tg_send] send with button failed (${RESP:-<empty>}); retrying without button" >&2
    BUTTON_URL=""
    RESP=$(send_doc "${DOCS[$i]}" "$CAPTION")
  fi
  [ "$(is_ok "$RESP")" = "1" ] || { echo "[tg_send] FAILED: ${RESP:-<empty>}" >&2; exit 1; }
  CAPTION=""; BUTTON_URL=""
  i=$((i + 1))
done

[ "$SILENT" -eq 1 ] || echo "[tg_send] sent (${#MESSAGE} chars, ${N_DOC} document(s))"
exit 0
