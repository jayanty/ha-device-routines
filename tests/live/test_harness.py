"""The live suite's own harness, proven without an instance. Runs in CI with every test.

Live finding F5: under the Home Assistant test plugin no live test could open a socket. A
separate pytest session, the plugin loaded as in every run, runs a few tests against this
folder's conftest: tests marked `live` reach a server on this machine by host name, every
other test keeps the plugin's guard, and with no `local/live.env` the `live` fixture
skips. That session's settings point at a file that does not exist, so it never reaches an
instance, whatever this clone holds.

Live finding F6: the tags Health's commit is checked against, read from a scratch
repository.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from tests.live.conftest import (
    MANIFEST,
    REPO,
    deployed_versions,
    git,
    manifest_version,
    release_version,
    tags_at,
)

INNER = '''
"""Run in a separate session by tests/live/test_harness.py."""

import json
from pathlib import Path
import socket
import socketserver
import threading
import http.server

import pytest

from tests.live import conftest
from tests.live.conftest import Live

# This session must never reach an instance: its settings file does not exist.
conftest.ENV = Path(__file__).with_name("live.env")


def test_the_plugin_runs_this_session(pytestconfig):
    assert pytestconfig.pluginmanager.has_plugin("homeassistant")


class Answer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        answer = {"path": self.path, "authorization": self.headers["Authorization"]}
        body = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


@pytest.mark.live
def test_a_live_test_reaches_a_server_by_host_name():
    server = socketserver.TCPServer(("127.0.0.1", 0), Answer)
    server.timeout = 10
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        answer = Live(f"http://localhost:{server.server_address[1]}", "token").get("/api/")
    finally:
        thread.join(10)
        server.server_close()
    assert answer == {"path": "/api/", "authorization": "Bearer token"}


@pytest.mark.live
def test_a_live_test_looks_names_up_and_connects_by_name():
    # The plugin refuses this lookup itself; the real resolver says it is not a number.
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("instance.invalid", 8123, flags=socket.AI_NUMERICHOST)
    # The plugin lets `connect` reach 127.0.0.1 only, never a host name.
    with socket.create_server(("127.0.0.1", 0)) as server, socket.socket() as client:
        client.connect(("localhost", server.getsockname()[1]))


def test_every_other_test_keeps_the_plugin_guard():
    with pytest.raises(RuntimeError):
        socket.getaddrinfo("instance.invalid", 8123, flags=socket.AI_NUMERICHOST)


@pytest.mark.live
def test_without_settings_the_live_fixture_skips(live):
    raise AssertionError("the live fixture skips without local/live.env")
'''


def _environment() -> dict[str, str]:
    """The environment without what the outer pytest and git set for themselves."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTEST_", "COV_CORE_", "GIT_"))
    }


# --------------------------------------------------------------------------------------
# F5: the network under the plugin
# --------------------------------------------------------------------------------------


def test_live_tests_get_the_network_under_the_plugin_and_skip_without_settings(
    tmp_path: Path,
) -> None:
    inner = tmp_path / "test_inner.py"
    inner.write_text(INNER, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.live.conftest",
            "-p",
            "no:cacheprovider",
            "-c",
            str(REPO / "pyproject.toml"),
            "-rs",
            str(inner),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=_environment(),
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    counts = {kind: int(n) for n, kind in re.findall(r"(\d+) (passed|skipped|failed)", output)}
    assert counts == {"passed": 4, "skipped": 1}, output
    assert "local/live.env is missing" in output, output


# --------------------------------------------------------------------------------------
# F6: what the instance is deployed from
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("v1.0.0-beta.2", "1.0.0"),
        ("v0.3.0", "0.3.0"),
        ("v1.2.3-rc.1", "1.2.3"),
        ("dev-stable", None),
        ("v1.0", None),
        ("1.0.0", None),
        ("v1.0.0-", None),
    ],
)
def test_a_release_tag_names_its_version_without_the_pre_release_suffix(
    tag: str, version: str | None
) -> None:
    assert release_version(tag) == version


@pytest.mark.parametrize(
    ("tags", "manifest", "versions"),
    [
        (["v1.0.0-beta.2"], "1.0.0", {"1.0.0"}),
        (["dev-stable", "v1.0.0", "v1.0.0-beta.2"], "1.0.0", {"1.0.0"}),
        # A release tag is the deploy; a manifest that disagrees with it fails the check.
        (["v0.3.0"], "9.9.9", {"0.3.0"}),
        # `dev-stable` alone names no version: the manifest at the commit does.
        (["dev-stable"], "1.0.0", {"1.0.0"}),
        (["dev-stable"], None, set()),
        (["some-branch-tag"], "1.0.0", set()),
        ([], "1.0.0", set()),
    ],
)
def test_the_versions_a_deployed_commit_may_run(
    tags: list[str], manifest: str | None, versions: set[str]
) -> None:
    assert deployed_versions(tags, manifest) == versions


def test_the_tags_and_the_manifest_are_read_from_the_clone(tmp_path: Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "tag.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                *args,
            ],
            check=True,
            capture_output=True,
            env=_environment(),
        )

    run("init", "-q")
    manifest = tmp_path / MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"domain": "device_routines", "version": "1.2.3"}', encoding="utf-8")
    run("add", ".")
    run("commit", "-q", "-m", "release")
    run("tag", "-a", "v1.2.3-beta.4", "-m", "beta")
    run("tag", "dev-stable")
    commit = (git("rev-parse", "HEAD", repo=tmp_path) or "").strip()

    assert tags_at(commit, repo=tmp_path) == ["dev-stable", "v1.2.3-beta.4"]
    assert manifest_version(commit, repo=tmp_path) == "1.2.3"
    # A commit the clone does not have names no tag and no manifest.
    unknown = "0" * 40
    assert tags_at(unknown, repo=tmp_path) == []
    assert manifest_version(unknown, repo=tmp_path) is None
