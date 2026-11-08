"""参照実装の「ポリシー層」。

MCP の通信とは無関係な純粋関数だけを置く。server.py はこのモジュールの
関数を通してしかファイルシステムに触らない。テストもこのモジュールが中心。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path


class PolicyError(Exception):
    """ポリシー違反。メッセージは利用者に見せてよい短い文にする(絶対パスを含めない)。"""


@dataclass(frozen=True)
class Policy:
    """参照実装の制限値。すべて「少なめ」を既定とし、必要なら起動時に広げる。"""

    root: Path
    allowed_extensions: frozenset[str] = field(default_factory=lambda: frozenset({".md", ".txt"}))
    max_file_bytes: int = 256 * 1024  # 1 ファイルの読み取り上限
    max_output_chars: int = 8_000  # 1 回の応答で返す文字数の上限
    max_results: int = 20  # 1 リクエストで返す件数の上限
    max_scan_files: int = 2_000  # 1 回の検索で開くファイル数の上限
    max_query_chars: int = 200  # 検索語の長さ上限
    max_path_chars: int = 512  # 要求パスの長さ上限

    def __post_init__(self) -> None:
        if not self.root.is_absolute():
            raise ValueError("root は絶対パスで指定してください")
        if not self.root.is_dir():
            raise ValueError("root は存在するディレクトリである必要があります")
        # root 自体がシンボリックリンクでも、以降の比較は実体で行う
        object.__setattr__(self, "root", Path(os.path.realpath(self.root)))


def resolve_in_root(policy: Policy, requested: str) -> Path:
    """利用者(=モデル)から渡された相対パスを、許可ルート配下の実体パスに解決する。

    - NUL 文字・空文字・長すぎるパスを拒否
    - 絶対パスを拒否(相対パスのみ受け付ける)
    - ``..`` を含むパスを拒否(正規化前に弾く)
    - シンボリックリンクを実体に解決した上で、ルート配下であることを検証
    """
    if not requested or "\x00" in requested:
        raise PolicyError("パスが不正です")
    if len(requested) > policy.max_path_chars:
        raise PolicyError("パスが長すぎます")

    candidate = Path(requested)
    if candidate.is_absolute() or requested.startswith(("/", "\\")):
        raise PolicyError("絶対パスは指定できません。許可フォルダからの相対パスを指定してください")
    if any(part == ".." for part in candidate.parts):
        raise PolicyError("上位ディレクトリへの参照 ('..') は指定できません")
    if any(part.startswith(".") for part in candidate.parts):
        raise PolicyError("隠しファイル・隠しディレクトリは対象外です")

    resolved = Path(os.path.realpath(policy.root / candidate))
    if not is_within(resolved, policy.root):
        raise PolicyError("許可フォルダの外を指しています")
    return resolved


def is_within(path: Path, root: Path) -> bool:
    """path が root と同じか、その配下にあるか(両方とも実体パス前提)。"""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def check_extension(policy: Policy, path: Path) -> None:
    if path.suffix.lower() not in policy.allowed_extensions:
        allowed = ", ".join(sorted(policy.allowed_extensions))
        raise PolicyError(f"この拡張子は対象外です(対象: {allowed})")


def check_regular_file(path: Path) -> None:
    # realpath 済みなので lstat でシンボリックリンクが残っていれば異常
    try:
        st = path.lstat()
    except FileNotFoundError:
        raise PolicyError("ファイルが見つかりません") from None
    if os.path.islink(path):
        raise PolicyError("シンボリックリンクは対象外です")
    if not path.is_file():
        raise PolicyError("通常ファイルではありません")
    _ = st


def check_size(policy: Policy, path: Path) -> int:
    size = path.stat().st_size
    if size > policy.max_file_bytes:
        raise PolicyError(f"ファイルが大きすぎます(上限 {policy.max_file_bytes} バイト)")
    return size


def validate_readable_file(policy: Policy, requested: str) -> Path:
    """read 系ツールの入口。順番に検証して、通った実体パスを返す。"""
    path = resolve_in_root(policy, requested)
    check_regular_file(path)
    check_extension(policy, path)
    check_size(policy, path)
    return path


def truncate_output(policy: Policy, text: str) -> tuple[str, bool]:
    """応答の文字数を上限に収める。切り詰めたかどうかも返す。"""
    if len(text) <= policy.max_output_chars:
        return text, False
    return text[: policy.max_output_chars], True


def validate_query(policy: Policy, query: str) -> str:
    q = query.strip()
    if not q:
        raise PolicyError("検索語が空です")
    if "\x00" in q:
        raise PolicyError("検索語が不正です")
    if len(q) > policy.max_query_chars:
        raise PolicyError(f"検索語が長すぎます(上限 {policy.max_query_chars} 文字)")
    return q


def iter_allowed_files(policy: Policy, subdir: str = "") -> list[Path]:
    """許可ルート配下の、拡張子許可リストに合う通常ファイルを列挙する。

    - シンボリックリンクはたどらない(ディレクトリもファイルも)
    - 隠しディレクトリ・隠しファイルは除外
    - 件数は max_scan_files で打ち切る(列挙だけで時間を使わせない)
    """
    base = resolve_in_root(policy, subdir) if subdir else policy.root
    if not base.is_dir():
        raise PolicyError("ディレクトリではありません")

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and not os.path.islink(os.path.join(dirpath, d))
        )
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            full = Path(dirpath) / name
            if os.path.islink(full):
                continue
            if full.suffix.lower() not in policy.allowed_extensions:
                continue
            if not full.is_file():
                continue
            found.append(full)
            if len(found) >= policy.max_scan_files:
                return found
    return found


def relative_display(policy: Policy, path: Path) -> str:
    """応答に載せる表示用パス。絶対パスを漏らさない。"""
    return path.relative_to(policy.root).as_posix()


def fingerprint(value: str) -> str:
    """ログ用。原文を残さず、同一性だけ追えるようにする。"""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
