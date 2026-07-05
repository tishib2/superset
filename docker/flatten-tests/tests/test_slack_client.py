"""Tests for the Slack notification client."""

from __future__ import annotations

import pytest
import respx
import httpx

from flatten_tests.models import Config
from flatten_tests.slack_client import notify_completion, notify_detection


def make_config(**kwargs) -> Config:  # type: ignore[return]
    defaults = dict(
        DEVIN_API_KEY="cog_test",
        DEVIN_ORG_ID="org-test",
        SLACK_WEBHOOK_URL="https://hooks.slack.com/test",
        GITHUB_ACTOR="testuser",
        GITHUB_REPOSITORY="org/repo",
        GITHUB_SHA="abc123",
        GITHUB_RUN_ID="99999",
    )
    defaults.update(kwargs)
    return Config(**defaults)  # type: ignore[call-arg]


class TestNotifyDetection:
    def test_dry_run_skips_http(self) -> None:
        config = make_config(DRY_RUN=True)
        # Should not raise even without mock
        notify_detection(config, ["src/foo.test.ts"])

    @respx.mock
    def test_posts_to_webhook(self) -> None:
        config = make_config()
        mock_route = respx.post("https://hooks.slack.com/test").mock(
            return_value=httpx.Response(200)
        )
        notify_detection(config, ["src/foo.test.ts"])
        assert mock_route.called

    @respx.mock
    def test_payload_contains_run_id(self) -> None:
        config = make_config()
        captured = {}

        def capture(request: httpx.Request) -> httpx.Response:
            import json
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200)

        respx.post("https://hooks.slack.com/test").mock(side_effect=capture)
        notify_detection(config, ["src/foo.test.ts"])
        assert "99999" in str(captured["payload"])

    @respx.mock
    def test_payload_contains_file(self) -> None:
        config = make_config()
        captured = {}

        def capture(request: httpx.Request) -> httpx.Response:
            import json
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200)

        respx.post("https://hooks.slack.com/test").mock(side_effect=capture)
        notify_detection(config, ["src/foo.test.ts"])
        assert "src/foo.test.ts" in str(captured["payload"])


class TestNotifyCompletion:
    def test_dry_run_skips_http(self) -> None:
        config = make_config(DRY_RUN=True)
        notify_completion(config, "https://app.devin.ai/sessions/abc", "exit")

    @respx.mock
    def test_success_status(self) -> None:
        config = make_config()
        captured = {}

        def capture(request: httpx.Request) -> httpx.Response:
            import json
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200)

        respx.post("https://hooks.slack.com/test").mock(side_effect=capture)
        notify_completion(config, "https://app.devin.ai/sessions/abc", "exit")
        assert "成功" in str(captured["payload"])

    @respx.mock
    def test_timeout_status(self) -> None:
        config = make_config()
        captured = {}

        def capture(request: httpx.Request) -> httpx.Response:
            import json
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200)

        respx.post("https://hooks.slack.com/test").mock(side_effect=capture)
        notify_completion(config, "https://app.devin.ai/sessions/abc", "timeout")
        assert "タイムアウト" in str(captured["payload"])

    @respx.mock
    def test_error_status(self) -> None:
        config = make_config()
        captured = {}

        def capture(request: httpx.Request) -> httpx.Response:
            import json
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200)

        respx.post("https://hooks.slack.com/test").mock(side_effect=capture)
        notify_completion(config, "https://app.devin.ai/sessions/abc", "error")
        assert "失敗" in str(captured["payload"])
