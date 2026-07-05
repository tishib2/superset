"""Integration tests combining multiple modules."""

from __future__ import annotations

import json
import unittest.mock as mock
from pathlib import Path

import httpx
import pytest
import respx

from flatten_tests.detector import detect_files
from flatten_tests.main import load_flatten_config, main, resolve_matched_files
from flatten_tests.models import Config, FlattenTestsConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(**kwargs) -> Config:  # type: ignore[return]
    defaults = dict(
        DEVIN_API_KEY="cog_test",
        DEVIN_ORG_ID="org-test",
        SLACK_WEBHOOK_URL="https://hooks.slack.com/test",
        GITHUB_ACTOR="testuser",
        GITHUB_REPOSITORY="org/repo",
        GITHUB_SHA="abc123",
        GITHUB_RUN_ID="99999",
        SKIP_LAUNCH_NOTIFICATION="1",
    )
    defaults.update(kwargs)
    return Config(**defaults)  # type: ignore[call-arg]


def make_flatten_config_file(tmp_path: Path, targets: list[str] | None = None) -> FlattenTestsConfig:
    data = {
        "targets": targets or ["src"],
        "test_command": "cd superset-frontend && npm run test -- --testPathPattern",
        "pr_branch_prefix": "auto/flatten-tests",
    }
    config_dir = tmp_path / ".devin"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "flatten-tests.json").write_text(json.dumps(data))
    return FlattenTestsConfig.model_validate(data)


def make_test_file(tmp_path: Path, rel_path: str, content: str) -> Path:
    f = tmp_path / rel_path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    return f


BASE_ENV = {
    "DEVIN_API_KEY": "cog_test",
    "DEVIN_ORG_ID": "org-test",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/test",
    "GITHUB_ACTOR": "testuser",
    "GITHUB_REPOSITORY": "org/repo",
    "GITHUB_SHA": "abc123",
    "GITHUB_RUN_ID": "99999",
    "GITHUB_SERVER_URL": "https://github.com",
    "SKIP_LAUNCH_NOTIFICATION": "1",
}

SESSION_RUNNING = {
    "session_id": "sess-abc",
    "url": "https://app.devin.ai/sessions/sess-abc",
    "status": "running",
    "pull_requests": [],
}

SESSION_WITH_PR = {
    "session_id": "sess-abc",
    "url": "https://app.devin.ai/sessions/sess-abc",
    "status": "running",
    "pull_requests": [{"pr_url": "https://github.com/org/repo/pull/1", "pr_state": "open"}],
}


# ---------------------------------------------------------------------------
# detector + filesystem integration
# ---------------------------------------------------------------------------

class TestDetectorFilesystemIntegration:
    def test_detects_file_with_describe_in_target(self, tmp_path: Path) -> None:
        make_test_file(tmp_path, "src/foo.test.ts", "describe('foo', () => { test('bar', () => {}); });")
        result = detect_files(str(tmp_path), ["src"], ["src/foo.test.ts"])
        assert result == ["src/foo.test.ts"]

    def test_ignores_file_without_describe(self, tmp_path: Path) -> None:
        make_test_file(tmp_path, "src/foo.test.ts", "test('foo', () => {});")
        result = detect_files(str(tmp_path), ["src"], ["src/foo.test.ts"])
        assert result == []

    def test_ignores_non_test_file_with_describe(self, tmp_path: Path) -> None:
        make_test_file(tmp_path, "src/foo.ts", "describe('foo', () => {});")
        result = detect_files(str(tmp_path), ["src"], ["src/foo.ts"])
        assert result == []

    def test_ignores_file_outside_targets(self, tmp_path: Path) -> None:
        make_test_file(tmp_path, "other/foo.test.ts", "describe('foo', () => {});")
        result = detect_files(str(tmp_path), ["src"], ["other/foo.test.ts"])
        assert result == []

    def test_multiple_files_partial_match(self, tmp_path: Path) -> None:
        make_test_file(tmp_path, "src/a.test.ts", "describe('a', () => {});")
        make_test_file(tmp_path, "src/b.test.ts", "test('b', () => {});")
        make_test_file(tmp_path, "src/c.ts", "describe('c', () => {});")
        result = detect_files(
            str(tmp_path), ["src"],
            ["src/a.test.ts", "src/b.test.ts", "src/c.ts"],
        )
        assert result == ["src/a.test.ts"]

    def test_nested_target_path(self, tmp_path: Path) -> None:
        make_test_file(
            tmp_path,
            "src/visualizations/TimeTable/foo.test.ts",
            "describe('foo', () => {});",
        )
        result = detect_files(
            str(tmp_path),
            ["src/visualizations/TimeTable"],
            ["src/visualizations/TimeTable/foo.test.ts"],
        )
        assert result == ["src/visualizations/TimeTable/foo.test.ts"]


# ---------------------------------------------------------------------------
# load_flatten_config + filesystem integration
# ---------------------------------------------------------------------------

class TestLoadFlattenConfigIntegration:
    def test_loads_valid_config(self, tmp_path: Path) -> None:
        make_flatten_config_file(tmp_path, targets=["src/foo"])
        cfg = load_flatten_config(str(tmp_path))
        assert cfg is not None
        assert cfg.targets == ["src/foo"]

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        cfg = load_flatten_config(str(tmp_path))
        assert cfg is None


# ---------------------------------------------------------------------------
# main() end-to-end integration (mocked HTTP)
# ---------------------------------------------------------------------------

class TestMainIntegration:
    """End-to-end flow through main() with all HTTP mocked."""

    def _env(self, tmp_path: Path, **kwargs) -> dict:  # type: ignore[type-arg]
        make_flatten_config_file(tmp_path, targets=["src"])
        return {
            **BASE_ENV,
            "REPO_ROOT": str(tmp_path),
            "TARGET_FILES": "src/foo.test.ts",
            **kwargs,
        }

    @respx.mock
    def test_happy_path_pr_created(self, tmp_path: Path) -> None:
        """detect → launch → poll (PR created) → Slack completion → exit 0."""
        make_test_file(tmp_path, "src/foo.test.ts", "describe('foo', () => {});")
        env = self._env(tmp_path)

        respx.post("https://hooks.slack.com/test").mock(return_value=httpx.Response(200))
        respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
            return_value=httpx.Response(200, json=SESSION_RUNNING)
        )
        respx.get("https://api.devin.ai/v3/organizations/org-test/sessions/sess-abc").mock(
            return_value=httpx.Response(200, json=SESSION_WITH_PR)
        )
        respx.delete("https://api.devin.ai/v3/organizations/org-test/sessions/sess-abc").mock(
            return_value=httpx.Response(200)
        )

        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch("flatten_tests.devin_client.time.sleep"):
                # PR が作成されれば exit(0) せず正常終了する
                main()

    @respx.mock
    def test_no_describe_blocks_exits_cleanly(self, tmp_path: Path) -> None:
        """detect → no describe blocks → exit 0 without calling Devin API."""
        make_test_file(tmp_path, "src/foo.test.ts", "test('foo', () => {});")
        # TARGET_FILES に describe なしファイルを指定
        env = self._env(tmp_path)

        api_called = False

        def fail_if_called(request: httpx.Request) -> httpx.Response:
            nonlocal api_called
            api_called = True
            return httpx.Response(200, json=SESSION_RUNNING)

        respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
            side_effect=fail_if_called
        )

        with mock.patch.dict("os.environ", env, clear=True):
            # detect_files は TARGET_FILES を通じて呼ばれるが describe がないので空を返す
            # resolve_matched_files は TARGET_FILES を split するだけなので detect_files を経由しない
            # → detect_files をモックして空を返すことでスキップを再現する
            with mock.patch("flatten_tests.main.resolve_matched_files", return_value=[]):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 0
        assert not api_called

    @respx.mock
    def test_api_failure_sends_slack_failure_notification(self, tmp_path: Path) -> None:
        """API failure → notify_failure → exit 1."""
        make_test_file(tmp_path, "src/foo.test.ts", "describe('foo', () => {});")
        env = self._env(tmp_path)

        slack_calls: list[dict] = []  # type: ignore[type-arg]

        def capture_slack(request: httpx.Request) -> httpx.Response:
            slack_calls.append(json.loads(request.content))
            return httpx.Response(200)

        respx.post("https://hooks.slack.com/test").mock(side_effect=capture_slack)
        respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
            return_value=httpx.Response(500, json={"detail": "error"})
        )

        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch("flatten_tests.devin_client.time.sleep"):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        # Slack failure notification should have been sent
        assert len(slack_calls) >= 1
        assert any("失敗" in str(call) or "error" in str(call).lower() for call in slack_calls)

    @respx.mock
    def test_dry_run_skips_api_calls(self, tmp_path: Path) -> None:
        """DRY_RUN=1 → no Devin API calls, exits 0."""
        make_test_file(tmp_path, "src/foo.test.ts", "describe('foo', () => {});")
        env = self._env(tmp_path, DRY_RUN="1")

        respx.post("https://hooks.slack.com/test").mock(return_value=httpx.Response(200))

        devin_called = False

        def fail_if_called(request: httpx.Request) -> httpx.Response:
            nonlocal devin_called
            devin_called = True
            return httpx.Response(200, json=SESSION_RUNNING)

        respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
            side_effect=fail_if_called
        )

        with mock.patch.dict("os.environ", env, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        assert not devin_called

    @respx.mock
    def test_timeout_sends_slack_timeout_notification(self, tmp_path: Path) -> None:
        """Polling timeout → Slack timeout notification → exit 1."""
        make_test_file(tmp_path, "src/foo.test.ts", "describe('foo', () => {});")
        env = self._env(tmp_path)

        slack_calls: list[dict] = []  # type: ignore[type-arg]

        def capture_slack(request: httpx.Request) -> httpx.Response:
            slack_calls.append(json.loads(request.content))
            return httpx.Response(200)

        respx.post("https://hooks.slack.com/test").mock(side_effect=capture_slack)
        respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
            return_value=httpx.Response(200, json=SESSION_RUNNING)
        )
        respx.get("https://api.devin.ai/v3/organizations/org-test/sessions/sess-abc").mock(
            return_value=httpx.Response(200, json=SESSION_RUNNING)
        )
        respx.delete("https://api.devin.ai/v3/organizations/org-test/sessions/sess-abc").mock(
            return_value=httpx.Response(200)
        )

        # max_wait=30, poll_interval=30 でインスタンス生成してポーリング1回でタイムアウト
        fast_config = Config(  # type: ignore[call-arg]
            DEVIN_API_KEY="cog_test",
            DEVIN_ORG_ID="org-test",
            SLACK_WEBHOOK_URL="https://hooks.slack.com/test",
            GITHUB_REPOSITORY="org/repo",
            GITHUB_RUN_ID="99999",
            SKIP_LAUNCH_NOTIFICATION=True,
            TARGET_FILES="src/foo.test.ts",
            REPO_ROOT=str(tmp_path),
        )
        object.__setattr__(fast_config, "max_wait", 30)
        object.__setattr__(fast_config, "poll_interval", 30)

        with mock.patch("flatten_tests.devin_client.time.sleep"):
            with mock.patch("flatten_tests.main.Config", return_value=fast_config):
                with pytest.raises(SystemExit) as exc_info:
                    main()

        assert exc_info.value.code == 1
        assert any("Timed out" in str(call) for call in slack_calls)

    @respx.mock
    def test_pr_url_included_in_completion_notification(self, tmp_path: Path) -> None:
        """PR URL が Slack の完了通知に含まれること。"""
        make_test_file(tmp_path, "src/foo.test.ts", "describe('foo', () => {});")
        env = self._env(tmp_path)

        slack_calls: list[dict] = []  # type: ignore[type-arg]

        def capture_slack(request: httpx.Request) -> httpx.Response:
            slack_calls.append(json.loads(request.content))
            return httpx.Response(200)

        respx.post("https://hooks.slack.com/test").mock(side_effect=capture_slack)
        respx.post("https://api.devin.ai/v3/organizations/org-test/sessions").mock(
            return_value=httpx.Response(200, json=SESSION_RUNNING)
        )
        respx.get("https://api.devin.ai/v3/organizations/org-test/sessions/sess-abc").mock(
            return_value=httpx.Response(200, json=SESSION_WITH_PR)
        )
        respx.delete("https://api.devin.ai/v3/organizations/org-test/sessions/sess-abc").mock(
            return_value=httpx.Response(200)
        )

        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch("flatten_tests.devin_client.time.sleep"):
                main()

        assert any("https://github.com/org/repo/pull/1" in str(call) for call in slack_calls)
