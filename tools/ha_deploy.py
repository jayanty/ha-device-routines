"""ha_deploy v1.1, shared between ha-device-links and ha-device-routines.

Pull based deploy tool: GitHub to Home Assistant. Runs on the Home Assistant host, inside
the Core container, using the standard library only, because nothing else is guaranteed to
be importable there. Nothing is ever copied from a laptop into `/config`: this tool downloads
the immutable archive for one commit, verifies it, byte compiles it and swaps it into place,
so the deployed directory is always traceable to a commit.

The properties this module exists to guarantee:

- Any failure, at any step, leaves the currently deployed directory exactly as it was.
- Nothing from the archive is ever executed, and only `custom_components/<domain>` is
  extracted from it.
- Home Assistant is never restarted and no config entry is ever reloaded. Python code loads
  on a restart, which is a human decision, so the tool only reports that one is needed.
- Nothing outside `custom_components/<domain>` and `<config>/.ha_deploy/<domain>` is
  written or deleted. The HACS store is read, never written, to label a HACS managed install.
- A ref that is already deployed changes nothing: the tool is idempotent.

Usage:

    python3 ha_deploy.py deploy   --domain <domain> --repo owner/name [--ref dev-stable]
    python3 ha_deploy.py rollback --domain <domain>
    python3 ha_deploy.py status   --domain <domain>

`--ref` takes a tag, a branch or a commit sha and defaults to the `dev-stable` tag that CI
moves on green; `--branch` is kept as an alias. `--config` (or `--config-dir`) defaults to
`/config`.

On success one JSON object is printed to stdout. On failure a JSON object with
`{"ok": false, "error": ...}` is printed to stderr and the exit code is 1, or 2 when a
rollback is refused because the last operation was already a rollback. Stdout is therefore
always either empty or a single parseable success object.
"""

from __future__ import annotations

import argparse
import compileall
import contextlib
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import TYPE_CHECKING
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if TYPE_CHECKING:
    from collections.abc import Sequence

VERSION = "1.1"
API_BASE = "https://api.github.com"
CODELOAD_BASE = "https://codeload.github.com"
USER_AGENT = f"ha-deploy/{VERSION}"
DEFAULT_REF = "dev-stable"

# A private repository answers an anonymous request with 404 rather than 401, so a token is
# what makes the difference between "deploy works" and "that repo does not exist". It comes
# from the environment (the generic name, then `<DOMAIN>_DEPLOY_TOKEN`), or from a file the
# owner writes once on the host. It is never a command line argument: an argument would land
# in the shell history, in the `shell_command` block and in the process list. A public
# repository needs no token at all.
TOKEN_ENV = "HA_DEPLOY_TOKEN"  # noqa: S105
TOKEN_FILENAME = "deploy_token"  # noqa: S105

# The only hosts an Authorization header is ever attached to. Checked per request rather
# than once at the start: `codeload` redirects, and a token must not follow it off GitHub.
TOKEN_HOSTS = frozenset({"api.github.com", "codeload.github.com"})

HTTP_NOT_FOUND = 404
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403

BACKUPS_TO_KEEP = 5
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
API_TIMEOUT = 30.0
DOWNLOAD_TIMEOUT = 180.0

DEPLOYED_FILENAME = ".deployed"
DEPLOY_DIRNAME = ".ha_deploy"
BLUEPRINTS_PREFIX = "blueprints/"
FRONTEND_PREFIX = "frontend/"

# HACS records what it installed here. Read only, and only to warn: deploying over a HACS
# managed install would be undone by the next HACS update.
HACS_STORE = Path(".storage") / "hacs.repositories"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2

_REPO_RE = re.compile(r"\A[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}\Z")
_SHA_RE = re.compile(r"\A[0-9a-fA-F]{7,40}\Z")
_FULL_SHA_RE = re.compile(r"\A[0-9a-fA-F]{40}\Z")
_BRANCH_RE = re.compile(r"\A[A-Za-z0-9._/-]{1,200}\Z")
_UNIX_CREATE_SYSTEM = 3
_SYMLINK_MODE = 0o120000
_FILE_TYPE_MASK = 0o170000
_IGNORED_SUFFIXES = (".pyc", ".pyo")


class DeployError(RuntimeError):
    """A deploy step refused to continue. The deployed directory is untouched."""


class RollbackRefusedError(DeployError):
    """The last operation was already a rollback; a second one needs a deploy in between."""


# --------------------------------------------------------------------------- #
# Argument validation
# --------------------------------------------------------------------------- #


def check_repo(repo: str) -> str:
    """Return `owner/name` unchanged, refusing anything that could reshape a URL."""
    owner, _, name = repo.partition("/")
    if not _REPO_RE.match(repo) or owner in {".", ".."} or name in {".", ".."}:
        raise DeployError(f"--repo must look like owner/name, got {repo!r}")
    return repo


def check_sha(ref: str) -> str:
    """Return a lowercased commit sha, refusing anything that is not one."""
    if not _SHA_RE.match(ref):
        raise DeployError(f"--ref must be a commit sha, got {ref!r}")
    return ref.lower()


def check_branch(branch: str) -> str:
    """Return a ref name, refusing characters that do not belong in one."""
    if not _BRANCH_RE.match(branch):
        raise DeployError(f"--ref is not a valid ref name, got {branch!r}")
    return branch


def require_https(url: str) -> str:
    """Return the URL unchanged, refusing anything that is not HTTPS."""
    if not url.lower().startswith("https://"):
        raise DeployError(f"refusing a non-https URL: {url}")
    return url


# --------------------------------------------------------------------------- #
# Network: the only two calls this tool makes
# --------------------------------------------------------------------------- #


def _token_paths(config_dir: Path, domain: str) -> list[Path]:
    """Where a token file may live: the hidden deploy directory, then the legacy one."""
    return [
        config_dir / DEPLOY_DIRNAME / domain / TOKEN_FILENAME,
        config_dir / domain / TOKEN_FILENAME,
    ]


def read_token(config_dir: Path, domain: str) -> str | None:
    """Return the GitHub token to authenticate with, or None to stay anonymous.

    The environment wins, so a one off deploy can pass a token without writing one to disk;
    the generic variable beats the per domain one. Otherwise the token file is read. A
    missing file is not an error: a public repository needs no token at all.
    """
    for variable in (TOKEN_ENV, f"{domain.upper()}_DEPLOY_TOKEN"):
        from_env = os.environ.get(variable, "").strip()
        if from_env:
            return from_env
    for path in _token_paths(Path(config_dir), domain):
        try:
            contents = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        _restrict(path)
        token = contents.strip()
        if token:
            return token
    return None


def _restrict(path: Path) -> None:
    """Take a token file down to owner only, because every app can read /config."""
    with contextlib.suppress(OSError):
        if path.stat().st_mode & 0o077:
            path.chmod(0o600)


def _authorized(url: str, token: str | None) -> dict[str, str]:
    """Build the headers for one request, attaching the token only to GitHub itself."""
    headers = {"User-Agent": USER_AGENT}
    if token and urllib.parse.urlsplit(url).hostname in TOKEN_HOSTS:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch(url: str, *, timeout: float, accept: str, token: str | None = None) -> bytes:
    """Fetch a URL over HTTPS, capped so a runaway response cannot fill /config."""
    require_https(url)
    headers = _authorized(url, token) | {"Accept": accept}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload: bytes = response.read(MAX_ARCHIVE_BYTES + 1)
    except urllib.error.HTTPError as err:
        raise DeployError(f"cannot fetch {url}: {_explain(err, token)}") from err
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise DeployError(f"cannot fetch {url}: {err}") from err
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise DeployError(f"refusing a response larger than {MAX_ARCHIVE_BYTES} bytes: {url}")
    return payload


def _explain(err: urllib.error.HTTPError, token: str | None) -> str:
    """Turn GitHub's status into the sentence that says what to do about it."""
    if err.code == HTTP_NOT_FOUND and token is None:
        return (
            "404 not found. If the repository is private this is what that looks like "
            f"without a token: set {TOKEN_ENV}, or write a token with read access to "
            f"repository contents into <config>/{DEPLOY_DIRNAME}/<domain>/{TOKEN_FILENAME}"
        )
    if err.code in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN) and token is not None:
        return (
            f"{err.code} {err.reason}. The token was sent and refused, so it is expired, "
            "revoked, or lacks read access to this repository's contents"
        )
    return f"{err.code} {err.reason}"


def resolve_commit(repo: str, ref: str, token: str | None = None) -> str:
    """Resolve a branch, tag or short sha to the full commit sha it names right now."""
    check_repo(repo)
    quoted = urllib.parse.quote(check_branch(ref), safe="")
    url = f"{API_BASE}/repos/{repo}/commits/{quoted}"
    raw = _fetch(url, timeout=API_TIMEOUT, accept="application/vnd.github+json", token=token)
    try:
        document: object = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise DeployError(f"the GitHub API returned something that is not JSON: {err}") from err
    sha = document.get("sha") if isinstance(document, dict) else None
    if not isinstance(sha, str) or not _SHA_RE.match(sha):
        raise DeployError(f"the GitHub API did not return a commit sha for {repo}@{ref}")
    return sha.lower()


def download_archive(repo: str, sha: str, token: str | None = None) -> bytes:
    """Download the immutable zip archive for exactly one commit."""
    check_repo(repo)
    url = f"{CODELOAD_BASE}/{repo}/zip/{check_sha(sha)}"
    return _fetch(url, timeout=DOWNLOAD_TIMEOUT, accept="application/zip", token=token)


# --------------------------------------------------------------------------- #
# Archive verification and extraction
# --------------------------------------------------------------------------- #


def verify_archive(archive: zipfile.ZipFile, domain: str) -> str:
    """Check the archive holds one root directory containing the expected component.

    Returns the name of that root directory. The repository is pinned by the command line,
    so the only thing trusted from the archive is that it looks like what was asked for.
    """
    names = [name for name in archive.namelist() if name.strip()]
    if not names:
        raise DeployError("the archive is empty")

    roots = {name.split("/", 1)[0] for name in names}
    if len(roots) != 1:
        raise DeployError(
            f"expected exactly one top level directory in the archive, found {sorted(roots)}"
        )
    root = next(iter(roots))

    manifest_name = f"{root}/custom_components/{domain}/manifest.json"
    if manifest_name not in names:
        raise DeployError(f"the archive has no custom_components/{domain}/manifest.json")
    try:
        manifest: object = json.loads(archive.read(manifest_name).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise DeployError(f"manifest.json is not valid JSON: {err}") from err

    declared = manifest.get("domain") if isinstance(manifest, dict) else None
    if declared != domain:
        raise DeployError(f"manifest.json declares domain {declared!r}, expected {domain!r}")
    return root


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """Report whether a zip entry claims to be a symlink."""
    mode = (info.external_attr >> 16) & _FILE_TYPE_MASK
    return info.create_system == _UNIX_CREATE_SYSTEM and mode == _SYMLINK_MODE


def extract_component(archive: zipfile.ZipFile, root: str, domain: str, target: Path) -> None:
    """Extract only `<root>/custom_components/<domain>/` into `target`.

    Every entry is validated before any of them is written, so an archive with a bad entry
    leaves no partial tree behind.
    """
    prefix = f"{root}/custom_components/{domain}/"
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    base = target.resolve()

    planned: list[tuple[zipfile.ZipInfo, Path]] = []
    for info in archive.infolist():
        if not info.filename.startswith(prefix):
            continue
        relative = info.filename[len(prefix) :]
        if not relative:
            continue
        if _is_symlink(info):
            raise DeployError(f"refusing a symlink entry in the archive: {info.filename}")
        destination = (base / relative).resolve()
        if base not in destination.parents:
            raise DeployError(f"archive entry escapes the target directory: {info.filename}")
        planned.append((info, destination))

    if not planned:
        raise DeployError(f"the archive has no files under custom_components/{domain}/")

    for info, destination in planned:
        if info.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, destination.open("wb") as sink:
            shutil.copyfileobj(source, sink)


def compile_tree(root: Path) -> None:
    """Byte compile an extracted tree, refusing to continue on a syntax error.

    This runs before anything is swapped, so a commit that cannot even be parsed can never
    reach a running Home Assistant. `compileall` writes its diagnostics to stdout, which is
    captured here to keep the tool's own stdout a single JSON object.
    """
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        compiled = compileall.compile_dir(str(root), quiet=1, force=True, workers=1)
    for cache in list(root.rglob("__pycache__")):
        shutil.rmtree(cache, ignore_errors=True)
    if not compiled:
        raise DeployError(f"the downloaded code does not compile:\n{captured.getvalue().strip()}")


def python_ok(root: Path) -> bool:
    """Report whether every Python file under `root` parses, writing nothing."""
    for path in sorted(root.rglob("*.py")):
        try:
            compile(path.read_bytes(), str(path), "exec")
        except SyntaxError, ValueError, OSError:
            return False
    return True


# --------------------------------------------------------------------------- #
# Hashing and the changed file list
# --------------------------------------------------------------------------- #


def _is_ignored(relative: str) -> bool:
    """Report whether a path is runtime noise rather than deployed content."""
    parts = relative.split("/")
    return (
        "__pycache__" in parts
        or parts[-1] == DEPLOYED_FILENAME
        or parts[-1].endswith(_IGNORED_SUFFIXES)
    )


def hash_tree(root: Path) -> dict[str, str]:
    """Map every deployable file under `root` to the sha256 of its bytes."""
    hashes: dict[str, str] = {}
    if not root.is_dir():
        return hashes
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if _is_ignored(relative):
            continue
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def diff_trees(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """List every path added, removed, or changed between two hash maps."""
    return sorted({name for name in before | after if before.get(name) != after.get(name)})


def classify(changed_files: list[str]) -> dict[str, bool]:
    """Say what the changed files mean for the running instance.

    Python, the manifest, services, strings and translations, and anything else the
    integration reads at startup, need a restart. A change touching only blueprints is an
    automation reload; one touching only the frontend bundle is a browser reload. A restart
    covers both, so the two lighter flags are only set when no restart is needed.
    """
    blueprints = any(name.startswith(BLUEPRINTS_PREFIX) for name in changed_files)
    frontend = any(name.startswith(FRONTEND_PREFIX) for name in changed_files)
    restart = any(
        not name.startswith((BLUEPRINTS_PREFIX, FRONTEND_PREFIX)) for name in changed_files
    )
    return {
        "restart_required": restart,
        "reload_automations": blueprints and not restart,
        "browser_reload": frontend and not restart,
    }


# --------------------------------------------------------------------------- #
# The deployed marker and the HACS store
# --------------------------------------------------------------------------- #


def read_deployed(component_dir: Path) -> dict[str, object] | None:
    """Read the `.deployed` marker, or None when this directory has no usable one."""
    marker = component_dir / DEPLOYED_FILENAME
    if not marker.is_file():
        return None
    try:
        document: object = json.loads(marker.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return None
    if not isinstance(document, dict):
        return None
    return {str(key): value for key, value in document.items()}


def _commit_of(marker: dict[str, object] | None) -> str | None:
    """Pull the commit out of a marker, tolerating a missing or damaged one."""
    if marker is None:
        return None
    commit = marker.get("commit")
    return commit if isinstance(commit, str) else None


def _marker(
    *,
    commit: str,
    branch: str | None,
    previous_commit: str | None,
    changed_files: list[str],
    rollback_of: str | None = None,
) -> dict[str, object]:
    """Build the marker the Health sensor reads to report the running commit."""
    return {
        "commit": commit,
        "branch": branch,
        "deployed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "previous_commit": previous_commit,
        "changed_files": changed_files,
        "rollback_of": rollback_of,
    }


def _write_deployed(component_dir: Path, marker: dict[str, object]) -> None:
    """Write the marker next to the deployed code."""
    (component_dir / DEPLOYED_FILENAME).write_text(
        json.dumps(marker, indent=2) + "\n", encoding="utf-8"
    )


def hacs_manages(config_dir: Path, domain: str) -> bool:
    """Report whether the HACS store says it installed this domain. Read only."""
    try:
        document: object = json.loads((config_dir / HACS_STORE).read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return False
    repositories = document.get("data") if isinstance(document, dict) else None
    if not isinstance(repositories, dict):
        return False
    return any(
        isinstance(entry, dict) and entry.get("domain") == domain and bool(entry.get("installed"))
        for entry in repositories.values()
    )


# --------------------------------------------------------------------------- #
# Backups and the atomic swap
# --------------------------------------------------------------------------- #


def backups_root(config_dir: Path, domain: str) -> Path:
    """Where new backups go: a hidden directory that no integration reads."""
    return config_dir / DEPLOY_DIRNAME / domain / "backups"


def legacy_backups_root(config_dir: Path, domain: str) -> Path:
    """Where v1 of this tool kept backups; still read so an older install can roll back."""
    return config_dir / domain / "backups"


def create_backup(current: Path, backups_root: Path, previous_commit: str | None) -> Path:
    """Copy the currently deployed directory into the backups directory."""
    backups_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}-{(previous_commit or 'unknown')[:12]}"
    destination = backups_root / base
    counter = 1
    while destination.exists():
        counter += 1
        destination = backups_root / f"{base}.{counter}"
    shutil.copytree(current, destination, symlinks=True)
    return destination


def list_backups(backups_root: Path) -> list[Path]:
    """List backup directories oldest first. Names start with a sortable timestamp."""
    if not backups_root.is_dir():
        return []
    return sorted((path for path in backups_root.iterdir() if path.is_dir()), key=lambda p: p.name)


def all_backups(config_dir: Path, domain: str) -> list[Path]:
    """List every backup, current and legacy location together, oldest first."""
    found = list_backups(backups_root(config_dir, domain)) + list_backups(
        legacy_backups_root(config_dir, domain)
    )
    return sorted(found, key=lambda p: p.name)


def prune_backups(backups_root: Path, keep: int = BACKUPS_TO_KEEP) -> list[str]:
    """Delete all but the `keep` most recent backups, returning the names removed."""
    existing = list_backups(backups_root)
    removed: list[str] = []
    for path in existing[: max(len(existing) - keep, 0)]:
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    return removed


def _reset(path: Path) -> None:
    """Clear a staging path left behind by an earlier interrupted run."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def swap_into_place(staging: Path, current: Path) -> None:
    """Rename the current directory away and the new one into place.

    Two renames within one directory, so the window in which `current` does not exist is as
    short as the filesystem can make it. If the second rename fails, the previous directory
    is put straight back.
    """
    retired = current.with_name(f".{current.name}.previous")
    _reset(retired)
    had_current = current.is_dir()
    if had_current:
        current.rename(retired)
    try:
        staging.rename(current)
    except OSError as err:
        if had_current:
            retired.rename(current)
        raise DeployError(f"could not swap the new directory into place: {err}") from err
    if had_current:
        shutil.rmtree(retired, ignore_errors=True)


def _summary(
    *,
    changed: bool,
    commit: str | None,
    previous_commit: str | None,
    changed_files: list[str],
    hacs_managed: bool,
) -> dict[str, object]:
    """Build the single JSON object `deploy` and `rollback` print."""
    warnings: list[str] = []
    if hacs_managed:
        warnings.append(
            "HACS manages this install: the next HACS update will replace what was deployed"
        )
    return {
        "ok": True,
        "changed": changed,
        "commit": commit,
        "previous_commit": previous_commit,
        "changed_files": changed_files,
        **classify(changed_files),
        "hacs_managed": hacs_managed,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #


def deploy(
    config_dir: Path,
    repo: str,
    domain: str,
    *,
    branch: str | None = None,
    ref: str | None = None,
) -> dict[str, object]:
    """Deploy one commit from GitHub into `<config>/custom_components/<domain>`.

    `ref` (or its alias `branch`) is a tag, a branch or a commit sha; a full sha is used
    as it is, anything else is resolved through the GitHub API. Every failure raises
    `DeployError` after removing the staging directory, leaving the currently deployed
    directory exactly as it was.
    """
    check_repo(repo)
    wanted = ref if ref is not None else branch
    if wanted is None:
        wanted = DEFAULT_REF

    config_dir = Path(config_dir)
    token = read_token(config_dir, domain)
    if _FULL_SHA_RE.match(wanted):
        commit, ref_name = wanted.lower(), None
    else:
        ref_name = check_branch(wanted)
        commit = resolve_commit(repo, ref_name, token)
    current = config_dir / "custom_components" / domain
    staging = config_dir / "custom_components" / f".{domain}.new"
    backups = backups_root(config_dir, domain)
    hacs_managed = hacs_manages(config_dir, domain)

    previous_commit = _commit_of(read_deployed(current))
    if previous_commit == commit:
        return _summary(
            changed=False,
            commit=commit,
            previous_commit=previous_commit,
            changed_files=[],
            hacs_managed=hacs_managed,
        )

    payload = download_archive(repo, commit, token)

    _reset(staging)
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            root = verify_archive(archive, domain)
            extract_component(archive, root, domain, staging)
        compile_tree(staging)

        changed_files = diff_trees(hash_tree(current), hash_tree(staging))
        if current.is_dir():
            create_backup(current, backups, previous_commit)
            prune_backups(backups)

        _write_deployed(
            staging,
            _marker(
                commit=commit,
                branch=ref_name,
                previous_commit=previous_commit,
                changed_files=changed_files,
            ),
        )
        swap_into_place(staging, current)
    except DeployError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile) as err:
        shutil.rmtree(staging, ignore_errors=True)
        raise DeployError(f"deploy aborted, nothing was swapped into place: {err}") from err

    return _summary(
        changed=True,
        commit=commit,
        previous_commit=previous_commit,
        changed_files=changed_files,
        hacs_managed=hacs_managed,
    )


def rollback(config_dir: Path, domain: str) -> dict[str, object]:
    """Restore the newest backup using the same atomic swap `deploy` uses.

    The backup that is restored is consumed. A rollback right after a rollback is refused:
    a deploy must happen in between, so a post restart check cannot loop.
    """
    config_dir = Path(config_dir)
    current = config_dir / "custom_components" / domain
    staging = config_dir / "custom_components" / f".{domain}.new"

    marker = read_deployed(current)
    if marker is not None and isinstance(marker.get("rollback_of"), str):
        raise RollbackRefusedError(
            f"the last operation on {domain} was already a rollback; deploy before rolling "
            "back again"
        )
    backups = all_backups(config_dir, domain)
    if not backups:
        raise DeployError(f"there is no backup to roll {domain} back to")
    newest = backups[-1]

    replaced_commit = _commit_of(marker)
    _reset(staging)
    try:
        shutil.copytree(newest, staging, symlinks=True)
        changed_files = diff_trees(hash_tree(current), hash_tree(staging))
        restored = read_deployed(staging)
        restored_commit = _commit_of(restored)
        restored_branch = restored.get("branch") if restored else None
        _write_deployed(
            staging,
            _marker(
                commit=restored_commit or "unknown",
                branch=restored_branch if isinstance(restored_branch, str) else None,
                previous_commit=replaced_commit,
                changed_files=changed_files,
                rollback_of=replaced_commit or "unknown",
            ),
        )
        swap_into_place(staging, current)
    except DeployError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except OSError as err:
        shutil.rmtree(staging, ignore_errors=True)
        raise DeployError(f"rollback aborted, nothing was swapped into place: {err}") from err

    shutil.rmtree(newest, ignore_errors=True)
    return _summary(
        changed=True,
        commit=restored_commit,
        previous_commit=replaced_commit,
        changed_files=changed_files,
        hacs_managed=hacs_manages(config_dir, domain),
    )


def status(config_dir: Path, domain: str) -> dict[str, object]:
    """Report the deployed marker, the channel, the backups and whether the code parses."""
    config_dir = Path(config_dir)
    component = config_dir / "custom_components" / domain
    if not component.is_dir():
        raise DeployError(f"{domain} is not installed at {component}")
    return {
        "ok": True,
        "deployed": read_deployed(component),
        "hacs_managed": hacs_manages(config_dir, domain),
        "backups": [path.name for path in all_backups(config_dir, domain)],
        "python_ok": python_ok(component),
    }


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the three subcommands."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config",
        "--config-dir",
        dest="config_dir",
        type=Path,
        default=Path("/config"),
        help="Home Assistant configuration directory (default: /config)",
    )
    common.add_argument("--domain", required=True, help="integration domain")

    parser = argparse.ArgumentParser(
        prog="ha_deploy.py",
        description="Deploy a custom integration from GitHub to Home Assistant.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    deploy_parser = subcommands.add_parser("deploy", parents=[common], help="deploy one ref")
    deploy_parser.add_argument("--repo", required=True, help="GitHub repository as owner/name")
    deploy_parser.add_argument(
        "--ref", "--branch", dest="ref", help=f"tag, branch or commit sha (default: {DEFAULT_REF})"
    )

    subcommands.add_parser("rollback", parents=[common], help="restore the newest backup")
    subcommands.add_parser("status", parents=[common], help="print the deployed marker")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand, printing one JSON object and returning an exit code."""
    args = build_parser().parse_args(argv)
    config_dir: Path = args.config_dir
    domain: str = args.domain
    try:
        if args.command == "deploy":
            result = deploy(config_dir, args.repo, domain, ref=args.ref)
        elif args.command == "rollback":
            result = rollback(config_dir, domain)
        else:
            result = status(config_dir, domain)
    except RollbackRefusedError as err:
        print(json.dumps({"ok": False, "error": str(err)}), file=sys.stderr)
        return EXIT_REFUSED
    except DeployError as err:
        print(json.dumps({"ok": False, "error": str(err)}), file=sys.stderr)
        return EXIT_FAILED
    print(json.dumps(result))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
