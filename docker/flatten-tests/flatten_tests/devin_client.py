"""Devin API client."""

from __future__ import annotations

import logging
import time

import httpx

from .models import Config, DevinSessionResponse

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_BASE_INTERVAL = 5  # seconds; actual wait = RETRY_BASE_INTERVAL * 2^(attempt-1)
RETRY_MAX_INTERVAL = 60  # cap to avoid excessively long waits


def build_prompt(
    repo_url: str,
    files: list[str],
    test_command: str,
    pr_branch_prefix: str,
    timestamp: str,
) -> str:
    files_list = "\n".join(files)
    return f"""\
リポジトリ: {repo_url}

以下のテストファイルで describe() ブロックを Jest の推奨スタイルに従いフラット化してください。

対象ファイル:
{files_list}

ルール:
- describe('A', () => {{ test('B', ...) }}) → test('A > B', ...) に変換する
- ネストが深い場合は > で連結する（例: test('A > B > C', ...)）
- テストのロジック・アサーションは一切変更しない
- eslint-disable-next-line no-restricted-globals のコメント行を削除する
- 変換後に以下のコマンドで全テストがパスすることを確認する:
  {test_command}=<対象ファイル名>
- 全テストがパスしたら {pr_branch_prefix}/{timestamp} ブランチで PR を作成する
- PR のコミットメッセージには必ず [skip ci] を含める（CI を一時的にスキップするため）
- PR を作成したらタスクは完了。それ以上の作業は行わずセッションを終了すること\
"""


def launch_session(config: Config, prompt: str) -> DevinSessionResponse:
    """Launch a Devin session with retries. Raises RuntimeError on failure."""
    url = f"{config.devin_api_base}/organizations/{config.devin_org_id}/sessions"
    headers = {
        "Authorization": f"Bearer {config.devin_api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Launching Devin session... (attempt %d/%d)", attempt, MAX_RETRIES)
        try:
            response = httpx.post(url, headers=headers, json={"prompt": prompt}, timeout=30)
            logger.info("Devin API response: HTTP %d", response.status_code)
            response.raise_for_status()
            session = DevinSessionResponse.model_validate(response.json())
            logger.info("Session launched: session_id=%s url=%s", session.session_id, session.url)
            return session
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            body = e.response.text[:300]
            if status == 429:
                logger.warning("Rate limited by Devin API (HTTP 429): %s", body)
            elif status >= 500:
                logger.warning("Devin API server error (HTTP %d): %s", status, body)
            else:
                logger.error("Devin API client error (HTTP %d): %s — not retrying", status, body)
                raise
            if attempt < MAX_RETRIES:
                wait = min(RETRY_BASE_INTERVAL * (2 ** (attempt - 1)), RETRY_MAX_INTERVAL)
                logger.info("Retrying in %ds...", wait)
                time.sleep(wait)
        except httpx.RequestError as e:
            logger.warning("Network error calling Devin API: %s", e)
            if attempt < MAX_RETRIES:
                wait = min(RETRY_BASE_INTERVAL * (2 ** (attempt - 1)), RETRY_MAX_INTERVAL)
                logger.info("Retrying in %ds...", wait)
                time.sleep(wait)

    raise RuntimeError(f"Failed to launch Devin session after {MAX_RETRIES} attempts.")


def get_session(config: Config, session_id: str) -> DevinSessionResponse:
    """Fetch the current state of a Devin session."""
    url = f"{config.devin_api_base}/organizations/{config.devin_org_id}/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {config.devin_api_key}"}
    response = httpx.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("pull_requests"):
        logger.info("Raw pull_requests from API: %s", data["pull_requests"])
    return DevinSessionResponse.model_validate(data)


def terminate_session(config: Config, session_id: str) -> None:
    """Terminate a Devin session."""
    url = f"{config.devin_api_base}/organizations/{config.devin_org_id}/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {config.devin_api_key}"}
    try:
        response = httpx.delete(url, headers=headers, timeout=30)
        response.raise_for_status()
        logger.info("Session terminated.")
    except httpx.HTTPStatusError as e:
        logger.warning("Failed to terminate session %s: %s", session_id, e)


TERMINAL_STATUSES = {"exit", "error", "suspended"}


def poll_until_done(config: Config, session_id: str) -> DevinSessionResponse:
    """Poll session status until done, PR created, or timeout. Returns final session state."""
    logger.info("Polling session %s (max %ds, interval %ds)...", session_id, config.max_wait, config.poll_interval)
    elapsed = 0
    poll_count = 0
    last_heartbeat = 0
    heartbeat_interval = 60  # emit a heartbeat log every 60 seconds

    while elapsed < config.max_wait:
        time.sleep(config.poll_interval)
        elapsed += config.poll_interval
        poll_count += 1

        if elapsed - last_heartbeat >= heartbeat_interval:
            logger.info("HEARTBEAT [session_id=%s]: still polling, elapsed=%ds/%ds", session_id, elapsed, config.max_wait)
            last_heartbeat = elapsed

        session = get_session(config, session_id)
        pr_count = len(session.pull_requests)
        logger.info(
            "Poll #%d [session_id=%s]: status=%s prs=%d elapsed=%ds",
            poll_count,
            session_id,
            session.status,
            pr_count,
            elapsed,
        )
        if pr_count > 0:
            pr_urls = [pr.pr_url for pr in session.pull_requests if pr.pr_url]
            logger.info("PR(s) detected [session_id=%s]: %s", session_id, pr_urls)

        if session.status in TERMINAL_STATUSES:
            logger.info("Terminal status reached [session_id=%s]: %s", session_id, session.status)
            return session

        if pr_count > 0:
            logger.info("PR created, terminating session [session_id=%s]", session_id)
            terminate_session(config, session_id)
            return DevinSessionResponse(
                session_id=session.session_id,
                url=session.url,
                status="exit",
                pull_requests=session.pull_requests,
            )

    logger.warning("Timeout reached [session_id=%s]: terminating session.", session_id)
    terminate_session(config, session_id)
    return DevinSessionResponse(
        session_id=session_id,
        url=f"https://app.devin.ai/sessions/{session_id}",
        status="timeout",
    )
