"""Submission intake (strict JSON, preservation) and replay path safety (grader/intake.py, grader/replay.py)."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from grader import intake as ik
from grader import replay as rp


@pytest.mark.parametrize("text, message", [
    ('{"a": 1, "a": 2}', "duplicate key"),
    ('{"a": NaN}', "non-finite constant"),
    ('{"a": Infinity}', "non-finite constant"),
    ('{"a": 1e309}', "finite double"),
])
def test_strict_loads_rejects(text: str, message: str):
    with pytest.raises(ik.StrictJSONError, match=message):
        ik.strict_loads(text)


def test_strict_loads_accepts_ordinary_json():
    assert ik.strict_loads('{"a": [1, 2.5, true, null], "b": {"c": "d"}}') == {"a": [1, 2.5, True, None], "b": {"c": "d"}}


@pytest.mark.skipif(os.name != "posix", reason="symlinks")
def test_preserve_archives_regular_files_read_only_and_never_follows_links(tmp_path: Path):
    sub, archive = tmp_path / "submission", tmp_path / "archive"
    (sub / "queries").mkdir(parents=True)
    (sub / "answer.json").write_text("{}", encoding="utf-8")
    (sub / "queries" / "q.sql").write_text("select 1", encoding="utf-8")
    secret = tmp_path / "outside.txt"
    secret.write_text("not part of the submission", encoding="utf-8")
    (sub / "link.txt").symlink_to(secret)
    (sub / "linked_dir").symlink_to(tmp_path)
    inv = ik.preserve(sub, archive)
    assert inv["answer.json"] == {"sha256": hashlib.sha256(b"{}").hexdigest(), "bytes": 2}
    assert inv["queries/q.sql"]["bytes"] == 8
    assert inv["link.txt"] == {"special": "symlink"} and inv["linked_dir"] == {"special": "symlink"}
    assert not (archive / "link.txt").exists()
    assert stat.S_IMODE((archive / "answer.json").stat().st_mode) == 0o444


@pytest.fixture
def answer_dir(tmp_path: Path) -> Path:
    d = tmp_path / "answer"
    (d / "sub").mkdir(parents=True)
    (d / "q.sql").write_text("select 1", encoding="utf-8")
    (d / "sub" / "x.py").write_text("print(1)", encoding="utf-8")
    (d / "game.duckdb").write_text("", encoding="utf-8")
    (tmp_path / "outside.sql").write_text("select 2", encoding="utf-8")
    if os.name == "posix":
        (d / "link.sql").symlink_to(d / "q.sql")
        (d / "out").symlink_to(tmp_path)
    return d


@pytest.mark.parametrize("rel", ["q.sql", "sub/x.py"])
def test_safe_member_accepts_regular_files_inside(answer_dir: Path, rel: str):
    assert rp.safe_member(answer_dir, rel) == answer_dir.resolve() / rel


@pytest.mark.parametrize("rel, reason", [
    ("../outside.sql", "escapes"), ("/etc/passwd", "escapes"), ("~/x.sql", "escapes"), ("sub\\x.py", "invalid path"),
    ("", "invalid path"), ("game.duckdb", "reserved"), ("_replay_out/r.json", "reserved"), ("tmp/x.py", "reserved"),
    ("missing.sql", "not a regular file"), ("sub", "not a regular file"),
])
def test_safe_member_rejects(answer_dir: Path, rel: str, reason: str):
    with pytest.raises(rp.ReplayRejected, match=reason):
        rp.safe_member(answer_dir, rel)


@pytest.mark.skipif(os.name != "posix", reason="symlinks")
@pytest.mark.parametrize("rel", ["link.sql", "out/outside.sql"])
def test_safe_member_rejects_symlinks(answer_dir: Path, rel: str):
    with pytest.raises(rp.ReplayRejected, match="symlink"):
        rp.safe_member(answer_dir, rel)
