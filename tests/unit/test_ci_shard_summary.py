"""Exercise the CI shard summary against delayed and failed Jobs API results."""

import os
import shutil
import subprocess
import sys

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash"),
    reason="the summary job runs in bash on an Ubuntu runner",
)

SUCCESS = (
    "success Tests (ubuntu-latest, shard 1/2)\n"
    "success Tests (ubuntu-latest, shard 2/2)\n"
)
PENDING = SUCCESS.replace("success Tests (ubuntu-latest, shard 1/2)",
                          "null Tests (ubuntu-latest, shard 1/2)")
FAILED = SUCCESS.replace("success Tests (ubuntu-latest, shard 1/2)",
                         "failure Tests (ubuntu-latest, shard 1/2)")


@pytest.mark.parametrize(
    "responses, expected_exit, expected_calls",
    [
        ([(0, PENDING), (0, SUCCESS)], 0, 2),
        ([(0, SUCCESS.splitlines()[0]), (0, SUCCESS)], 0, 2),
        ([(0, FAILED)], 1, 1),
        ([(0, PENDING)], 1, 3),
        ([(1, ""), (0, SUCCESS)], 0, 2),
        ([(1, "")], 1, 3),
    ],
    ids=["pending-then-success", "missing-then-success", "failed-shard",
         "pending-timeout", "api-recovery", "api-failure"],
)
def test_shard_summary_waits_for_conclusions(
    project_root, tmp_path, responses, expected_exit, expected_calls
):
    workflow = yaml.safe_load((project_root / ".github/workflows/test.yml").read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["test"]["steps"]
                if step["name"].startswith("Both shards"))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        '#!/bin/sh\n'
        'i=0\n'
        '[ ! -f "$CI_PROBE_DIR/calls" ] || i=$(cat "$CI_PROBE_DIR/calls")\n'
        'i=$((i + 1))\n'
        'printf "%s\\n" "$i" > "$CI_PROBE_DIR/calls"\n'
        'cat "$CI_PROBE_DIR/output-$i"\n'
        'exit "$(cat "$CI_PROBE_DIR/status-$i")"\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    sleep = bin_dir / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sleep.chmod(0o755)
    for i in range(1, 4):
        code, output = responses[min(i - 1, len(responses) - 1)]
        (tmp_path / f"output-{i}").write_text(output, encoding="utf-8")
        (tmp_path / f"status-{i}").write_text(str(code), encoding="utf-8")

    env = {
        **os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "CI_PROBE_DIR": str(tmp_path), "OS": "ubuntu-latest",
        "GITHUB_REPOSITORY": "test/repo", "GITHUB_RUN_ID": "1",
    }
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        env=env, capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == expected_exit, result.stdout + result.stderr
    assert int((tmp_path / "calls").read_text(encoding="utf-8")) == expected_calls
