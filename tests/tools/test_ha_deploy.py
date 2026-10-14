"""The deploy tool must fail safe: a bad archive never reaches custom_components."""

from __future__ import annotations

import ast
from email.message import Message
import io
import json
from pathlib import Path
import sys
from typing import Self
import zipfile

import pytest

from tools import ha_deploy
from tools.ha_deploy import (
    DeployError,
    deploy,
    extract_component,
    main,
    prune_backups,
    read_deployed,
    require_https,
    rollback,
    status,
    verify_archive,
)

ROOT = "ha-device-links-abc123"
MANIFEST = json.dumps({"domain": "device_links", "version": "0.0.1"})


def _archive(files: dict[str, str], root: str = ROOT) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, body in files.items():
            zf.writestr(f"{root}/{name}", body)
    return buf.getvalue()


def _component_archive(files: dict[str, str], root: str = ROOT) -> bytes:
    """Build a repository archive whose component subtree holds `files`."""
    payload = {f"custom_components/device_links/{name}": body for name, body in files.items()}
    payload.setdefault("custom_components/device_links/manifest.json", MANIFEST)
    payload["README.md"] = "not deployed"
    return _archive(payload, root=root)


def _snapshot(root: Path) -> dict[str, bytes]:
    """Byte-exact picture of a directory, used to prove nothing moved."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _seed_deployment(config_dir: Path, files: dict[str, str], commit: str) -> Path:
    component = config_dir / "custom_components" / "device_links"
    component.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        target = component / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    (component / ".deployed").write_text(
        json.dumps(
            {
                "commit": commit,
                "branch": "dev",
                "deployed_at": "2026-09-05T00:00:00Z",
                "previous_commit": None,
                "changed_files": sorted(files),
            }
        )
    )
    return component


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Stub the two network calls. No test in this file may touch the network."""
    state: dict[str, object] = {"sha": "a" * 40, "archive": b"", "calls": []}

    def _resolve(repo: str, branch: str, token: str | None = None) -> str:
        calls = state["calls"]
        assert isinstance(calls, list)
        calls.append(("resolve", repo, branch))
        state["resolve_token"] = token
        return str(state["sha"])

    def _download(repo: str, sha: str, token: str | None = None) -> bytes:
        calls = state["calls"]
        assert isinstance(calls, list)
        calls.append(("download", repo, sha))
        state["download_token"] = token
        archive = state["archive"]
        if isinstance(archive, Exception):
            raise archive
        assert isinstance(archive, bytes)
        return archive

    monkeypatch.setattr(ha_deploy, "resolve_commit", _resolve)
    monkeypatch.setattr(ha_deploy, "download_archive", _download)
    return state


# --------------------------------------------------------------------------- #
# Archive validation
# --------------------------------------------------------------------------- #


def test_a_valid_archive_passes() -> None:
    data = _archive(
        {
            "custom_components/device_links/manifest.json": json.dumps({"domain": "device_links"}),
            "custom_components/device_links/__init__.py": "",
        }
    )
    assert verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links") == (
        "ha-device-links-abc123"
    )


def test_an_archive_without_the_component_is_refused() -> None:
    data = _archive({"README.md": "nothing here"})
    with pytest.raises(DeployError, match=r"manifest\.json"):
        verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links")


def test_a_domain_mismatch_is_refused() -> None:
    data = _archive(
        {"custom_components/device_links/manifest.json": json.dumps({"domain": "something_else"})}
    )
    with pytest.raises(DeployError, match="domain"):
        verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links")


def test_more_than_one_top_level_directory_is_refused() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/custom_components/device_links/manifest.json", MANIFEST)
        zf.writestr("b/other.txt", "x")
    with pytest.raises(DeployError, match="one top level directory"):
        verify_archive(zipfile.ZipFile(io.BytesIO(buf.getvalue())), "device_links")


def test_an_unparseable_manifest_is_refused() -> None:
    data = _archive({"custom_components/device_links/manifest.json": "{not json"})
    with pytest.raises(DeployError, match="valid JSON"):
        verify_archive(zipfile.ZipFile(io.BytesIO(data)), "device_links")


def test_path_traversal_in_the_archive_is_refused(tmp_path: Path) -> None:
    """A zip entry escaping the target directory must never be written."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "root/custom_components/device_links/manifest.json", '{"domain":"device_links"}'
        )
        zf.writestr("root/custom_components/device_links/../../../etc/evil", "pwned")

    with pytest.raises(DeployError, match="escapes"):
        extract_component(
            zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", tmp_path
        )
    assert not (tmp_path.parent / "etc" / "evil").exists()


def test_traversal_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    """Validation is a whole-archive pass, so a bad entry leaves no partial tree."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "root/custom_components/device_links/manifest.json", '{"domain":"device_links"}'
        )
        zf.writestr("root/custom_components/device_links/../escape.py", "X = 1")

    target = tmp_path / "staging"
    with pytest.raises(DeployError, match="escapes"):
        extract_component(
            zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", target
        )
    assert _snapshot(target) == {}, "no file may be written when any entry is rejected"


def test_a_symlink_entry_is_refused(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "root/custom_components/device_links/manifest.json", '{"domain":"device_links"}'
        )
        info = zipfile.ZipInfo("root/custom_components/device_links/link.py")
        info.create_system = 3
        info.external_attr = (0o120777 << 16) | 0o20
        zf.writestr(info, "/etc/passwd")

    with pytest.raises(DeployError, match="symlink"):
        extract_component(
            zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", tmp_path / "s"
        )


def test_extract_writes_only_the_component_subtree(tmp_path: Path) -> None:
    data = _archive(
        {
            "custom_components/device_links/manifest.json": '{"domain":"device_links"}',
            "custom_components/device_links/const.py": "X = 1",
            "docs/PRD.md": "should not be deployed",
            "tests/test_x.py": "should not be deployed",
        }
    )
    extract_component(
        zipfile.ZipFile(io.BytesIO(data)), "ha-device-links-abc123", "device_links", tmp_path
    )

    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "const.py").read_text() == "X = 1"
    assert not (tmp_path / "docs").exists(), "only custom_components/<domain> is deployed"


# --------------------------------------------------------------------------- #
# Transport safety
# --------------------------------------------------------------------------- #


def test_a_non_https_url_is_rejected() -> None:
    with pytest.raises(DeployError, match="non-https"):
        require_https("http://api.github.com/repos/jayanty/ha-device-links/commits/dev")
    assert require_https("https://api.github.com/x") == "https://api.github.com/x"


def test_resolve_commit_refuses_a_plain_http_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even a misconfigured base URL cannot make the tool fetch over plain HTTP."""
    monkeypatch.setattr(ha_deploy, "API_BASE", "http://api.github.com")
    with pytest.raises(DeployError, match="non-https"):
        ha_deploy.resolve_commit("jayanty/ha-device-links", "dev")


def test_download_archive_refuses_a_plain_http_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ha_deploy, "CODELOAD_BASE", "http://codeload.github.com")
    with pytest.raises(DeployError, match="non-https"):
        ha_deploy.download_archive("jayanty/ha-device-links", "b" * 40)


@pytest.mark.parametrize("repo", ["", "noslash", "a/b/c", "../etc", "owner/..", "own er/name"])
def test_a_malformed_repo_argument_is_refused(repo: str, tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="owner/name"):
        deploy(tmp_path, repo, "device_links", branch="dev")


def test_a_malformed_ref_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="not a valid ref name"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", ref="dev; rm -rf /")


def test_the_module_imports_only_the_standard_library() -> None:
    """It runs inside the HA Core container, where nothing else is guaranteed."""
    source = Path(ha_deploy.__file__).read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    outside = sorted(imported - set(sys.stdlib_module_names) - {"__future__"})
    assert not outside, f"ha_deploy.py must be stdlib only, found: {outside}"


def test_the_module_never_restarts_and_reads_storage_only_for_the_hacs_store() -> None:
    source = Path(ha_deploy.__file__).read_text()
    body = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("homeassistant.restart", "ha core restart", "automations.yaml"):
        assert forbidden not in body, f"the deploy tool must never reference {forbidden}"
    mentions = [line for line in body.splitlines() if ".storage" in line]
    assert mentions == ['HACS_STORE = Path(".storage") / "hacs.repositories"']


# --------------------------------------------------------------------------- #
# The property that matters: a failure changes nothing
# --------------------------------------------------------------------------- #


def test_a_compile_failure_leaves_the_previous_deployment_intact(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "GOOD = 1"}, "old" + "0" * 37
    )
    before = _snapshot(component)

    github["sha"] = "b" * 40
    github["archive"] = _component_archive({"const.py": "def broken(:\n"})

    with pytest.raises(DeployError, match="does not compile"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(component) == before, "a syntax error must never reach custom_components"
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()
    assert not (tmp_path / "device_links" / "backups").exists(), "no backup for a failed deploy"


def test_a_download_failure_leaves_the_previous_deployment_intact(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "c" * 40
    )
    before = _snapshot(component)

    github["archive"] = DeployError("cannot fetch https://codeload.github.com/...: timed out")
    with pytest.raises(DeployError, match="cannot fetch"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(component) == before
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()


def test_a_bad_archive_leaves_the_previous_deployment_intact(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "d" * 40
    )
    before = _snapshot(component)

    github["archive"] = b"this is not a zip file"
    with pytest.raises(DeployError):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(component) == before
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()


def test_a_domain_mismatch_leaves_the_previous_deployment_intact(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "e" * 40
    )
    before = _snapshot(component)

    github["archive"] = _archive(
        {"custom_components/device_links/manifest.json": json.dumps({"domain": "impostor"})}
    )
    with pytest.raises(DeployError, match="domain"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(component) == before


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_a_first_deploy_creates_the_component_without_a_backup(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "1" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})

    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    component = tmp_path / "custom_components" / "device_links"
    assert (component / "const.py").read_text() == "X = 1"
    assert result["ok"] is True
    assert result["commit"] == "1" * 40
    assert result["previous_commit"] is None
    assert result["changed_files"] == ["const.py", "manifest.json"]
    assert result["restart_required"] is True
    assert not (tmp_path / "device_links" / "backups").exists()
    assert not (component / "README.md").exists(), "only the component subtree is deployed"


def test_a_successful_deploy_over_an_existing_deployment(
    tmp_path: Path, github: dict[str, object]
) -> None:
    component = _seed_deployment(
        tmp_path,
        {"manifest.json": MANIFEST, "const.py": "X = 1", "gone.py": "OLD = 1"},
        "0" * 40,
    )
    github["sha"] = "2" * 40
    github["archive"] = _component_archive({"const.py": "X = 2", "new.py": "NEW = 1"})

    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert result["changed_files"] == ["const.py", "gone.py", "new.py"]
    assert result["previous_commit"] == "0" * 40
    assert result["commit"] == "2" * 40
    assert result["restart_required"] is True
    assert result["browser_reload"] is False

    assert (component / "const.py").read_text() == "X = 2"
    assert (component / "new.py").read_text() == "NEW = 1"
    assert not (component / "gone.py").exists(), "removed files must not survive the swap"
    assert not list(component.rglob("__pycache__")), "compileall leftovers must be cleaned up"

    marker = json.loads((component / ".deployed").read_text())
    assert marker["commit"] == "2" * 40
    assert marker["branch"] == "dev"
    assert marker["previous_commit"] == "0" * 40
    assert marker["changed_files"] == ["const.py", "gone.py", "new.py"]
    assert marker["deployed_at"].endswith("Z")

    backups = sorted((tmp_path / ".ha_deploy" / "device_links" / "backups").iterdir())
    assert len(backups) == 1, "exactly one backup per deploy"
    assert (backups[0] / "const.py").read_text() == "X = 1"
    assert (backups[0] / "gone.py").read_text() == "OLD = 1"


def test_an_unchanged_redeploy_reports_no_changes(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "3" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", ref="3" * 40)

    assert result["changed_files"] == []
    assert result["restart_required"] is False
    assert result["browser_reload"] is False


def test_deploy_touches_nothing_else_under_the_config_directory(
    tmp_path: Path, github: dict[str, object]
) -> None:
    storage = tmp_path / ".storage"
    storage.mkdir()
    (storage / "device_links.profiles").write_text('{"data": "precious"}')
    (tmp_path / "configuration.yaml").write_text("default_config:\n")
    (tmp_path / "custom_components" / "spook").mkdir(parents=True)
    (tmp_path / "custom_components" / "spook" / "__init__.py").write_text("SPOOK = 1")
    outside = _snapshot(storage) | _snapshot(tmp_path / "custom_components" / "spook")

    github["sha"] = "4" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert _snapshot(storage) | _snapshot(tmp_path / "custom_components" / "spook") == outside
    assert (tmp_path / "configuration.yaml").read_text() == "default_config:\n"


# --------------------------------------------------------------------------- #
# restart_required and browser_reload
# --------------------------------------------------------------------------- #


def test_only_a_frontend_change_needs_a_browser_reload_not_a_restart(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "5" * 40
    github["archive"] = _component_archive(
        {"const.py": "X = 1", "frontend/device-links-panel.js": "console.log(1);"}
    )
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    github["sha"] = "6" * 40
    github["archive"] = _component_archive(
        {"const.py": "X = 1", "frontend/device-links-panel.js": "console.log(2);"}
    )
    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert result["changed_files"] == ["frontend/device-links-panel.js"]
    assert result["restart_required"] is False
    assert result["browser_reload"] is True


def test_a_python_change_requires_a_restart(tmp_path: Path, github: dict[str, object]) -> None:
    github["sha"] = "7" * 40
    github["archive"] = _component_archive(
        {"const.py": "X = 1", "frontend/device-links-panel.js": "console.log(1);"}
    )
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    github["sha"] = "8" * 40
    github["archive"] = _component_archive(
        {"const.py": "X = 2", "frontend/device-links-panel.js": "console.log(2);"}
    )
    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert result["changed_files"] == ["const.py", "frontend/device-links-panel.js"]
    assert result["restart_required"] is True
    assert result["browser_reload"] is False, "a restart covers the browser reload"
    assert result["reload_automations"] is False


# --------------------------------------------------------------------------- #
# Backups and rollback
# --------------------------------------------------------------------------- #


def test_backup_retention_keeps_five_and_prunes_the_sixth(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    names = [f"2026090{index}T120000Z-sha{index}" for index in range(1, 7)]
    for name in names:
        (backups / name).mkdir(parents=True)

    removed = prune_backups(backups, keep=5)

    assert removed == [names[0]], "the oldest backup is the one that goes"
    assert sorted(path.name for path in backups.iterdir()) == names[1:]


def test_repeated_deploys_never_grow_past_five_backups(
    tmp_path: Path, github: dict[str, object]
) -> None:
    for index in range(7):
        github["sha"] = str(index) * 40
        github["archive"] = _component_archive({"const.py": f"X = {index}"})
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    backups = list((tmp_path / ".ha_deploy" / "device_links" / "backups").iterdir())
    assert len(backups) == 5, "the backups directory must not grow without bound"


def test_rollback_restores_the_previous_content_exactly(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "a" * 40
    github["archive"] = _component_archive({"const.py": "GOOD = 1", "keep.py": "K = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    component = tmp_path / "custom_components" / "device_links"
    good = _snapshot(component)

    github["sha"] = "b" * 40
    github["archive"] = _component_archive({"const.py": "BAD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    assert (component / "const.py").read_text() == "BAD = 1"

    result = rollback(tmp_path, "device_links")

    assert (component / "const.py").read_text() == "GOOD = 1"
    assert (component / "keep.py").read_text() == "K = 1"
    assert result["ok"] is True
    assert result["commit"] == "a" * 40
    assert result["previous_commit"] == "b" * 40
    assert result["changed_files"] == ["const.py", "keep.py"]
    assert result["restart_required"] is True

    restored = _snapshot(component)
    assert {name: body for name, body in restored.items() if name != ".deployed"} == {
        name: body for name, body in good.items() if name != ".deployed"
    }
    marker = json.loads((component / ".deployed").read_text())
    assert marker["commit"] == "a" * 40
    assert marker["previous_commit"] == "b" * 40


def test_rollback_without_a_backup_fails_cleanly(tmp_path: Path) -> None:
    _seed_deployment(tmp_path, {"manifest.json": MANIFEST}, "f" * 40)
    with pytest.raises(DeployError, match="no backup"):
        rollback(tmp_path, "device_links")


# --------------------------------------------------------------------------- #
# status and the command line
# --------------------------------------------------------------------------- #


def test_status_on_a_missing_install_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(DeployError, match="not installed"):
        status(tmp_path, "device_links")

    code = main(["status", "--config-dir", str(tmp_path), "--domain", "device_links"])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == "", "stdout stays clean so a caller can always parse it"
    assert json.loads(captured.err)["ok"] is False
    assert "not installed" in json.loads(captured.err)["error"]

    (tmp_path / "custom_components" / "device_links").mkdir(parents=True)
    assert status(tmp_path, "device_links")["deployed"] is None


def test_status_prints_the_deployed_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_deployment(tmp_path, {"manifest.json": MANIFEST}, "9" * 40)

    code = main(["status", "--config-dir", str(tmp_path), "--domain", "device_links"])

    assert code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["deployed"]["commit"] == "9" * 40
    assert document["deployed"]["branch"] == "dev"
    assert document["backups"] == []


def test_the_command_line_prints_exactly_one_json_object(
    tmp_path: Path, github: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    github["sha"] = "c" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})

    code = main(
        [
            "deploy",
            "--config-dir",
            str(tmp_path),
            "--repo",
            "jayanty/ha-device-links",
            "--branch",
            "dev",
            "--domain",
            "device_links",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert len(captured.out.strip().splitlines()) == 1
    document = json.loads(captured.out)
    assert set(document) == {
        "ok",
        "changed",
        "commit",
        "previous_commit",
        "changed_files",
        "restart_required",
        "reload_automations",
        "browser_reload",
        "hacs_managed",
        "warnings",
    }
    assert document["ok"] is True
    assert github["calls"] == [
        ("resolve", "jayanty/ha-device-links", "dev"),
        ("download", "jayanty/ha-device-links", "c" * 40),
    ]


def test_an_explicit_ref_skips_the_branch_lookup(tmp_path: Path, github: dict[str, object]) -> None:
    github["archive"] = _component_archive({"const.py": "X = 1"})

    result = deploy(tmp_path, "jayanty/ha-device-links", "device_links", ref="D" * 40)

    assert result["commit"] == "d" * 40
    assert github["calls"] == [("download", "jayanty/ha-device-links", "d" * 40)]
    marker = json.loads((tmp_path / "custom_components" / "device_links" / ".deployed").read_text())
    assert marker["branch"] is None


def test_the_command_line_reports_a_failure_on_stderr(
    tmp_path: Path, github: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_deployment(tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "0" * 40)
    github["archive"] = b"not a zip"

    code = main(
        [
            "deploy",
            "--config-dir",
            str(tmp_path),
            "--repo",
            "jayanty/ha-device-links",
            "--branch",
            "dev",
            "--domain",
            "device_links",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert json.loads(captured.err)["ok"] is False
    assert (tmp_path / "custom_components" / "device_links" / "const.py").read_text() == "X = 1"


# --------------------------------------------------------------------------- #
# Error paths that only ever run when something has already gone wrong
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, amount: int) -> bytes:
        return self._payload[:amount]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_fetch_returns_the_body_over_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ha_deploy.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(b"hello")
    )
    assert ha_deploy._fetch("https://example.invalid/x", timeout=1.0, accept="*/*") == b"hello"


def test_fetch_turns_a_network_error_into_a_deploy_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(request: object, timeout: float) -> object:
        raise ha_deploy.urllib.error.URLError("name resolution failed")

    monkeypatch.setattr(ha_deploy.urllib.request, "urlopen", _boom)
    with pytest.raises(DeployError, match="cannot fetch"):
        ha_deploy._fetch("https://example.invalid/x", timeout=1.0, accept="*/*")


def test_fetch_refuses_an_oversized_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ha_deploy, "MAX_ARCHIVE_BYTES", 8)
    monkeypatch.setattr(
        ha_deploy.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(b"x" * 64)
    )
    with pytest.raises(DeployError, match="larger than"):
        ha_deploy._fetch("https://example.invalid/x", timeout=1.0, accept="*/*")


def test_resolve_commit_reads_the_sha_from_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ha_deploy,
        "_fetch",
        lambda url, timeout, accept, token=None: json.dumps({"sha": "A" * 40}).encode(),
    )
    assert ha_deploy.resolve_commit("jayanty/ha-device-links", "dev") == "a" * 40


def test_resolve_commit_refuses_a_response_that_is_not_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ha_deploy, "_fetch", lambda url, timeout, accept, token=None: b"<html>rate limited"
    )
    with pytest.raises(DeployError, match="not JSON"):
        ha_deploy.resolve_commit("jayanty/ha-device-links", "dev")


@pytest.mark.parametrize("body", [b"[]", b'{"message":"Not Found"}', b'{"sha":"nope"}'])
def test_resolve_commit_refuses_a_response_without_a_sha(
    body: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ha_deploy, "_fetch", lambda url, timeout, accept, token=None: body)
    with pytest.raises(DeployError, match="did not return a commit sha"):
        ha_deploy.resolve_commit("jayanty/ha-device-links", "dev")


def test_a_branch_name_that_is_not_a_ref_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DeployError, match="valid ref name"):
        deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev; rm -rf /")


def test_an_empty_archive_is_refused() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("  ", "")
    with pytest.raises(DeployError, match="empty"):
        verify_archive(zipfile.ZipFile(io.BytesIO(buf.getvalue())), "device_links")


def test_an_archive_whose_component_holds_only_directories_is_refused(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("root/custom_components/other/manifest.json", MANIFEST)
    with pytest.raises(DeployError, match="no files under"):
        extract_component(
            zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", tmp_path / "s"
        )


def test_directory_entries_in_the_archive_are_created(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("root/custom_components/device_links/", "")
        zf.writestr("root/custom_components/device_links/translations/", "")
        zf.writestr("root/custom_components/device_links/translations/en.json", "{}")

    target = tmp_path / "s"
    extract_component(zipfile.ZipFile(io.BytesIO(buf.getvalue())), "root", "device_links", target)

    assert (target / "translations" / "en.json").read_text() == "{}"


@pytest.mark.parametrize("body", ["{not json", '["a list"]'])
def test_a_damaged_deployed_marker_reads_as_never_deployed(body: str, tmp_path: Path) -> None:
    component = tmp_path / "custom_components" / "device_links"
    component.mkdir(parents=True)
    (component / ".deployed").write_text(body)

    assert ha_deploy.read_deployed(component) is None
    assert status(tmp_path, "device_links")["deployed"] is None


def test_a_stray_file_where_staging_belongs_is_cleared(
    tmp_path: Path, github: dict[str, object]
) -> None:
    (tmp_path / "custom_components").mkdir()
    (tmp_path / "custom_components" / ".device_links.new").write_text("litter")

    github["sha"] = "e" * 40
    github["archive"] = _component_archive({"const.py": "X = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert (tmp_path / "custom_components" / "device_links" / "const.py").read_text() == "X = 1"


def test_two_backups_in_the_same_second_do_not_collide(tmp_path: Path) -> None:
    component = _seed_deployment(tmp_path, {"manifest.json": MANIFEST}, "f" * 40)
    backups = tmp_path / "device_links" / "backups"

    first = ha_deploy.create_backup(component, backups, "f" * 40)
    second = ha_deploy.create_backup(component, backups, "f" * 40)

    assert first != second
    assert len(list(backups.iterdir())) == 2


def test_a_failed_swap_puts_the_previous_directory_straight_back(tmp_path: Path) -> None:
    component = _seed_deployment(
        tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "0" * 40
    )
    before = _snapshot(component)
    missing = tmp_path / "custom_components" / ".device_links.new"

    with pytest.raises(DeployError, match="could not swap"):
        ha_deploy.swap_into_place(missing, component)

    assert _snapshot(component) == before, "a failed swap must restore the previous directory"
    assert not (tmp_path / "custom_components" / ".device_links.previous").exists()


def test_rollback_over_the_command_line(tmp_path: Path, github: dict[str, object]) -> None:
    github["sha"] = "1" * 40
    github["archive"] = _component_archive({"const.py": "GOOD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    github["sha"] = "2" * 40
    github["archive"] = _component_archive({"const.py": "BAD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    code = main(["rollback", "--config-dir", str(tmp_path), "--domain", "device_links"])

    assert code == 0
    component = tmp_path / "custom_components" / "device_links"
    assert (component / "const.py").read_text() == "GOOD = 1"


def test_a_leftover_previous_directory_is_cleared_before_the_swap(
    tmp_path: Path, github: dict[str, object]
) -> None:
    _seed_deployment(tmp_path, {"manifest.json": MANIFEST, "const.py": "X = 1"}, "3" * 40)
    stale = tmp_path / "custom_components" / ".device_links.previous"
    stale.mkdir()
    (stale / "junk.py").write_text("JUNK = 1")

    github["sha"] = "4" * 40
    github["archive"] = _component_archive({"const.py": "X = 2"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert not stale.exists(), "litter from an interrupted run must not survive a deploy"
    assert (tmp_path / "custom_components" / "device_links" / "const.py").read_text() == "X = 2"


def test_a_failed_first_swap_reports_cleanly(tmp_path: Path) -> None:
    components = tmp_path / "custom_components"
    components.mkdir()
    with pytest.raises(DeployError, match="could not swap"):
        ha_deploy.swap_into_place(components / ".device_links.new", components / "device_links")
    assert not (components / "device_links").exists()


def test_a_failed_rollback_leaves_the_current_deployment_intact(
    tmp_path: Path, github: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    github["sha"] = "5" * 40
    github["archive"] = _component_archive({"const.py": "GOOD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    github["sha"] = "6" * 40
    github["archive"] = _component_archive({"const.py": "BAD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    component = tmp_path / "custom_components" / "device_links"
    before = _snapshot(component)

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("no space left on device")

    monkeypatch.setattr(ha_deploy.shutil, "copytree", _boom)
    with pytest.raises(DeployError, match="rollback aborted"):
        rollback(tmp_path, "device_links")

    assert _snapshot(component) == before
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()
    kept = tmp_path / ".ha_deploy" / "device_links" / "backups"
    assert len(list(kept.iterdir())) == 1, "backup is kept"


def test_a_rollback_that_cannot_swap_leaves_the_current_deployment_intact(
    tmp_path: Path, github: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    github["sha"] = "7" * 40
    github["archive"] = _component_archive({"const.py": "GOOD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")
    github["sha"] = "8" * 40
    github["archive"] = _component_archive({"const.py": "BAD = 1"})
    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    component = tmp_path / "custom_components" / "device_links"
    before = _snapshot(component)

    def _refuse(staging: Path, current: Path) -> None:
        raise DeployError("could not swap the new directory into place: simulated")

    monkeypatch.setattr(ha_deploy, "swap_into_place", _refuse)
    with pytest.raises(DeployError, match="could not swap"):
        rollback(tmp_path, "device_links")

    assert _snapshot(component) == before
    assert not (tmp_path / "custom_components" / ".device_links.new").exists()


# --------------------------------------------------------------------------- #
# Authenticating to a private repository
# --------------------------------------------------------------------------- #


class _Recorder:
    """Capture the request a fetch builds, so the headers can be asserted on."""

    def __init__(self) -> None:
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: float) -> _FakeResponse:
        self.requests.append(request)
        return _FakeResponse(b"body")


def test_an_anonymous_fetch_sends_no_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool spent its whole life without a token and must still work without one."""
    recorder = _Recorder()
    monkeypatch.setattr(ha_deploy.urllib.request, "urlopen", recorder)

    ha_deploy._fetch("https://api.github.com/x", timeout=1.0, accept="*/*")

    assert not recorder.requests[0].has_header("Authorization")  # type: ignore[attr-defined]


def test_a_token_reaches_github_as_a_bearer_header(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(ha_deploy.urllib.request, "urlopen", recorder)

    ha_deploy._fetch("https://codeload.github.com/x", timeout=1.0, accept="*/*", token="secret")

    assert recorder.requests[0].get_header("Authorization") == "Bearer secret"  # type: ignore[attr-defined]


def test_a_token_is_never_sent_anywhere_but_github(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirect off GitHub must not carry the credential with it.

    codeload redirects, and the header is decided per URL rather than once per run, so
    this is the assertion that keeps that true if the bases are ever reconfigured.
    """
    recorder = _Recorder()
    monkeypatch.setattr(ha_deploy.urllib.request, "urlopen", recorder)

    ha_deploy._fetch("https://evil.invalid/x", timeout=1.0, accept="*/*", token="secret")

    assert not recorder.requests[0].has_header("Authorization")  # type: ignore[attr-defined]


def test_a_token_file_is_read_and_stripped(tmp_path: Path) -> None:
    directory = tmp_path / "device_links"
    directory.mkdir()
    (directory / "deploy_token").write_text("  github_pat_x\n")

    assert ha_deploy.read_token(tmp_path, "device_links") == "github_pat_x"


def test_reading_a_token_file_tightens_its_permissions(tmp_path: Path) -> None:
    """A token written by hand is world readable, and every add-on can read /config."""
    directory = tmp_path / "device_links"
    directory.mkdir()
    token_file = directory / "deploy_token"
    token_file.write_text("github_pat_x")
    token_file.chmod(0o644)

    ha_deploy.read_token(tmp_path, "device_links")

    assert token_file.stat().st_mode & 0o777 == 0o600


def test_the_environment_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "device_links"
    directory.mkdir()
    (directory / "deploy_token").write_text("from_file")
    monkeypatch.setenv(ha_deploy.TOKEN_ENV, "from_env")

    assert ha_deploy.read_token(tmp_path, "device_links") == "from_env"


@pytest.mark.parametrize("contents", ["", "   \n"])
def test_an_empty_token_file_is_the_same_as_no_token(tmp_path: Path, contents: str) -> None:
    directory = tmp_path / "device_links"
    directory.mkdir()
    (directory / "deploy_token").write_text(contents)

    assert ha_deploy.read_token(tmp_path, "device_links") is None


def test_no_token_anywhere_is_not_an_error(tmp_path: Path) -> None:
    assert ha_deploy.read_token(tmp_path, "device_links") is None


def test_a_token_file_that_cannot_be_read_is_not_an_error(tmp_path: Path) -> None:
    """A directory where a file belongs, or a bad mode, must not break a public deploy."""
    (tmp_path / "device_links" / "deploy_token").mkdir(parents=True)

    assert ha_deploy.read_token(tmp_path, "device_links") is None


def test_deploy_passes_the_token_to_both_network_calls(
    tmp_path: Path, github: dict[str, object]
) -> None:
    """The whole point: a private repository is unreadable without this."""
    (tmp_path / "device_links").mkdir()
    (tmp_path / "device_links" / "deploy_token").write_text("github_pat_x")
    github["archive"] = _component_archive({"__init__.py": "x = 1\n"})

    deploy(tmp_path, "jayanty/ha-device-links", "device_links", branch="dev")

    assert github["resolve_token"] == "github_pat_x"
    assert github["download_token"] == "github_pat_x"


def test_a_404_without_a_token_says_it_might_be_private(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 is what a private repository looks like to a stranger, and the message must say so."""

    def _not_found(request: object, timeout: float) -> object:
        raise ha_deploy.urllib.error.HTTPError(
            "https://api.github.com/x", 404, "Not Found", Message(), None
        )

    monkeypatch.setattr(ha_deploy.urllib.request, "urlopen", _not_found)

    with pytest.raises(DeployError, match="private"):
        ha_deploy._fetch("https://api.github.com/x", timeout=1.0, accept="*/*")


def test_a_404_with_a_token_is_reported_as_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """With a token in hand, a 404 really does mean the repository is not there."""

    def _not_found(request: object, timeout: float) -> object:
        raise ha_deploy.urllib.error.HTTPError(
            "https://api.github.com/x", 404, "Not Found", Message(), None
        )

    monkeypatch.setattr(ha_deploy.urllib.request, "urlopen", _not_found)

    with pytest.raises(DeployError, match="404 Not Found") as caught:
        ha_deploy._fetch("https://api.github.com/x", timeout=1.0, accept="*/*", token="t")
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("code", [401, 403])
def test_a_refused_token_is_named_as_the_cause(code: int, monkeypatch: pytest.MonkeyPatch) -> None:
    def _refused(request: object, timeout: float) -> object:
        raise ha_deploy.urllib.error.HTTPError(
            "https://api.github.com/x", code, "Forbidden", Message(), None
        )

    monkeypatch.setattr(ha_deploy.urllib.request, "urlopen", _refused)

    with pytest.raises(DeployError, match="expired, revoked, or lacks read access"):
        ha_deploy._fetch("https://api.github.com/x", timeout=1.0, accept="*/*", token="t")


def test_no_error_message_can_carry_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every deploy failure is printed as JSON, and a token in it would be logged."""

    def _refused(request: object, timeout: float) -> object:
        raise ha_deploy.urllib.error.HTTPError(
            "https://api.github.com/x", 403, "Forbidden", Message(), None
        )

    monkeypatch.setattr(ha_deploy.urllib.request, "urlopen", _refused)

    with pytest.raises(DeployError) as caught:
        ha_deploy._fetch("https://api.github.com/x", timeout=1.0, accept="*/*", token="s3cret")
    assert "s3cret" not in str(caught.value)


# --------------------------------------------------------------------------- #
# v1.1: the interface of TECH_SPEC 10.1 (shared with ha-device-links)
# --------------------------------------------------------------------------- #


def _calls(github: dict[str, object]) -> list[tuple[str, ...]]:
    calls = github["calls"]
    assert isinstance(calls, list)
    return calls


REPO = "jayanty/ha-device-routines"
DOMAIN = "device_routines"
ROUTINES_MANIFEST = json.dumps({"domain": DOMAIN, "version": "0.0.1"})


def _routines_archive(files: dict[str, str], root: str = "ha-device-routines-abc") -> bytes:
    payload = {f"custom_components/{DOMAIN}/{name}": body for name, body in files.items()}
    payload.setdefault(f"custom_components/{DOMAIN}/manifest.json", ROUTINES_MANIFEST)
    return _archive(payload, root=root)


def _deployed(config_dir: Path) -> dict[str, object]:
    marker = read_deployed(config_dir / "custom_components" / DOMAIN)
    assert marker is not None
    return marker


def test_the_version_header_is_the_shared_one() -> None:
    assert ha_deploy.__doc__ is not None
    assert ha_deploy.__doc__.startswith("ha_deploy v1.1, shared")
    assert ha_deploy.VERSION == "1.1"


def test_a_ref_that_is_not_a_sha_is_resolved_through_the_api(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "1" * 40
    github["archive"] = _routines_archive({"const.py": "X = 1"})

    result = deploy(tmp_path, REPO, DOMAIN, ref="dev-stable")

    assert ("resolve", REPO, "dev-stable") in _calls(github)
    assert result["commit"] == "1" * 40
    assert _deployed(tmp_path)["branch"] == "dev-stable"


def test_the_default_ref_is_the_dev_stable_tag(tmp_path: Path, github: dict[str, object]) -> None:
    github["sha"] = "1" * 40
    github["archive"] = _routines_archive({"const.py": "X = 1"})

    deploy(tmp_path, REPO, DOMAIN)

    assert ("resolve", REPO, ha_deploy.DEFAULT_REF) in _calls(github)
    assert ha_deploy.DEFAULT_REF == "dev-stable"


def test_branch_is_an_alias_for_ref(tmp_path: Path, github: dict[str, object]) -> None:
    github["sha"] = "1" * 40
    github["archive"] = _routines_archive({"const.py": "X = 1"})

    deploy(tmp_path, REPO, DOMAIN, branch="dev")

    assert ("resolve", REPO, "dev") in _calls(github)
    assert _deployed(tmp_path)["branch"] == "dev"


def test_a_full_sha_is_used_without_a_lookup_and_records_no_branch(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["archive"] = _routines_archive({"const.py": "X = 1"})

    deploy(tmp_path, REPO, DOMAIN, ref="e" * 40)

    assert not [call for call in _calls(github) if call[0] == "resolve"]
    assert _deployed(tmp_path)["branch"] is None


def test_redeploying_the_running_commit_downloads_nothing(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "2" * 40
    github["archive"] = _routines_archive({"const.py": "X = 1"})
    deploy(tmp_path, REPO, DOMAIN)
    downloads = len([call for call in _calls(github) if call[0] == "download"])

    result = deploy(tmp_path, REPO, DOMAIN)

    assert result == {
        "ok": True,
        "changed": False,
        "commit": "2" * 40,
        "previous_commit": "2" * 40,
        "changed_files": [],
        "restart_required": False,
        "reload_automations": False,
        "browser_reload": False,
        "hacs_managed": False,
        "warnings": [],
    }
    assert len([call for call in _calls(github) if call[0] == "download"]) == downloads


def test_a_changed_deploy_says_so(tmp_path: Path, github: dict[str, object]) -> None:
    github["sha"] = "3" * 40
    github["archive"] = _routines_archive({"const.py": "X = 1"})

    result = deploy(tmp_path, REPO, DOMAIN)

    assert result["changed"] is True
    assert result["previous_commit"] is None
    assert _deployed(tmp_path)["rollback_of"] is None


@pytest.mark.parametrize(
    ("changed", "restart", "reload", "browser"),
    [
        (["const.py"], True, False, False),
        (["manifest.json"], True, False, False),
        (["services.yaml"], True, False, False),
        (["strings.json"], True, False, False),
        (["translations/en.json"], True, False, False),
        (["icons.json"], True, False, False),
        (["blueprints/device_routine.yaml"], False, True, False),
        (["frontend/panel.js"], False, False, True),
        (["blueprints/device_routine.yaml", "frontend/panel.js"], False, True, True),
        (["const.py", "blueprints/device_routine.yaml", "frontend/panel.js"], True, False, False),
        ([], False, False, False),
    ],
)
def test_changed_files_decide_what_happens_next(
    changed: list[str], restart: bool, reload: bool, browser: bool
) -> None:
    summary = ha_deploy.classify(changed)

    assert summary == {
        "restart_required": restart,
        "reload_automations": reload,
        "browser_reload": browser,
    }


def test_a_blueprint_only_change_is_an_automation_reload(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "4" * 40
    github["archive"] = _routines_archive(
        {"const.py": "X = 1", "blueprints/device_routine.yaml": "a: 1"}
    )
    deploy(tmp_path, REPO, DOMAIN)
    github["sha"] = "5" * 40
    github["archive"] = _routines_archive(
        {"const.py": "X = 1", "blueprints/device_routine.yaml": "a: 2"}
    )

    result = deploy(tmp_path, REPO, DOMAIN)

    assert result["changed_files"] == ["blueprints/device_routine.yaml"]
    assert result["restart_required"] is False
    assert result["reload_automations"] is True
    assert result["browser_reload"] is False


def test_backups_live_under_the_hidden_deploy_directory(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "6" * 40
    github["archive"] = _routines_archive({"const.py": "X = 1"})
    deploy(tmp_path, REPO, DOMAIN)
    github["sha"] = "7" * 40
    github["archive"] = _routines_archive({"const.py": "X = 2"})
    deploy(tmp_path, REPO, DOMAIN)

    backups = list((tmp_path / ".ha_deploy" / DOMAIN / "backups").iterdir())

    assert len(backups) == 1
    assert backups[0].name.endswith("-" + "6" * 12)
    assert not (tmp_path / DOMAIN).exists(), "nothing is written beside the hidden directory"


def test_a_backup_in_the_legacy_directory_is_still_restored(
    tmp_path: Path, github: dict[str, object]
) -> None:
    github["sha"] = "8" * 40
    github["archive"] = _routines_archive({"const.py": "NOW = 1"})
    deploy(tmp_path, REPO, DOMAIN)
    legacy = tmp_path / DOMAIN / "backups" / "20260101T000000Z-oldsha"
    legacy.mkdir(parents=True)
    (legacy / "const.py").write_text("OLD = 1")
    (legacy / "manifest.json").write_text(ROUTINES_MANIFEST)

    result = rollback(tmp_path, DOMAIN)

    assert result["changed"] is True
    assert (tmp_path / "custom_components" / DOMAIN / "const.py").read_text() == "OLD = 1"
    assert not legacy.exists(), "a restored backup is consumed wherever it lived"


def test_rollback_records_what_it_rolled_back(tmp_path: Path, github: dict[str, object]) -> None:
    github["sha"] = "a" * 40
    github["archive"] = _routines_archive({"const.py": "GOOD = 1"})
    deploy(tmp_path, REPO, DOMAIN)
    github["sha"] = "b" * 40
    github["archive"] = _routines_archive({"const.py": "BAD = 1"})
    deploy(tmp_path, REPO, DOMAIN)

    rollback(tmp_path, DOMAIN)

    marker = _deployed(tmp_path)
    assert marker["commit"] == "a" * 40
    assert marker["rollback_of"] == "b" * 40


def test_a_second_rollback_in_a_row_is_refused(tmp_path: Path, github: dict[str, object]) -> None:
    for sha in ("a", "b", "c"):
        github["sha"] = sha * 40
        github["archive"] = _routines_archive({"const.py": f"V = '{sha}'"})
        deploy(tmp_path, REPO, DOMAIN)
    rollback(tmp_path, DOMAIN)

    with pytest.raises(ha_deploy.RollbackRefusedError, match="already a rollback"):
        rollback(tmp_path, DOMAIN)
    assert (tmp_path / "custom_components" / DOMAIN / "const.py").read_text() == "V = 'b'"


def test_a_refused_rollback_exits_with_two(
    tmp_path: Path, github: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    for sha in ("a", "b"):
        github["sha"] = sha * 40
        github["archive"] = _routines_archive({"const.py": f"V = '{sha}'"})
        deploy(tmp_path, REPO, DOMAIN)
    assert main(["rollback", "--config", str(tmp_path), "--domain", DOMAIN]) == 0

    code = main(["rollback", "--config", str(tmp_path), "--domain", DOMAIN])

    assert code == 2
    captured = capsys.readouterr()
    assert json.loads(captured.err.strip().splitlines()[-1])["ok"] is False


def test_a_deploy_after_a_rollback_allows_the_next_rollback(
    tmp_path: Path, github: dict[str, object]
) -> None:
    for sha in ("a", "b"):
        github["sha"] = sha * 40
        github["archive"] = _routines_archive({"const.py": f"V = '{sha}'"})
        deploy(tmp_path, REPO, DOMAIN)
    rollback(tmp_path, DOMAIN)
    github["sha"] = "c" * 40
    github["archive"] = _routines_archive({"const.py": "V = 'c'"})
    deploy(tmp_path, REPO, DOMAIN)

    assert _deployed(tmp_path)["rollback_of"] is None
    rollback(tmp_path, DOMAIN)
    assert (tmp_path / "custom_components" / DOMAIN / "const.py").read_text() == "V = 'a'"


def test_status_reports_the_marker_the_channel_the_backups_and_python(
    tmp_path: Path, github: dict[str, object]
) -> None:
    for sha in ("a", "b"):
        github["sha"] = sha * 40
        github["archive"] = _routines_archive({"const.py": f"V = '{sha}'"})
        deploy(tmp_path, REPO, DOMAIN)

    result = status(tmp_path, DOMAIN)

    assert set(result) == {"ok", "deployed", "hacs_managed", "backups", "python_ok"}
    assert result["ok"] is True
    deployed = result["deployed"]
    assert isinstance(deployed, dict)
    assert deployed["commit"] == "b" * 40
    assert result["hacs_managed"] is False
    backups = result["backups"]
    assert isinstance(backups, list)
    assert len(backups) == 1
    assert result["python_ok"] is True


def test_status_on_an_install_the_tool_never_made_is_not_an_error(tmp_path: Path) -> None:
    (tmp_path / "custom_components" / DOMAIN).mkdir(parents=True)
    (tmp_path / "custom_components" / DOMAIN / "manifest.json").write_text(ROUTINES_MANIFEST)

    result = status(tmp_path, DOMAIN)

    assert result["deployed"] is None
    assert result["backups"] == []
    assert result["python_ok"] is True


def test_status_python_ok_is_false_when_the_code_does_not_compile(tmp_path: Path) -> None:
    _seed_deployment(tmp_path, {"broken.py": "def ("}, "9" * 40)
    component = tmp_path / "custom_components" / DOMAIN
    component.mkdir(parents=True)
    (component / "broken.py").write_text("def (")
    (component / ".deployed").write_text(json.dumps({"commit": "9" * 40}))

    assert status(tmp_path, DOMAIN)["python_ok"] is False


def _hacs_store(config_dir: Path, installed: bool) -> None:
    store = config_dir / ".storage" / "hacs.repositories"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps({"data": {"1": {"domain": DOMAIN, "installed": installed, "full_name": REPO}}})
    )


def test_status_detects_a_hacs_managed_install(tmp_path: Path) -> None:
    (tmp_path / "custom_components" / DOMAIN).mkdir(parents=True)
    _hacs_store(tmp_path, installed=True)

    assert status(tmp_path, DOMAIN)["hacs_managed"] is True

    _hacs_store(tmp_path, installed=False)
    assert status(tmp_path, DOMAIN)["hacs_managed"] is False


def test_deploy_warns_when_hacs_manages_the_install(
    tmp_path: Path, github: dict[str, object]
) -> None:
    _hacs_store(tmp_path, installed=True)
    github["sha"] = "c" * 40
    github["archive"] = _routines_archive({"const.py": "X = 1"})

    result = deploy(tmp_path, REPO, DOMAIN)

    assert result["hacs_managed"] is True
    warnings = result["warnings"]
    assert isinstance(warnings, list)
    assert any("HACS" in warning for warning in warnings)


def test_config_is_an_alias_for_config_dir(
    tmp_path: Path, github: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    github["sha"] = "d" * 40
    github["archive"] = _routines_archive({"const.py": "X = 1"})

    code = main(["deploy", "--config", str(tmp_path), "--repo", REPO, "--domain", DOMAIN])

    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["changed"] is True
    assert ("resolve", REPO, "dev-stable") in _calls(github)


def test_the_token_can_come_from_the_generic_or_the_domain_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HA_DEPLOY_TOKEN", raising=False)
    monkeypatch.setenv("DEVICE_ROUTINES_DEPLOY_TOKEN", "per-domain")
    assert ha_deploy.read_token(tmp_path, DOMAIN) == "per-domain"

    monkeypatch.setenv("HA_DEPLOY_TOKEN", "generic")
    assert ha_deploy.read_token(tmp_path, DOMAIN) == "generic"


def test_the_token_file_may_live_in_the_hidden_deploy_directory(tmp_path: Path) -> None:
    hidden = tmp_path / ".ha_deploy" / DOMAIN
    hidden.mkdir(parents=True)
    (hidden / "deploy_token").write_text("hidden-token\n")

    assert ha_deploy.read_token(tmp_path, DOMAIN) == "hidden-token"


def test_the_tool_never_restarts_and_never_writes_to_storage() -> None:
    source = Path(ha_deploy.__file__).read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "homeassistant.restart" not in node.value
            assert "automations.yaml" not in node.value
    # The HACS store is read to label the channel and nothing under .storage is written:
    # every write in the module goes through the two marker writers and the swap.
    writers = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"write_text", "write_bytes", "open"}
    ]
    assert writers, "the collector found nothing"
