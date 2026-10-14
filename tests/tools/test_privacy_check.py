"""The privacy check: generic patterns everywhere, the local denylist where one exists.

Every example token below is assembled at runtime so that this file never contains a
string the check would flag in CI.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import time

import pytest

from tools import privacy_check

# Assembled, never literal: see the module docstring.
HA_TOKEN = "eyJ" + "a" * 20 + "." + "b" * 30 + "." + "c" * 40
GITHUB_TOKEN = "ghp_" + "A" * 36
GITHUB_PAT = "github_pat_" + "B" * 30
PRIVATE_IPS = [
    ".".join(["10", "1", "2", "3"]),
    ".".join(["172", "16", "0", "9"]),
    ".".join(["192", "168", "7", "8"]),
]
PUBLIC_IP = ".".join(["8", "8", "8", "8"])
NOT_PRIVATE_172 = ".".join(["172", "32", "0", "1"])
MAC = ":".join(["00", "1a", "2b", "3c", "4d", "5e"])
MAC_DASHED = "-".join(["00", "1A", "2B", "3C", "4D", "5E"])
LOCAL_HOST = "homeassistant" + ".local"
EMAIL = "@".join(["someone", "example.com"])
HEX_ID = "0123456789abcdef" * 2

DENYLIST = ["Top Floor Hallway", "switch.gizmo_plug_7", "Zorblax"]


def _scan(
    text: str, allowlist: frozenset[str] = frozenset(), hex_ids: bool = True
) -> list[privacy_check.Finding]:
    return privacy_check.scan_text(
        text, denylist=privacy_check.compile_denylist([]), allowlist=allowlist, hex_ids=hex_ids
    )


# --------------------------------------------------------------------------------------
# Generic patterns
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sample", "kind"),
    [
        (HA_TOKEN, "home_assistant_token"),
        (GITHUB_TOKEN, "github_token"),
        (GITHUB_PAT, "github_token"),
        (PRIVATE_IPS[0], "private_ipv4"),
        (PRIVATE_IPS[1], "private_ipv4"),
        (PRIVATE_IPS[2], "private_ipv4"),
        (MAC, "mac_address"),
        (MAC_DASHED, "mac_address"),
        (LOCAL_HOST, "local_hostname"),
        (EMAIL, "email_address"),
        (HEX_ID, "hex_id"),
    ],
)
def test_each_generic_pattern_is_detected(sample: str, kind: str) -> None:
    findings = _scan(f"value: {sample}\n")

    assert [f.kind for f in findings] == [kind]
    assert findings[0].line == 1


@pytest.mark.parametrize(
    "sample",
    [
        PUBLIC_IP,
        NOT_PRIVATE_172,
        "CLAUDE.local.md",
        "settings.local.json",
        "*.local.*",
        "0123456789abcdef" * 4,  # a sha256 is 64 characters, not a 32 character registry id
        "0123456789abcdef" * 2 + "01234567",  # a 40 character commit sha
        "z" * 32,  # the right length, not hexadecimal
    ],
)
def test_lookalikes_are_not_flagged(sample: str) -> None:
    assert _scan(f"value: {sample}\n") == []


def test_hex_ids_are_allowed_inside_anonymized_fixtures() -> None:
    denylist = privacy_check.compile_denylist([])
    text = f"id: {HEX_ID}\n"

    assert privacy_check.scan_path("tests/fixtures/automations/one.json", text, denylist) == []
    assert privacy_check.scan_path("tests/unit/test_x.py", text, denylist) != []


def test_the_line_number_is_reported() -> None:
    findings = _scan(f"one\ntwo\nthree {MAC}\n")

    assert [(f.kind, f.line) for f in findings] == [("mac_address", 3)]


# --------------------------------------------------------------------------------------
# The denylist
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The Top Floor Hallway light",
        "top floor hallway",
        "light.top_floor_hallway_lamp",
        "top-floor-hallway",
        "TOP_FLOOR_HALLWAY",
    ],
)
def test_a_denylisted_phrase_matches_any_separator_and_case(text: str) -> None:
    denylist = privacy_check.compile_denylist(DENYLIST)

    findings = privacy_check.scan_text(text, denylist=denylist)

    assert [f.kind for f in findings] == ["denylist"]


def test_a_denylisted_entity_id_matches_exactly() -> None:
    denylist = privacy_check.compile_denylist(DENYLIST)

    assert privacy_check.scan_text("entity_id: switch.gizmo_plug_7", denylist=denylist)
    assert privacy_check.scan_text("switch.gizmo_plug_71", denylist=denylist) == []


def test_a_denylisted_word_does_not_match_inside_another_word() -> None:
    denylist = privacy_check.compile_denylist(DENYLIST)

    assert privacy_check.scan_text("zorblaxian", denylist=denylist) == []
    assert privacy_check.scan_text("a Zorblax here", denylist=denylist)


def test_denylist_lines_are_loaded_without_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "denylist.txt"
    path.write_text("# a comment\n\nZorblax\n  switch.gizmo_plug_7  \n", encoding="utf-8")

    assert privacy_check.load_lines(path) == ["Zorblax", "switch.gizmo_plug_7"]


def test_a_missing_list_file_loads_as_empty(tmp_path: Path) -> None:
    assert privacy_check.load_lines(tmp_path / "nope.txt") == []


# --------------------------------------------------------------------------------------
# The allowlist and masking
# --------------------------------------------------------------------------------------


def test_an_allowlisted_match_is_ignored() -> None:
    findings = _scan(f"contact {EMAIL}\n", allowlist=frozenset({EMAIL.lower()}))

    assert findings == []


def test_the_allowlist_is_case_insensitive() -> None:
    assert _scan(f"contact {EMAIL.upper()}\n", allowlist=frozenset({EMAIL.lower()})) == []


def test_the_shipped_allowlist_permits_the_co_author_trailer() -> None:
    allowlist = privacy_check.load_allowlist(privacy_check.REPO_ROOT / privacy_check.ALLOWLIST_PATH)
    trailer = "Co-Authored-By: Claude <" + "@".join(["noreply", "anthropic.com"]) + ">"

    assert _scan(trailer, allowlist=allowlist) == []


def test_findings_never_carry_the_full_match() -> None:
    findings = _scan(f"token {GITHUB_TOKEN}\n")

    assert GITHUB_TOKEN not in findings[0].excerpt
    assert findings[0].excerpt.startswith("ghp")
    assert len(findings[0].excerpt) == len(GITHUB_TOKEN)


@pytest.mark.parametrize(
    ("value", "expected"), [("abc", "***"), ("abcdef", "******"), ("abcdefgh", "abc***gh")]
)
def test_mask(value: str, expected: str) -> None:
    assert privacy_check.mask(value) == expected


# --------------------------------------------------------------------------------------
# Modes: staged, commit message, ci
# --------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "@".join(["test", "example.com"]))
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "denylist.txt").write_text("\n".join(DENYLIST) + "\n", encoding="utf-8")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "privacy_allowlist.txt").write_text("", encoding="utf-8")
    return tmp_path


def test_staged_mode_blocks_a_denylisted_name(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "doc.md").write_text("The Zorblax device\n", encoding="utf-8")
    _git(repo, "add", "doc.md")

    code = privacy_check.main(["--staged", "--root", str(repo)])

    assert code == 1
    out = capsys.readouterr().out
    assert "doc.md:1: denylist:" in out
    assert "Zorblax" not in out


def test_staged_mode_passes_clean_content(repo: Path) -> None:
    (repo / "doc.md").write_text("A living room fan example\n", encoding="utf-8")
    _git(repo, "add", "doc.md")

    assert privacy_check.main(["--staged", "--root", str(repo)]) == 0


def test_staged_mode_scans_the_staged_content_not_the_working_tree(repo: Path) -> None:
    path = repo / "doc.md"
    path.write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "doc.md")
    path.write_text("Zorblax\n", encoding="utf-8")

    assert privacy_check.main(["--staged", "--root", str(repo)]) == 0


def test_staged_mode_skips_binary_files(repo: Path) -> None:
    (repo / "blob.bin").write_bytes(b"\x00\x01" + b"Zorblax")
    _git(repo, "add", "blob.bin")

    assert privacy_check.main(["--staged", "--root", str(repo)]) == 0


def test_staged_mode_applies_the_generic_patterns_too(repo: Path) -> None:
    (repo / "notes.md").write_text(f"host {LOCAL_HOST}\n", encoding="utf-8")
    _git(repo, "add", "notes.md")

    assert privacy_check.main(["--staged", "--root", str(repo)]) == 1


def test_a_clone_with_private_context_must_have_a_denylist(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / "local" / "denylist.txt").unlink()
    (repo / "CLAUDE.local.md").write_text("private\n", encoding="utf-8")
    (repo / "doc.md").write_text("clean\n", encoding="utf-8")
    _git(repo, "add", "doc.md")

    assert privacy_check.main(["--staged", "--root", str(repo)]) == 2
    assert "make_denylist" in capsys.readouterr().out


def test_a_clone_without_private_context_needs_no_denylist(repo: Path) -> None:
    (repo / "local" / "denylist.txt").unlink()
    (repo / "doc.md").write_text("Zorblax is unknown here\n", encoding="utf-8")
    _git(repo, "add", "doc.md")

    assert privacy_check.main(["--staged", "--root", str(repo)]) == 0


def test_commit_message_mode_scans_the_message(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    message = repo / "COMMIT_EDITMSG"
    message.write_text(
        "feat: add Zorblax support\n\n# a git comment with Zorblax\n", encoding="utf-8"
    )

    code = privacy_check.main(["--commit-msg", str(message), "--root", str(repo)])

    assert code == 1
    out = capsys.readouterr().out
    assert out.count("denylist:") == 1
    assert "commit message:1:" in out


def test_commit_message_mode_passes_a_clean_message(repo: Path) -> None:
    message = repo / "COMMIT_EDITMSG"
    message.write_text("feat: add a living room example\n", encoding="utf-8")

    assert privacy_check.main(["--commit-msg", str(message), "--root", str(repo)]) == 0


def test_ci_mode_scans_tracked_files_with_generic_patterns_only(repo: Path) -> None:
    (repo / "a.md").write_text("Zorblax\n", encoding="utf-8")
    (repo / "b.md").write_text(f"{MAC}\n", encoding="utf-8")
    _git(repo, "add", "a.md")
    _git(repo, "commit", "-q", "-m", "one")
    assert privacy_check.main(["--ci", "--root", str(repo)]) == 0, "denylist is not used in ci"

    _git(repo, "add", "b.md")
    _git(repo, "commit", "-q", "-m", "two")

    assert privacy_check.main(["--ci", "--root", str(repo)]) == 1


def test_files_mode_scans_the_given_paths(repo: Path) -> None:
    path = repo / "x.md"
    path.write_text("Zorblax\n", encoding="utf-8")

    assert privacy_check.main(["--files", str(path), "--root", str(repo)]) == 1
    path.write_text("fine\n", encoding="utf-8")
    assert privacy_check.main(["--files", str(path), "--root", str(repo)]) == 0


def test_exactly_one_mode_is_required(repo: Path) -> None:
    with pytest.raises(SystemExit):
        privacy_check.main(["--root", str(repo)])


# --------------------------------------------------------------------------------------
# A denylist of thousands of tokens must stay fast: candidates are picked by word
# --------------------------------------------------------------------------------------


def test_the_denylist_indexes_tokens_by_their_rarest_word() -> None:
    denylist = privacy_check.compile_denylist(
        ["switch.zorblax_plug", "switch.quux_lamp", "Zorblax Hallway"]
    )

    assert len(denylist) == 3
    # `switch` and `zorblax` are shared, so nothing is filed under them: a line holding
    # only those words cannot contain any of the three tokens in full.
    assert [t for t, _ in denylist.candidates("the switch is on")] == []
    assert [t for t, _ in denylist.candidates("zorblax")] == []
    assert [t for t, _ in denylist.candidates("a plug and a hallway")] == [
        "switch.zorblax_plug",
        "Zorblax Hallway",
    ]


def test_candidates_come_longest_first() -> None:
    denylist = privacy_check.compile_denylist(["Zorblax", "Zorblax Plug Deluxe", "Zorblax Plug"])

    assert [t for t, _ in denylist.candidates("zorblax plug deluxe")] == [
        "Zorblax Plug Deluxe",
        "Zorblax Plug",
        "Zorblax",
    ]


def test_an_empty_denylist_has_no_candidates() -> None:
    assert privacy_check.compile_denylist([]).candidates("anything at all") == []


def test_a_large_denylist_scans_quickly() -> None:
    tokens = [f"sensor.gizmo_{i}_power" for i in range(5000)] + [f"Gizmo {i}" for i in range(2000)]
    denylist = privacy_check.compile_denylist(tokens)
    text = "\n".join(f"line {i} mentions sensor.gizmo_{i % 7000}_power here" for i in range(3000))

    started = time.perf_counter()
    findings = privacy_check.scan_text(text, denylist=denylist)
    elapsed = time.perf_counter() - started

    # Every line carries its entity id; lines whose number is below 2000 also carry the
    # device name `Gizmo <n>`, which rightly matches inside the entity id.
    assert {f.line for f in findings} == set(range(1, 3001))
    assert elapsed < 2.0


# --------------------------------------------------------------------------------------
# Edges the modes have to survive
# --------------------------------------------------------------------------------------


def test_staged_mode_skips_text_that_is_not_utf8(repo: Path) -> None:
    (repo / "latin.txt").write_bytes("Zorblax caf\xe9".encode("latin-1"))
    _git(repo, "add", "latin.txt")

    assert privacy_check.main(["--staged", "--root", str(repo)]) == 0


def test_files_mode_skips_a_missing_file_and_a_file_outside_the_root(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "far.md"
    outside.write_text("Zorblax\n", encoding="utf-8")

    code = privacy_check.main(
        ["--files", str(repo / "missing.md"), str(outside), "--root", str(repo)]
    )

    assert code == 1


def test_the_anonymizers_synthetic_mac_range_is_not_a_finding() -> None:
    synthetic = privacy_check.SYNTHETIC_MAC_PREFIX + "2a"

    assert _scan(f"mac: {synthetic}\n") == []
    assert _scan(f"mac: {MAC}\n")
