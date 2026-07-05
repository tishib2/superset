#!/usr/bin/env bash
# entrypoint.sh
# describe ブロックを検知して Devin API を呼び出し、Slack に通知する。
# GitHub Actions と Docker 両方から呼び出される共通ロジック。
#
# 必須環境変数:
#   DEVIN_API_KEY       Devin API キー（cog_ prefix）
#   DEVIN_ORG_ID        Devin Organization ID（org- prefix）
#   SLACK_WEBHOOK_URL   Slack Incoming Webhook URL
#   GITHUB_ACTOR        push したユーザー名（GitHub Actions では自動設定）
#   GITHUB_SERVER_URL   GitHub サーバー URL（デフォルト: https://github.com）
#   GITHUB_REPOSITORY   リポジトリ名（例: tishib/superset）
#   GITHUB_SHA          コミット SHA
#
# オプション環境変数:
#   TARGET_FILES        | 区切りで対象ファイルを直接指定（指定時は検知ステップをスキップ）
#   DRY_RUN             1 を指定すると API 呼び出し・Slack 通知をスキップしてログのみ出力

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/repo}"
CONFIG_FILE="$REPO_ROOT/.devin/flatten-tests.json"
DEVIN_API_BASE="https://api.devin.ai/v3"

# ── ユーティリティ ──────────────────────────────────────────────────────────

log()  { echo "[flatten-tests] $*"; }
warn() { echo "[flatten-tests] WARNING: $*" >&2; }
err()  { echo "[flatten-tests] ERROR: $*" >&2; }

# ── 前提チェック ────────────────────────────────────────────────────────────

if [ ! -f "$CONFIG_FILE" ]; then
  log "No flatten-tests.json found, skipping."
  exit 0
fi

for var in DEVIN_API_KEY DEVIN_ORG_ID SLACK_WEBHOOK_URL; do
  if [ -z "${!var:-}" ]; then
    err "$var is not set. Please set it as an environment variable."
    exit 1
  fi
done

GITHUB_ACTOR="${GITHUB_ACTOR:-unknown}"
GITHUB_SERVER_URL="${GITHUB_SERVER_URL:-https://github.com}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-}"
GITHUB_SHA="${GITHUB_SHA:-}"
GITHUB_RUN_ID="${GITHUB_RUN_ID:-}"
DRY_RUN="${DRY_RUN:-0}"

# ── 対象ファイルの決定 ───────────────────────────────────────────────────────

if [ -n "${TARGET_FILES:-}" ]; then
  # 直接指定された場合（GitHub Actions からの呼び出し）
  log "Using provided TARGET_FILES."
  MATCHED_FILES=()
  while IFS='|' read -ra parts; do
    for f in "${parts[@]}"; do
      [ -n "$f" ] && MATCHED_FILES+=("$f")
    done
  done <<< "$TARGET_FILES"
else
  # git diff から自動検知（Docker ローカル実行時）
  log "Detecting changed files via git diff..."

  if git -C "$REPO_ROOT" rev-parse HEAD~1 &>/dev/null; then
    CHANGED_FILES="$(git -C "$REPO_ROOT" diff --name-only HEAD~1 HEAD)"
  else
    CHANGED_FILES="$(git -C "$REPO_ROOT" diff --name-only "$(git hash-object -t tree /dev/null)" HEAD)"
  fi

  TARGETS="$(jq -r '.targets[]' "$CONFIG_FILE")"
  MATCHED_FILES=()

  while IFS= read -r changed; do
    [[ ! "$changed" =~ \.(test|spec)\.(ts|tsx)$ ]] && continue
    while IFS= read -r target; do
      if [[ "$changed" == *"$target"* ]]; then
        if grep -q 'describe(' "$REPO_ROOT/$changed" 2>/dev/null; then
          MATCHED_FILES+=("$changed")
          break
        fi
      fi
    done <<< "$TARGETS"
  done <<< "$CHANGED_FILES"
fi

if [ ${#MATCHED_FILES[@]} -eq 0 ]; then
  log "No describe blocks found in target files, skipping."
  exit 0
fi

log "Files with describe blocks detected:"
for f in "${MATCHED_FILES[@]}"; do
  log "  - $f"
done

# ── Devin API セッション起動 ─────────────────────────────────────────────────

TEST_COMMAND="$(jq -r '.test_command' "$CONFIG_FILE")"
PR_BRANCH_PREFIX="$(jq -r '.pr_branch_prefix' "$CONFIG_FILE")"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
FILES_LIST="$(printf '%s\n' "${MATCHED_FILES[@]}")"

PROMPT="以下のテストファイルで describe() ブロックを Jest の推奨スタイルに従いフラット化してください。

対象ファイル:
$FILES_LIST

ルール:
- describe('A', () => { test('B', ...) }) → test('A > B', ...) に変換する
- ネストが深い場合は > で連結する（例: test('A > B > C', ...)）
- テストのロジック・アサーションは一切変更しない
- eslint-disable-next-line no-restricted-globals のコメント行を削除する
- 変換後に以下のコマンドで全テストがパスすることを確認する:
  $TEST_COMMAND=<対象ファイル名>
- 全テストがパスしたら ${PR_BRANCH_PREFIX}/${TIMESTAMP} ブランチで PR を作成する
- PR のコミットメッセージには必ず [skip ci] を含める（CI を一時的にスキップするため）
- PR を作成したらタスクは完了。それ以上の作業は行わずセッションを終了すること"

SESSION_ID=""
if [ "$DRY_RUN" = "1" ]; then
  log "[DRY RUN] Would launch Devin session with prompt:"
  echo "$PROMPT"
  SESSION_ID="dry-run-session-id"
else
  for attempt in 1 2 3; do
    log "Launching Devin session... (attempt $attempt/3)"
    REPO_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}"
    RESPONSE="$(curl -sf \
      -X POST \
      -H "Authorization: Bearer $DEVIN_API_KEY" \
      -H "Content-Type: application/json" \
      -d "$(jq -n --arg prompt "$PROMPT" --arg repo "$REPO_URL" \
        '{"prompt": $prompt, "repos": [$repo], "resumable": false}')" \
      "$DEVIN_API_BASE/organizations/$DEVIN_ORG_ID/sessions" || echo "")"

    SESSION_ID="$(echo "$RESPONSE" | jq -r '.session_id // empty' 2>/dev/null || echo "")"
    [ -n "$SESSION_ID" ] && break

    if [ "$attempt" -lt 3 ]; then
      warn "API call failed, retrying in 5 seconds..."
      sleep 5
    fi
  done

  if [ -z "$SESSION_ID" ]; then
    err "Failed to launch Devin session after 3 attempts."
    exit 1
  fi
fi

SESSION_URL="https://app.devin.ai/sessions/$SESSION_ID"
log "Devin session launched: $SESSION_URL"

# ── 起動通知（ローカル Docker 実行時のみ・CI では検知直後に送信済み）────────

SKIP_LAUNCH_NOTIFICATION="${SKIP_LAUNCH_NOTIFICATION:-0}"
COMMIT_URL="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/commit/$GITHUB_SHA"
FILES_DISPLAY="$(printf '%s\n' "${MATCHED_FILES[@]}" | sed 's/^/• /')"

if [ "$SKIP_LAUNCH_NOTIFICATION" != "1" ]; then
  PAYLOAD="$(jq -n \
    --arg pusher "$GITHUB_ACTOR" \
    --arg files "$FILES_DISPLAY" \
    --arg commit_url "$COMMIT_URL" \
    --arg session_url "$SESSION_URL" \
    '{
      "text": ":mag: describe ブロック検出 → Devin によるフラット化を開始します",
      "blocks": [
        {
          "type": "section",
          "text": {
            "type": "mrkdwn",
            "text": ":mag: *describe ブロック検出 → Devin によるフラット化を開始します*\n\n*Push したユーザー:* \($pusher)\n*対象ファイル:*\n\($files)\n\n<\($commit_url)|コミットを見る> | <\($session_url)|Devin セッションを見る>"
          }
        }
      ]
    }')"

  if [ "$DRY_RUN" = "1" ]; then
    log "[DRY RUN] Would send launch Slack notification:"
    echo "$PAYLOAD" | jq .
  else
    curl -sf -X POST \
      -H "Content-Type: application/json" \
      -d "$PAYLOAD" \
      "$SLACK_WEBHOOK_URL"
    log "Launch notification sent."
  fi
fi

# ── Devin セッション完了待ち（ポーリング）────────────────────────────────────

MAX_WAIT=1200  # 最大20分
INTERVAL=30    # 30秒ごとにポーリング
elapsed=0
FINAL_STATUS=""

log "Waiting for Devin session to complete (max ${MAX_WAIT}s)..."

if [ "$DRY_RUN" = "1" ]; then
  log "[DRY RUN] Skipping polling."
  FINAL_STATUS="exit"
else
  while [ "$elapsed" -lt "$MAX_WAIT" ]; do
    sleep "$INTERVAL"
    elapsed=$((elapsed + INTERVAL))

    SESSION_DATA="$(curl -sf \
      -H "Authorization: Bearer $DEVIN_API_KEY" \
      "$DEVIN_API_BASE/organizations/$DEVIN_ORG_ID/sessions/$SESSION_ID" || echo "")"

    FINAL_STATUS="$(echo "$SESSION_DATA" | jq -r '.status // empty' 2>/dev/null || echo "")"
    log "Session status: ${FINAL_STATUS:-unknown} (${elapsed}s elapsed)"

    if [[ "$FINAL_STATUS" == "exit" || "$FINAL_STATUS" == "error" || "$FINAL_STATUS" == "suspended" ]]; then
      break
    fi
  done
fi

# ── 完了通知（Slack）────────────────────────────────────────────────────────

if [ -z "$FINAL_STATUS" ] || [[ "$FINAL_STATUS" != "exit" && "$FINAL_STATUS" != "error" && "$FINAL_STATUS" != "suspended" ]]; then
  # タイムアウト → セッションを終了させる
  RESULT_EMOJI=":warning:"
  RESULT_TEXT="タイムアウト（${MAX_WAIT}秒以内に完了しませんでした）"
  if [ "$DRY_RUN" != "1" ]; then
    log "Terminating Devin session due to timeout..."
    curl -sf -X DELETE \
      -H "Authorization: Bearer $DEVIN_API_KEY" \
      "$DEVIN_API_BASE/organizations/$DEVIN_ORG_ID/sessions/$SESSION_ID" \
      > /dev/null || warn "Failed to terminate session $SESSION_ID"
    log "Session terminated."
  fi
elif [ "$FINAL_STATUS" = "exit" ]; then
  RESULT_EMOJI=":white_check_mark:"
  RESULT_TEXT="成功 — PR が作成されました"
else
  RESULT_EMOJI=":x:"
  RESULT_TEXT="失敗 (status: ${FINAL_STATUS})"
fi

RUN_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
RESULT_PAYLOAD="$(jq -n \
  --arg emoji "$RESULT_EMOJI" \
  --arg result "$RESULT_TEXT" \
  --arg session_url "$SESSION_URL" \
  --arg run_url "$RUN_URL" \
  --arg run_id "$GITHUB_RUN_ID" \
  '{
    "text": "\($emoji) Devin フラット化セッション完了",
    "blocks": [
      {
        "type": "section",
        "text": {
          "type": "mrkdwn",
          "text": "\($emoji) *Devin フラット化セッション完了*\n\n*Run ID:* <\($run_url)|\($run_id)>\n*結果:* \($result)\n\n<\($session_url)|Devin セッションを見る>"
        }
      }
    ]
  }')"

if [ "$DRY_RUN" = "1" ]; then
  log "[DRY RUN] Would send completion Slack notification:"
  echo "$RESULT_PAYLOAD" | jq .
else
  curl -sf -X POST \
    -H "Content-Type: application/json" \
    -d "$RESULT_PAYLOAD" \
    "$SLACK_WEBHOOK_URL"
  log "Completion notification sent (${RESULT_TEXT})."
fi
