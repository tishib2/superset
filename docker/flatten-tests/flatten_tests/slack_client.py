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

    links = f"<{commit_url}|View commit>"
    if session_url:
        links += f" | <{session_url}|View Devin session>"

    text = (
        f":mag: *describe blocks detected — starting Devin flatten*\n\n"
        f"*Run ID:* <{run_url}|{config.github_run_id}>\n"
        f"*Pushed by:* {config.github_actor}\n"
        f"*Target files:*\n{files_display}\n\n"
        f"{links}"
    )

    payload = _build_payload(
        fallback_text=":mag: describe blocks detected — starting Devin flatten",
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
    session_url: str | None = None,
) -> None:
    """Send Slack notification when the workflow itself fails."""
    run_url = f"{config.github_server_url}/{config.github_repository}/actions/runs/{config.github_run_id}"

    session_line = f"\n<{session_url}|View Devin session>" if session_url else ""
    text = (
        f":rotating_light: *flatten-tests workflow failed*\n\n"
        f"*Run ID:* <{run_url}|{config.github_run_id}>\n"
        f"*Error:* `{error}`"
        f"{session_line}"
    )

    payload = _build_payload(
        fallback_text=":rotating_light: flatten-tests workflow failed",
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
        result_text = "Success — PR created"
        color = COLOR_SUCCESS
    elif status == "timeout":
        emoji = ":warning:"
        result_text = f"Timed out (did not complete within {config.max_wait}s)"
        color = COLOR_WARNING
    else:
        emoji = ":x:"
        result_text = f"Failed (status: {status})"
        color = COLOR_DANGER

    pr_links = ""
    if pull_request_urls:
        pr_lines = "\n".join(f"• <{url}|{url}>" for url in pull_request_urls)
        pr_links = f"\n*Pull request(s) created:*\n{pr_lines}\n"

    text = (
        f"{emoji} *Devin flatten session completed*\n\n"
        f"*Run ID:* <{run_url}|{config.github_run_id}>\n"
        f"*Result:* {result_text}\n"
        f"{pr_links}\n"
        f"<{session_url}|View Devin session>"
    )

    payload = _build_payload(
        fallback_text=f"{emoji} Devin flatten session completed",
        color=color,
        mrkdwn_text=text,
    )

    if config.dry_run:
        logger.info("[DRY RUN] Would send completion Slack notification: %s", payload)
        return

    _post(config.slack_webhook_url, payload)
    logger.info("Completion notification sent (%s).", result_text)
