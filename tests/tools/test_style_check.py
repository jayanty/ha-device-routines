"""The style check: the em dash character is refused anywhere in the repository."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tools import style_check

EM_DASH = chr(0x2014)  # never the character itself: this file is checked too


def test_a_clean_file_passes(tmp_path: Path) -> None:
    path = tmp_path / "clean.md"
    path.write_text("A hyphen - and a colon: are both fine.\n", encoding="utf-8")

    assert style_check.scan_files([path]) == []


def test_an_em_dash_is_reported_with_its_position(tmp_path: Path) -> None:
    path = tmp_path / "dirty.md"
    path.write_text(f"first line\nsecond {EM_DASH} line\n", encoding="utf-8")

    findings = style_check.scan_files([path])

    assert findings == [style_check.Finding(path=path, line=2, column=8)]


def test_every_occurrence_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "dirty.py"
    path.write_text(f"x = '{EM_DASH}'\ny = '{EM_DASH}{EM_DASH}'\n", encoding="utf-8")

    findings = style_check.scan_files([path])

    assert [(f.line, f.column) for f in findings] == [(1, 6), (2, 6), (2, 7)]


def test_binary_files_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00" + EM_DASH.encode("utf-8"))

    assert style_check.scan_files([path]) == []


def test_a_missing_file_is_skipped(tmp_path: Path) -> None:
    assert style_check.scan_files([tmp_path / "gone.md"]) == []


def test_tracked_files_come_from_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.md").write_text("ok\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("ok\n", encoding="utf-8")
    monkeypatch.setattr(style_check, "_git_ls_files", lambda _root: ["a.md", "b.md"])

    assert style_check.tracked_files(tmp_path) == [tmp_path / "a.md", tmp_path / "b.md"]


def test_main_reports_findings_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "dirty.md"
    path.write_text(f"bad {EM_DASH} text\n", encoding="utf-8")

    code = style_check.main([str(path)])

    assert code == 1
    out = capsys.readouterr().out
    assert f"{path}:1:5" in out
    assert "em dash" in out


def test_main_is_quiet_and_passes_on_clean_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "clean.md"
    path.write_text("fine\n", encoding="utf-8")

    assert style_check.main([str(path)]) == 0
    assert capsys.readouterr().out == ""


def test_main_without_arguments_scans_the_tracked_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "x.md").write_text(f"{EM_DASH}\n", encoding="utf-8")
    monkeypatch.setattr(style_check, "_git_ls_files", lambda _root: ["x.md"])
    monkeypatch.chdir(tmp_path)

    assert style_check.main([]) == 1


def test_a_file_that_is_not_utf8_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "latin.txt"
    path.write_bytes(f"caf\xe9 {EM_DASH}".encode("latin-1", errors="replace"))

    assert style_check.scan_files([path]) == []


def test_tracked_files_really_asks_git(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.md").write_text("ok\n", encoding="utf-8")
    (tmp_path / "untracked.md").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.md"], cwd=tmp_path, check=True)

    assert style_check.tracked_files(tmp_path) == [tmp_path / "tracked.md"]
