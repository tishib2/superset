"""Pydantic models for Devin API responses and configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    devin_api_key: str = Field(alias="DEVIN_API_KEY")
    devin_org_id: str = Field(alias="DEVIN_ORG_ID")
    slack_webhook_url: str = Field(alias="SLACK_WEBHOOK_URL")

    github_actor: str = Field(default="unknown", alias="GITHUB_ACTOR")
    github_server_url: str = Field(default="https://github.com", alias="GITHUB_SERVER_URL")
    github_repository: str = Field(default="", alias="GITHUB_REPOSITORY")
    github_sha: str = Field(default="", alias="GITHUB_SHA")
    github_run_id: str = Field(default="", alias="GITHUB_RUN_ID")

    repo_root: str = Field(default="/repo", alias="REPO_ROOT")
    target_files: str = Field(default="", alias="TARGET_FILES")
    skip_launch_notification: bool = Field(default=False, alias="SKIP_LAUNCH_NOTIFICATION")
    dry_run: bool = Field(default=False, alias="DRY_RUN")

    devin_api_base: str = "https://api.devin.ai/v3"
    max_wait: int = 1200
    poll_interval: int = 30


class DevinPullRequest(BaseModel):
    """A pull request created by a Devin session."""

    number: int | None = None
    url: str | None = None
    title: str | None = None


class DevinSessionResponse(BaseModel):
    """Response from the Devin sessions API."""

    session_id: str
    url: str
    status: str
    pull_requests: list[DevinPullRequest] = Field(default_factory=list)


class FlattenTestsConfig(BaseModel):
    """Configuration loaded from .devin/flatten-tests.json."""

    targets: list[str]
    test_command: str
    pr_branch_prefix: str
