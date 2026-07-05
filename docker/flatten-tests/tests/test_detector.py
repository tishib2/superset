"""Tests for the detector module."""

from __future__ import annotations

from pathlib import Path

import pytest

from flatten_tests.detector import detect_files, has_describe_block, is_test_file


class TestIsTestFile:
    def test_typescript_test_file(self) -> None:
        assert is_test_file("src/foo/foo.test.ts") is True

    def test_typescript_spec_file(self) -> None:
        assert is_test_file("src/foo/foo.spec.ts") is True

    def test_tsx_test_file(self) -> None:
        assert is_test_file("src/foo/Foo.test.tsx") is True

    def test_non_test_file(self) -> None:
        assert is_test_file("src/foo/foo.ts") is False

    def test_python_test_file(self) -> None:
        assert is_test_file("tests/test_foo.py") is False

    def test_javascript_test_file(self) -> None:
        assert is_test_file("src/foo/foo.test.js") is False


class TestHasDescribeBlock:
    def test_file_with_describe(self, tmp_path: Path) -> None:
        f = tmp_path / "foo.test.ts"
        f.write_text("describe('foo', () => { test('bar', () => {}); });")
        assert has_describe_block(f) is True

    def test_file_without_describe(self, tmp_path: Path) -> None:
        f = tmp_path / "foo.test.ts"
        f.write_text("test('bar', () => {});")
        assert has_describe_block(f) is False

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        f = tmp_path / "nonexistent.test.ts"
        assert has_describe_block(f) is False


class TestDetectFiles:
    def test_detects_matching_file(self, tmp_path: Path) -> None:
        file_path = tmp_path / "src" / "foo.test.ts"
        file_path.parent.mkdir(parents=True)
        file_path.write_text("describe('foo', () => {});")

        result = detect_files(
            repo_root=str(tmp_path),
            targets=["src"],
            changed_files=["src/foo.test.ts"],
        )
        assert result == ["src/foo.test.ts"]

    def test_skips_non_test_files(self, tmp_path: Path) -> None:
        result = detect_files(
            repo_root=str(tmp_path),
            targets=["src"],
            changed_files=["src/foo.ts"],
        )
        assert result == []

    def test_skips_files_outside_targets(self, tmp_path: Path) -> None:
        file_path = tmp_path / "other" / "foo.test.ts"
        file_path.parent.mkdir(parents=True)
        file_path.write_text("describe('foo', () => {});")

        result = detect_files(
            repo_root=str(tmp_path),
            targets=["src"],
            changed_files=["other/foo.test.ts"],
        )
        assert result == []

    def test_skips_files_without_describe(self, tmp_path: Path) -> None:
        file_path = tmp_path / "src" / "foo.test.ts"
        file_path.parent.mkdir(parents=True)
        file_path.write_text("test('foo', () => {});")

        result = detect_files(
            repo_root=str(tmp_path),
            targets=["src"],
            changed_files=["src/foo.test.ts"],
        )
        assert result == []

    def test_deduplicates_matches(self, tmp_path: Path) -> None:
        file_path = tmp_path / "src" / "foo.test.ts"
        file_path.parent.mkdir(parents=True)
        file_path.write_text("describe('foo', () => {});")

        result = detect_files(
            repo_root=str(tmp_path),
            targets=["src", "src/foo"],
            changed_files=["src/foo.test.ts"],
        )
        assert result == ["src/foo.test.ts"]
