"""Tests for the Devin API client."""

from __future__ import annotations

import pytest
import respx
import httpx

from flatten_tests.devin_client import build_prompt, launch_session, poll_until_done
from flatten_tests.models import Config, DevinSessionResponse


def make_config(**kwargs) -> Config:  # type: ignore[return]
    defaults = dict(
        DEVIN_API_KEY="cog_test",
        DEVIN_ORG_ID="org-test",
        SLACK_WEBHOOK_URL="https://hooks.slack.com/test",
        GITHUB_RUN_ID="12345",
    )
    defaults.update(kwargs)
    return Config(**defaults)  # type: ignore[call-arg]


class TestBuildPrompt:
    def test_contains_repo_url(self) -> None:
        prompt = build_prompt(
            repo_url="https://github.com/org/repo",
            files=["src/foo.test.ts"],
            test_command="npm run test",
            pr_branch_prefix="auto/flatten",
            timestamp="20260101-000000",
        )
        assert "https://github.com/org/repo" in prompt

    def test_contains_file_list(self) -> None:
        prompt = build_prompt(
            repo_url="https://github.com/org/repo",
            files=["src/foo.test.ts", "src/bar.test.ts"],
            test_command="npm run test",
            pr_branch_prefix="auto/flatten",
            timestamp="20260101-000000",
        )
        assert "src/foo.test.ts" in prompt
        assert "src/bar.test.ts" in prompt

    def test_contains_pr_branch(self) -> None:
        prompt = build_prompt(
            repo_url="https://github.com/org/repo",
            files=["src/foo.test.ts"],
            test_command="npm run test",
            pr_branch_prefix="auto/flatten",
            timestamp="20260101-000000",
        )
        assert "auto/flatten/20260101-000000" in prompt

    def test_contains_skip_ci(self) -> None:
        prompt = build_prompt(
            repo_url="https://github.com/org/repo",
            files=["src/foo.test.ts"],
            test_command="npm run test",
            pr_branch_prefix="auto/flatten",
            timestamp="20260101-000000",
        )
        assert "[skip ci]" in prompt


class TestLaunchSession:
    @respx.mock
    def test_success(self) -> None:
        config = make_config()
        respx.post(
            f"{config.devin_api_base}/organizations/{config.devin_org_id}/sessions"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "session_id": "sess-abc",
                    "url": "https://app.devin.ai/sessions/sess-abc",
                    "status": "new",
                    "pull_requests": [],
                },
            )
        )

        session = launch_session(config, "test prompt")
        assert session.session_id == "sess-abc"
        assert session.status == "new"

    @respx.mock
    def test_retries_on_failure_then_succeeds(self) -> None:
        config = make_config()
        url = f"{config.devin_api_base}/organizations/{config.devin_org_id}/sessions"
        respx.post(url).mock(
            side_effect=[
                httpx.Response(500, json={"detail": "error"}),
                httpx.Response(
                    200,
                    json={
                        "session_id": "sess-abc",
                        "url": "https://app.devin.ai/sessions/sess-abc",
                        "status": "new",
                        "pull_requests": [],
                    },
                ),
            ]
        )

        session = launch_session(config, "test prompt")
        assert session.session_id == "sess-abc"

    @respx.mock
    def test_raises_after_max_retries(self) -> None:
        config = make_config()
        respx.post(
            f"{config.devin_api_base}/organizations/{config.devin_org_id}/sessions"
        ).mock(return_value=httpx.Response(500, json={"detail": "error"}))

        with pytest.raises(RuntimeError, match="Failed to launch"):
            launch_session(config, "test prompt")


class TestPollUntilDone:
    @respx.mock
    def test_exits_on_terminal_status(self) -> None:
        config = make_config(max_wait=90, poll_interval=30)
        url = f"{config.devin_api_base}/organizations/{config.devin_org_id}/sessions/sess-abc"
        respx.get(url).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "session_id": "sess-abc",
                        "url": "https://app.devin.ai/sessions/sess-abc",
                        "status": "running",
                        "pull_requests": [],
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "session_id": "sess-abc",
                        "url": "https://app.devin.ai/sessions/sess-abc",
                        "status": "exit",
                        "pull_requests": [],
                    },
                ),
            ]
        )

        import unittest.mock as mock
        with mock.patch("flatten_tests.devin_client.time.sleep"):
            result = poll_until_done(config, "sess-abc")
        assert result.status == "exit"

    @respx.mock
    def test_exits_when_pr_created(self) -> None:
        config = make_config(max_wait=90, poll_interval=30)
        url = f"{config.devin_api_base}/organizations/{config.devin_org_id}/sessions/sess-abc"
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "session_id": "sess-abc",
                    "url": "https://app.devin.ai/sessions/sess-abc",
                    "status": "running",
                    "pull_requests": [{"pr_url": "https://github.com/org/repo/pull/42", "pr_state": "open"}],
                },
            )
        )

        import unittest.mock as mock
        with mock.patch("flatten_tests.devin_client.time.sleep"):
            result = poll_until_done(config, "sess-abc")
        assert result.status == "exit"
        assert len(result.pull_requests) == 1
