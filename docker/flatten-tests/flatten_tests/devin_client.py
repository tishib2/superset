"""Devin API client."""

from __future__ import annotations

import logging
import time

import httpx

from .models import Config, DevinSessionResponse

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_INTERVAL = 5


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
            logger.info("API response (HTTP %d): %s", response.status_code, response.text)
            response.raise_for_status()
            return DevinSessionResponse.model_validate(response.json())
        except (httpx.HTTPStatusError, httpx.RequestError, Exception) as e:
            logger.warning("API call failed: %s", e)
            if attempt < MAX_RETRIES:
                logger.info("Retrying in %ds...", RETRY_INTERVAL)
                time.sleep(RETRY_INTERVAL)

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
    logger.info("Waiting for Devin session to complete (max %ds)...", config.max_wait)
    elapsed = 0

    while elapsed < config.max_wait:
        time.sleep(config.poll_interval)
        elapsed += config.poll_interval

        session = get_session(config, session_id)
        pr_count = len(session.pull_requests)
        if pr_count > 0:
            logger.info("Raw pull_requests API data: %s", session.model_dump()["pull_requests"])
        logger.info(
            "Session status: %s, PRs: %d (%ds elapsed)",
            session.status,
            pr_count,
            elapsed,
        )

        if session.status in TERMINAL_STATUSES:
            return session

        if pr_count > 0:
            logger.info("PR created, treating as success. pull_requests: %s", session.pull_requests)
            return DevinSessionResponse(
                session_id=session.session_id,
                url=session.url,
                status="exit",
                pull_requests=session.pull_requests,
            )

    logger.warning("Timeout: terminating session.")
    terminate_session(config, session_id)
    return DevinSessionResponse(
        session_id=session_id,
        url=f"https://app.devin.ai/sessions/{session_id}",
        status="timeout",
    )
