"""Entry point for the flatten-tests automation."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from .devin_client import build_prompt, launch_session, poll_until_done
from .detector import detect_files, get_changed_files
from .models import Config, FlattenTestsConfig
from .slack_client import notify_completion, notify_detection, notify_failure

logging.basicConfig(
    level=logging.INFO,
    format="[flatten-tests] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def load_flatten_config(repo_root: str) -> FlattenTestsConfig | None:
    config_path = Path(repo_root) / ".devin" / "flatten-tests.json"
    if not config_path.exists():
        logger.info("No flatten-tests.json found, skipping.")
        return None
    return FlattenTestsConfig.model_validate(json.loads(config_path.read_text()))


def resolve_matched_files(config: Config, flatten_config: FlattenTestsConfig) -> list[str]:
    """Return files to process, either from TARGET_FILES env or via git diff detection."""
    if config.target_files:
        logger.info("Using provided TARGET_FILES.")
        return [f for f in config.target_files.split("|") if f]

    logger.info("Detecting changed files via git diff...")
    changed = get_changed_files(config.repo_root)
    return detect_files(config.repo_root, flatten_config.targets, changed)


def main() -> None:
    config = Config()  # type: ignore[call-arg]

    try:
        flatten_config = load_flatten_config(config.repo_root)
        if flatten_config is None:
            sys.exit(0)

        matched_files = resolve_matched_files(config, flatten_config)

        if not matched_files:
            logger.info("No describe blocks found in target files, skipping.")
            sys.exit(0)

        logger.info("Files with describe blocks detected:")
        for f in matched_files:
            logger.info("  - %s", f)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        repo_url = f"{config.github_server_url}/{config.github_repository}"

        prompt = build_prompt(
            repo_url=repo_url,
            files=matched_files,
            test_command=flatten_config.test_command,
            pr_branch_prefix=flatten_config.pr_branch_prefix,
            timestamp=timestamp,
        )

        if config.dry_run:
            logger.info("[DRY RUN] Would launch Devin session with prompt:\n%s", prompt)
            if not config.skip_launch_notification:
                notify_detection(config, matched_files)
            notify_completion(config, "https://app.devin.ai/sessions/dry-run", "exit")
            sys.exit(0)

        session = launch_session(config, prompt)
        logger.info("Devin session launched: %s", session.url)

        if not config.skip_launch_notification:
            notify_detection(config, matched_files, session_url=session.url)

        final_session = poll_until_done(config, session.session_id)
        pr_urls = [pr.url for pr in final_session.pull_requests if pr.url]
        notify_completion(config, final_session.url, final_session.status, pull_request_urls=pr_urls or None)

        if final_session.status not in {"exit"}:
            sys.exit(1)

    except Exception as e:
        logger.error("Unexpected error: %s", e)
        try:
            notify_failure(config, str(e))
        except Exception as slack_err:
            logger.error("Failed to send failure notification: %s", slack_err)
        sys.exit(1)


if __name__ == "__main__":
    main()
