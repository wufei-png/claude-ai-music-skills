"""Check PR 645's Windows install on the fork's hosted runner."""

import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main(product: Path) -> None:
    sys.path.insert(0, str(product / "tests/e2e"))
    from codex_plugin_discovery_check import AppServer, _install_local_plugin
    from codex_session_resume_check import SessionProbe, initialize, require

    require(sys.platform == "win32", "This check requires native Windows")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=product, text=True).strip()
    codex = str(product / "tests/e2e/codex/node_modules/.bin/codex.cmd")
    setup_relative = Path("skills/setup/SKILL.md")

    print(f"Testing {sha} on {platform.platform()}")
    subprocess.run([codex, "--version"], check=True)

    with TemporaryDirectory(prefix="bitwize first setup ", dir=os.environ["RUNNER_TEMP"],
                            ignore_cleanup_errors=True) as temp:
        root = Path(temp).resolve()
        home = root / "fresh user"
        workspace = root / "music workspace"
        codex_home = home / "codex"
        appdata = home / "AppData"
        home.mkdir()
        require(not any(home.iterdir()), "The user directory must start empty")
        print(f"Created empty user profile: {home}")
        for directory in (workspace, codex_home, appdata / "Local", appdata / "Roaming"):
            directory.mkdir(parents=True)

        env = os.environ.copy()
        for name in ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT", "PLAYWRIGHT_BROWSERS_PATH"):
            env.pop(name, None)
        env.update(
            HOME=str(home),
            USERPROFILE=str(home),
            CODEX_HOME=str(codex_home),
            LOCALAPPDATA=str(appdata / "Local"),
            APPDATA=str(appdata / "Roaming"),
        )

        version = _install_local_plugin(codex, root=product, cwd=workspace, env=env)
        discovery = AppServer(codex, cwd=workspace, env=env)
        try:
            initialize(discovery)
            result = discovery.request(
                3, "skills/list", {"cwds": [str(workspace)], "forceReload": True},
            )
            skill = next(
                skill for entry in result["data"] for skill in entry["skills"]
                if skill["name"] == "bitwize-music:setup" and skill.get("enabled")
            )
        finally:
            discovery.close()

        installed_setup = Path(skill["path"]).resolve()
        installed_root = installed_setup.parents[2]
        require(installed_root.is_relative_to(codex_home), "Setup was loaded outside the install")
        require(" " in str(installed_root), f"Installed path has no spaces: {installed_root}")
        for relative in (setup_relative, Path("requirements.txt")):
            require((installed_root / relative).read_bytes() == (product / relative).read_bytes(),
                    f"Installed {relative} differs from the PR")
        print(f"Installed bitwize-music {version} at: {installed_root}")

        venv = home / ".bitwize-music/venv"
        require(not venv.exists(), "The venv already exists before setup")
        setup = installed_setup.read_text(encoding="utf-8")
        step3 = setup.split("## Step 3:", 1)[1].split("## Step 3.5:", 1)[0]
        block = re.search(r"```powershell\n(.*?)\n```", step3, re.DOTALL)
        require(block is not None, "Step 3 must show the PowerShell commands")
        commands = block[1].replace("$env:CLAUDE_PLUGIN_ROOT", str(installed_root))
        script = root / "first-setup.ps1"
        script.write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "$PSNativeCommandUseErrorActionPreference = $true\n"
            "py -3 --version\n"
            f"{commands}\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["pwsh.exe", "-NoProfile", "-NonInteractive", "-File", str(script)],
            cwd=workspace, env=env, check=True, timeout=900,
        )

        python = venv / "Scripts/python.exe"
        require(python.is_file(), f"Setup did not create {python}")
        python_version = subprocess.check_output([str(python), "--version"], text=True).strip()
        print(f"Created fresh venv with {python_version}: {python}")
        subprocess.run(
            [str(python), "-c",
             "from pathlib import Path\n"
             "from playwright.sync_api import sync_playwright\n"
             "with sync_playwright() as browser:\n"
             "    assert Path(browser.chromium.executable_path).is_file()\n"],
            cwd=workspace, env=env, check=True, timeout=60,
        )
        print("Verified Chromium installed in the fresh profile")

        app = AppServer(codex, cwd=workspace, env=env)
        try:
            initialize(app)
            session = SessionProbe(app, workspace, codex_home=codex_home)
            reported = session.call("get_python_command")
            require(Path(reported["plugin_root"]).resolve() == installed_root, "Wrong MCP install")
            require(reported["venv_exists"] and Path(reported["python"]).resolve() == python.resolve(),
                    "MCP did not find the fresh venv")
            venv_health = session.call("health_check", runtime="codex")["venv"]
            require(venv_health["status"] == "ok", f"Venv check failed: {venv_health}")
        finally:
            app.close()
        print("New Codex session reached the installed MCP server and verified the fresh venv")

        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            summary.write(
                "### Native Windows first setup\n\n"
                f"- Tested PR head `{sha}` on `windows-latest`.\n"
                f"- Installed bitwize-music {version} under the space-containing path "
                f"`{installed_root}`.\n"
                f"- Ran the installed skill's PowerShell commands with {python_version} "
                "from a fresh profile. The venv and Chromium install passed.\n"
                "- A new Codex session called the installed MCP server and reported "
                "`venv.status: ok`.\n"
            )


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
