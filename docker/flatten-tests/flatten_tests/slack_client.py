"""Slack notification client."""

from __future__ import annotations

import logging

import httpx

from .models import Config

logger = logging.getLogger(__name__)

# Notification colors by status
COLOR_INFO = "#0088cc"    # blue  — detection / start
COLOR_SUCCESS = "#36a64f" # green — session completed successfully
COLOR_WARNING = "#e8a838" # yellow — timeout
COLOR_DANGER = "#e01e5a"  # red   — error / workflow failure


def _post(webhook_url: str, payload: dict) -> None:  # type: ignore[type-arg]
    response = httpx.post(webhook_url, json=payload, timeout=10)
    response.raise_for_status()


def _build_payload(
    fallback_text: str,
    color: str,
    mrkdwn_text: str,
) -> dict:  # type: ignore[type-arg]
    """Build a Slack payload with a colored attachment."""
    return {
        "text": fallback_text,
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": mrkdwn_text}}
                ],
            }
        ],
    }


def notify_detection(
    config: Config,
    matched_files: list[str],
    session_url: str | None = None,
) -> None:
    """Send Slack notification when describe blocks are detected."""
    files_display = "\n".join(f"• {f}" for f in matched_files)
    commit_url = f"{config.github_server_url}/{config.github_repository}/commit/{config.github_sha}"
    run_url = f"{config.github_server_url}/{config.github_repository}/actions/runs/{config.github_run_id}"

    links = f"<{commit_url}|コミットを見る>"
    if session_url:
        links += f" | <{session_url}|Devin セッションを見る>"

    text = (
        f":mag: *describe ブロック検出 → Devin によるフラット化を開始します*\n\n"
        f"*Run ID:* <{run_url}|{config.github_run_id}>\n"
        f"*Push したユーザー:* {config.github_actor}\n"
        f"*対象ファイル:*\n{files_display}\n\n"
        f"{links}"
    )

    payload = _build_payload(
        fallback_text=":mag: describe ブロック検出 → Devin によるフラット化を開始します",
        color=COLOR_INFO,
        mrkdwn_text=text,
    )

    if config.dry_run:
        logger.info("[DRY RUN] Would send detection Slack notification: %s", payload)
        return

    _post(config.slack_webhook_url, payload)
    logger.info("Detection notification sent.")


def notify_failure(
    config: Config,
    error: str,
) -> None:
    """Send Slack notification when the workflow itself fails."""
    run_url = f"{config.github_server_url}/{config.github_repository}/actions/runs/{config.github_run_id}"

    text = (
        f":rotating_light: *flatten-tests ワークフロー失敗*\n\n"
        f"*Run ID:* <{run_url}|{config.github_run_id}>\n"
        f"*エラー:* `{error}`"
    )

    payload = _build_payload(
        fallback_text=":rotating_light: flatten-tests ワークフロー失敗",
        color=COLOR_DANGER,
        mrkdwn_text=text,
    )

    if config.dry_run:
        logger.info("[DRY RUN] Would send failure Slack notification: %s", payload)
        return

    _post(config.slack_webhook_url, payload)
    logger.info("Failure notification sent.")


def notify_completion(
    config: Config,
    session_url: str,
    status: str,
    pull_request_urls: list[str] | None = None,
) -> None:
    """Send Slack notification when a Devin session completes."""
    run_url = f"{config.github_server_url}/{config.github_repository}/actions/runs/{config.github_run_id}"

    if status == "exit":
        emoji = ":white_check_mark:"
        result_text = "成功 — PR が作成されました"
        color = COLOR_SUCCESS
    elif status == "timeout":
        emoji = ":warning:"
        result_text = f"タイムアウト（{config.max_wait}秒以内に完了しませんでした）"
        color = COLOR_WARNING
    else:
        emoji = ":x:"
        result_text = f"失敗 (status: {status})"
        color = COLOR_DANGER

    pr_links = ""
    if pull_request_urls:
        pr_lines = "\n".join(f"• <{url}|{url}>" for url in pull_request_urls)
        pr_links = f"\n*作成された PR:*\n{pr_lines}\n"

    text = (
        f"{emoji} *Devin フラット化セッション完了*\n\n"
        f"*Run ID:* <{run_url}|{config.github_run_id}>\n"
        f"*結果:* {result_text}\n"
        f"{pr_links}\n"
        f"<{session_url}|Devin セッションを見る>"
    )

    payload = _build_payload(
        fallback_text=f"{emoji} Devin フラット化セッション完了",
        color=color,
        mrkdwn_text=text,
    )

    if config.dry_run:
        logger.info("[DRY RUN] Would send completion Slack notification: %s", payload)
        return

    _post(config.slack_webhook_url, payload)
    logger.info("Completion notification sent (%s).", result_text)
