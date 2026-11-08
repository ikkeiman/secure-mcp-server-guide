"""policy.py のテスト。MCP の接続は使わず、純粋関数だけを検証する。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from policy import (
    Policy,
    PolicyError,
    check_extension,
    check_size,
    fingerprint,
    iter_allowed_files,
    relative_display,
    resolve_in_root,
    truncate_output,
    validate_query,
    validate_readable_file,
)


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Policy, Path, Path]:
    """root(許可) と outside(不許可) を用意する。"""
    root = tmp_path / "notes"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "a.md").write_text("hello\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "b.txt").write_text("world\n", encoding="utf-8")
    (root / "secret.key").write_text("not allowed ext\n", encoding="utf-8")
    (root / ".hidden.md").write_text("hidden\n", encoding="utf-8")
    (outside / "leak.md").write_text("outside\n", encoding="utf-8")
    policy = Policy(root=root, max_file_bytes=64, max_output_chars=10, max_results=2)
    return policy, root, outside


# --- resolve_in_root: パストラバーサル ---------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "../outside/leak.md",
        "sub/../../outside/leak.md",
        "..",
        "sub/..",
    ],
)
def test_rejects_dotdot(workspace, bad):
    policy, _, _ = workspace
    with pytest.raises(PolicyError):
        resolve_in_root(policy, bad)


def test_rejects_absolute_path(workspace):
    policy, _, outside = workspace
    with pytest.raises(PolicyError):
        resolve_in_root(policy, str(outside / "leak.md"))
    with pytest.raises(PolicyError):
        resolve_in_root(policy, "/etc/passwd")


def test_rejects_null_byte_and_empty(workspace):
    policy, _, _ = workspace
    for bad in ["", "a.md\x00.txt"]:
        with pytest.raises(PolicyError):
            resolve_in_root(policy, bad)


def test_rejects_too_long_path(workspace):
    policy, _, _ = workspace
    with pytest.raises(PolicyError):
        resolve_in_root(policy, "a" * (policy.max_path_chars + 1))


def test_rejects_hidden(workspace):
    policy, _, _ = workspace
    with pytest.raises(PolicyError):
        resolve_in_root(policy, ".hidden.md")


def test_accepts_normal_relative_path(workspace):
    policy, root, _ = workspace
    assert resolve_in_root(policy, "sub/b.txt") == Path(os.path.realpath(root / "sub" / "b.txt"))


# --- シンボリックリンク -----------------------------------------------------------


def test_symlink_file_pointing_outside_is_rejected(workspace):
    policy, root, outside = workspace
    (root / "link.md").symlink_to(outside / "leak.md")
    with pytest.raises(PolicyError):
        resolve_in_root(policy, "link.md")


def test_symlink_dir_pointing_outside_is_rejected(workspace):
    policy, root, outside = workspace
    (root / "linkdir").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PolicyError):
        resolve_in_root(policy, "linkdir/leak.md")


def test_symlink_inside_root_is_allowed_by_resolve_but_not_listed(workspace):
    policy, root, _ = workspace
    (root / "alias.md").symlink_to(root / "a.md")
    # 実体が root 内なので解決自体は通る
    assert resolve_in_root(policy, "alias.md") == Path(os.path.realpath(root / "a.md"))
    # ただし一覧ではシンボリックリンクはたどらない
    names = [relative_display(policy, p) for p in iter_allowed_files(policy)]
    assert "alias.md" not in names
    assert "a.md" in names


# --- 拡張子・サイズ -------------------------------------------------------------


def test_extension_allowlist(workspace):
    policy, root, _ = workspace
    with pytest.raises(PolicyError):
        check_extension(policy, root / "secret.key")
    check_extension(policy, root / "a.md")
    check_extension(policy, root / "A.MD")  # 大文字も同じ扱い


def test_validate_readable_file_rejects_disallowed_extension(workspace):
    policy, _, _ = workspace
    with pytest.raises(PolicyError):
        validate_readable_file(policy, "secret.key")


def test_size_limit(workspace):
    policy, root, _ = workspace
    big = root / "big.md"
    big.write_bytes(b"x" * (policy.max_file_bytes + 1))
    with pytest.raises(PolicyError):
        check_size(policy, big)
    with pytest.raises(PolicyError):
        validate_readable_file(policy, "big.md")
    assert check_size(policy, root / "a.md") == 6


def test_directory_is_not_readable_file(workspace):
    policy, _, _ = workspace
    with pytest.raises(PolicyError):
        validate_readable_file(policy, "sub")


def test_missing_file(workspace):
    policy, _, _ = workspace
    with pytest.raises(PolicyError):
        validate_readable_file(policy, "nope.md")


# --- 出力・検索語の上限 -----------------------------------------------------------


def test_truncate_output(workspace):
    policy, _, _ = workspace
    assert truncate_output(policy, "short") == ("short", False)
    body, truncated = truncate_output(policy, "0123456789ABC")
    assert body == "0123456789" and truncated


def test_validate_query(workspace):
    policy, _, _ = workspace
    assert validate_query(policy, "  hello ") == "hello"
    for bad in ["", "   ", "a\x00b", "q" * (policy.max_query_chars + 1)]:
        with pytest.raises(PolicyError):
            validate_query(policy, bad)


# --- 列挙 ----------------------------------------------------------------------


def test_iter_allowed_files_filters(workspace):
    policy, _, _ = workspace
    names = sorted(relative_display(policy, p) for p in iter_allowed_files(policy))
    assert names == ["a.md", "sub/b.txt"]  # .hidden.md と secret.key は含まれない


def test_iter_allowed_files_scan_cap(tmp_path: Path):
    root = tmp_path / "many"
    root.mkdir()
    for i in range(10):
        (root / f"{i}.md").write_text("x", encoding="utf-8")
    policy = Policy(root=root, max_scan_files=3)
    assert len(iter_allowed_files(policy)) == 3


def test_iter_allowed_files_subdir_traversal_rejected(workspace):
    policy, _, _ = workspace
    with pytest.raises(PolicyError):
        iter_allowed_files(policy, "../outside")


# --- Policy 自体 ----------------------------------------------------------------


def test_policy_requires_absolute_existing_dir(tmp_path: Path):
    with pytest.raises(ValueError):
        Policy(root=Path("relative/dir"))
    with pytest.raises(ValueError):
        Policy(root=tmp_path / "does-not-exist")


def test_fingerprint_is_stable_and_short():
    assert fingerprint("abc") == fingerprint("abc")
    assert fingerprint("abc") != fingerprint("abd")
    assert len(fingerprint("abc")) == 12
