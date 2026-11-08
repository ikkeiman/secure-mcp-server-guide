"""server.py のツール関数を、MCP 接続なしで直接呼んで確認する。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import server
from policy import Policy


@pytest.fixture
def policy(tmp_path: Path) -> Policy:
    root = tmp_path / "notes"
    root.mkdir()
    (root / "todo.md").write_text("買い物\n- 牛乳\n", encoding="utf-8")
    (root / "memo.txt").write_text("会議メモ: 牛乳の話\n", encoding="utf-8")
    (root / "ignore.bin").write_bytes(b"\x00\x01")
    (tmp_path / "outside.md").write_text("leak", encoding="utf-8")
    return Policy(root=root, max_output_chars=30, max_results=1)


def test_list_notes_respects_max_results(policy):
    out = server.do_list_notes(policy)
    assert "todo.md" in out or "memo.txt" in out
    assert "他 1 件" in out


def test_search_notes_hits_and_caps(policy):
    out = server.do_search_notes(policy, "牛乳")
    assert out.count("\n") == 0  # max_results=1 なので 1 行
    assert ":2: - 牛乳" in out or ":1: 会議メモ" in out


def test_read_note_prefixes_notice_and_truncates(policy):
    out = server.do_read_note(policy, "todo.md")
    assert out.startswith(server.UNTRUSTED_NOTICE)
    long_file = policy.root / "long.md"
    long_file.write_text("a" * 100, encoding="utf-8")
    out2 = server.do_read_note(policy, "long.md")
    assert "切り詰め" in out2


def test_read_note_outside_is_rejected_via_guard(policy):
    mcp = server.build_server(policy)
    assert mcp is not None
    with pytest.raises(server.PolicyError):
        server.do_read_note(policy, "../outside.md")


def test_server_exposes_only_read_only_tools(policy):
    mcp = server.build_server(policy)
    tools = asyncio.run(mcp.list_tools())
    names = sorted(t.name for t in tools)
    assert names == ["list_notes", "read_note", "search_notes"]
    for t in tools:
        assert t.annotations is not None
        assert t.annotations.read_only_hint is True
        assert t.annotations.destructive_hint is False
