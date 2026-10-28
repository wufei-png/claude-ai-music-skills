"""Regression checks for model evidence attribution and session persistence."""

import contextlib
import importlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def probe(monkeypatch, project_root):
    monkeypatch.syspath_prepend(str(project_root / "tests/e2e"))
    return importlib.import_module("codex_session_resume_check")


def tool_event(tool, arguments=None, *, payload=None, server="bitwize-music-mcp"):
    if payload is None:
        payload = {"status": "ok"} if tool == "health_check" else {}
    return {"type": "item.completed", "item": {
        "type": "mcp_tool_call", "server": server, "tool": tool, "arguments": arguments or {},
        "status": "completed", "error": None,
        "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
    }}


def answer_event(answer):
    return {"type": "item.completed", "item": {"type": "agent_message", "text": answer}}


def run_model_stub(probe, monkeypatch, home, mode):
    """Run both model turns with synthetic CLI events and real temporary state."""
    state_file = home / ".bitwize-music/cache/state.json"
    state_file.parent.mkdir(parents=True)
    session = {"last_album": probe.ALBUM, "last_phase": "Source Verification", "updated_at": "before"}
    state_file.write_text(json.dumps({"session": session}), encoding="utf-8")
    arguments = {"album": probe.ALBUM, "phase": "Source Verification"}
    required = [tool_event(tool) for tool in ("get_session", "find_album", "get_album_progress", "list_tracks")]
    recommendation = answer_event("Probe Album: $bitwize-music:verify-sources")
    # Startup has all the old checker's evidence; resume must still stand alone.
    startup = [tool_event("health_check", {"runtime": "codex"}), *required,
               tool_event("update_session", arguments), recommendation]
    if mode == "startup_health_missing":
        startup = startup[1:]
    resume = [*required, tool_event("update_session", arguments), recommendation]
    if mode == "no_resume":
        resume = [answer_event("I cannot resume the album or update the session.")]
    elif mode == "borrowed_recommendation":
        resume[-1] = answer_event("Resume completed.")
    elif mode == "clear":
        resume[-2] = tool_event("update_session", {"clear": True})

    turns = iter([startup, resume])
    started = []

    class FakeProcess:
        pid = 9999999
        returncode = 0

        def __init__(self, *args, **kwargs):
            self.events = next(turns)
            started.append(args[0])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def communicate(self, timeout):
            if len(started) == 2 and mode != "unchanged":
                saved = {**session, "updated_at": "after"}
                if mode == "wrong_album":
                    saved["last_album"] = "another-album"
                elif mode == "wrong_phase":
                    saved["last_phase"] = "Writing"
                state_file.write_text(json.dumps({"session": saved}), encoding="utf-8")
            return "\n".join(json.dumps(e) for e in self.events), ""

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(probe.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(probe.os, "killpg", lambda *args: None, raising=False)
    probe.check_model("fake-codex", home, {"HOME": str(home), "CODEX_HOME": str(home)}, home)
    return started


@pytest.mark.parametrize("mode, message", [
    ("no_resume", "Resume missed workflow tools"),
    ("borrowed_recommendation", "Resume missed album/source gate"),
    ("clear", "Resume did not update the expected album and phase"),
    ("unchanged", "Resume session update was not persisted"),
    ("wrong_album", "Resume persisted the wrong album or phase"),
    ("wrong_phase", "Resume persisted the wrong album or phase"),
    ("startup_health_missing", "Startup did not select Codex health diagnostics"),
])
def test_model_probe_rejects_invalid_turn_evidence(probe, monkeypatch, tmp_path, mode, message):
    with pytest.raises(probe.ProbeError, match=message):
        run_model_stub(probe, monkeypatch, tmp_path, mode)


def test_model_probe_accepts_independent_resume_and_saved_update(probe, monkeypatch, tmp_path):
    started = run_model_stub(probe, monkeypatch, tmp_path, "success")
    assert len(started) == 2
    assert probe.read_saved_session(tmp_path)["updated_at"] == "after"


@pytest.mark.parametrize("payload", [
    {"error": "No config in state"},
    {"status": "fail", "venv": {"status": "no_venv"}},
    {},
])
def test_model_startup_rejects_unsuccessful_health_payload(probe, payload):
    event = tool_event("health_check", {"runtime": "codex"}, payload=payload)
    with pytest.raises(probe.ProbeError):
        probe.check_model_turn([event], resume=False)


def test_model_probe_rejects_business_error_even_with_successful_transport(probe):
    events = [
        tool_event("health_check", {"runtime": "codex"}),
        tool_event("get_config", payload={"error": "No config in state"}),
    ]
    with pytest.raises(probe.ProbeError, match="get_config"):
        probe.check_model_turn(events, resume=False)


@pytest.mark.parametrize("result", [None, {"content": []}, {"content": [{"type": "text", "text": "not json"}]},
                                    {"is_error": True, "content": [{"type": "text", "text": "{}"}]}])
def test_model_probe_rejects_unusable_plugin_result(probe, result):
    event = tool_event("health_check", {"runtime": "codex"})
    event["item"]["result"] = result
    with pytest.raises(probe.ProbeError):
        probe.check_model_turn([event], resume=False)


def test_model_probe_does_not_accept_health_call_from_another_server(probe):
    event = tool_event("health_check", {"runtime": "codex"}, server="other-server")
    with pytest.raises(probe.ProbeError, match="Codex health diagnostics"):
        probe.check_model_turn([event], resume=False)


def test_model_probe_accepts_health_warning_and_unrelated_mcp_result(probe):
    events = [
        tool_event("health_check", {"runtime": "codex"}, payload={"status": "warn"}),
        {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "other-server",
                                             "tool": "another_tool", "status": "completed", "error": None,
                                             "result": {"content": [{"type": "text", "text": "plain text"}]}}},
    ]
    assert probe.check_model_turn(events, resume=False) == 2


@pytest.fixture
def host_app(probe, tmp_path):
    class HostApp:
        def __init__(self):
            self.server = {
                "name": probe.EXPECTED_MCP_SERVER,
                "pluginId": probe.EXPECTED_PLUGIN_ID,
                "tools": {"health_check": {}},
            }
            self.plugin_root = tmp_path / "codex home" / "plugins" / "installed plugin"

        def request(self, request_id, method, arguments):
            if method == "thread/start":
                return {"thread": {"id": "synthetic-thread"}}
            if method == "mcpServerStatus/list":
                return {"data": [self.server]}
            assert method == "mcpServer/tool/call"
            assert arguments["tool"] == "get_plugin_version"
            return {"content": [{"type": "text", "text": json.dumps({
                "plugin_root": str(self.plugin_root),
            })}]}

    return HostApp()


def test_session_probe_accepts_installed_server(probe, host_app, tmp_path):
    probe.SessionProbe(host_app, tmp_path / "foreign workspace", codex_home=tmp_path / "codex home")


def test_session_probe_rejects_server_from_checkout(probe, host_app, tmp_path):
    host_app.plugin_root = tmp_path / "source checkout"
    with pytest.raises(probe.ProbeError, match="not the copy installed"):
        probe.SessionProbe(host_app, tmp_path / "foreign workspace", codex_home=tmp_path / "codex home")


def test_session_probe_reports_mcp_startup_error(probe, host_app, tmp_path):
    host_app.server = {**host_app.server, "tools": None,
                       "runtimeStatus": "failed", "toolsError": "synthetic launcher missing"}
    with pytest.raises(probe.ProbeError, match="synthetic launcher missing"):
        probe.SessionProbe(host_app, tmp_path / "foreign workspace", codex_home=tmp_path / "codex home")


@pytest.mark.parametrize("directory_name", ["dependency venv", "Alice&Bob", "Alice%TEMP%Bob", "Alice^Bob"])
def test_venv_link_cleanup_preserves_source(probe, tmp_path, directory_name):
    source = tmp_path / directory_name
    source.mkdir()
    marker = source / "dependency.txt"
    marker.write_text("keep the source dependencies", encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="isolated home ", dir=tmp_path) as scratch:
        target = Path(scratch) / "venv"
        probe.link_venv(source, target)
        assert (target / marker.name).samefile(marker)
    assert marker.read_text(encoding="utf-8") == "keep the source dependencies"


def test_model_timeout_cleanup_closes_descendant_pipes(probe, tmp_path):
    """A surviving child keeps stdout open even after its launcher is killed."""
    pid_file = tmp_path / "child.pid"
    launcher = (
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8')\n"
        "time.sleep(30)\n"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", launcher, str(pid_file)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        start_new_session=sys.platform != "win32",
    )
    drained = False
    try:
        deadline = time.monotonic() + 10
        while not pid_file.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pid_file.is_file(), "Synthetic launcher did not start its child"
        with pytest.raises(subprocess.TimeoutExpired):
            process.communicate(timeout=0.1)
        probe.stop_model_process(process)
        # EOF proves descendants released inherited handles, not just the parent.
        process.communicate(timeout=5)
        drained = True
    finally:
        if not drained:
            # Independent cleanup keeps a failing regression test from leaking.
            if sys.platform == "win32":
                pids = [process.pid]
                if pid_file.is_file():
                    pids.append(int(pid_file.read_text(encoding="utf-8")))
                for pid in pids:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   capture_output=True, check=False, timeout=10)
            else:
                with contextlib.suppress(OSError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)


@pytest.mark.parametrize("error", [OSError("taskkill unavailable"), subprocess.TimeoutExpired("taskkill", 10)])
def test_windows_model_cleanup_falls_back_when_taskkill_fails(probe, monkeypatch, error):
    class Launcher:
        pid = 424242
        returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

        def wait(self, timeout):
            assert timeout == 10
            assert self.returncode == -9

    def failed_taskkill(command, **kwargs):
        assert command == ["taskkill", "/PID", "424242", "/T", "/F"]
        assert kwargs["timeout"] == 10
        raise error

    with monkeypatch.context() as windows:
        windows.setattr(probe.sys, "platform", "win32")
        windows.setattr(probe.subprocess, "run", failed_taskkill)
        probe.stop_model_process(Launcher())
