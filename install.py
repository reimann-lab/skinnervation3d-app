#!/usr/bin/env python3
"""
SkInnervation3D — Cross-platform installer
Works on Windows, macOS, and Linux.
Run via install.sh (Mac/Linux) or install.bat (Windows).
"""

import sys
import os
import platform
import subprocess
import shutil
import urllib.request
import urllib.error
import tempfile
import getpass
from pathlib import Path

# ── Identity ───────────────────────────────────────────────────────────────────

APP_NAME   = "SkInnervation3D"
APP_ENV    = "skin3d-app"
NAPARI_ENV = "napari-crop"

SYSTEM = platform.system()   # 'Windows', 'Darwin', 'Linux'
ARCH   = platform.machine()  # 'x86_64', 'arm64', 'AMD64'

# ── Repositories ───────────────────────────────────────────────────────────────

PUBLIC_REPOS = {
    "napari-crop-tool":        "https://github.com/girochat/napari-crop-tool.git",
    "skinnervation3d-app":             "https://github.com/reimann-lab/skinnervation3d-app.git",
    
}
PRIVATE_REPOS = {
    "mesospim-fractal-tasks":    "https://github.com/reimann-lab/mesospim-fractal-tasks.git",
    "skinnervation3d-fractal-tasks":   "https://github.com/reimann-lab/skinnervation3d-fractal-tasks.git",
}

# ── Miniforge download URLs ────────────────────────────────────────────────────

def _miniforge_url() -> str:
    if SYSTEM == "Windows":
        return "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe"
    elif SYSTEM == "Darwin":
        arch = "arm64" if ARCH == "arm64" else "x86_64"
        return f"https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-{arch}.sh"
    else:
        machine = ARCH if ARCH in ("x86_64", "aarch64") else "x86_64"
        return f"https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-{machine}.sh"


# ══════════════════════════════════════════════════════════════════════════════
#  UI helpers
# ══════════════════════════════════════════════════════════════════════════════

W = 62

def header(text: str):
    print(f"\n{'═' * W}")
    print(f"  {text}")
    print(f"{'═' * W}")

def step(text: str):
    print(f"\n▶  {text}")

def ok(text: str):
    print(f"   ✓  {text}")

def warn(text: str):
    print(f"   ⚠  {text}")

def err(text: str):
    print(f"\n   ✗  ERROR: {text}", file=sys.stderr)

def ask(prompt: str, default: str = "") -> str:
    if default:
        val = input(f"\n   {prompt}\n   [{default}]: ").strip()
        return val if val else default
    while True:
        val = input(f"\n   {prompt}: ").strip()
        if val:
            return val
        print("   (required — please enter a value)")

def ask_secret(prompt: str) -> str:
    while True:
        val = getpass.getpass(f"\n   {prompt}: ").strip()
        if val:
            return val
        print("   (required — please enter a value)")

def run(cmd: list, check: bool = True, capture: bool = False,
        cwd: Path = None) -> subprocess.CompletedProcess:
    display = " ".join(str(c) for c in cmd)
    # Mask any PAT that slipped into a URL
    if "https://" in display and "@" in display:
        display = display.split("@")[0].split("//")[0] + "//***@" + display.split("@", 1)[1]
    print(f"   $ {display}")
    return subprocess.run(
        [str(c) for c in cmd],
        check=check,
        capture_output=capture,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Conda / Miniforge
# ══════════════════════════════════════════════════════════════════════════════

def find_conda() -> Path | None:
    exe = "conda.exe" if SYSTEM == "Windows" else "conda"
    found = shutil.which(exe)
    if found:
        return Path(found)

    home = Path.home()
    if SYSTEM == "Windows":
        candidates = [
            home / "miniforge3"  / "Scripts" / "conda.exe",
            home / "miniforge"   / "Scripts" / "conda.exe",
            home / "miniconda3"  / "Scripts" / "conda.exe",
            home / "anaconda3"   / "Scripts" / "conda.exe",
            Path("C:/ProgramData/miniforge3/Scripts/conda.exe"),
        ]
    else:
        candidates = [
            home / "miniforge3"  / "bin" / "conda",
            home / "miniforge"   / "bin" / "conda",
            home / "miniconda3"  / "bin" / "conda",
            home / "anaconda3"   / "bin" / "conda",
            Path("/opt/homebrew/Caskroom/miniforge/base/bin/conda"),
        ]

    for c in candidates:
        if c.exists():
            return c
    return None


def install_miniforge() -> Path:
    step("Miniforge not found — downloading and installing it now…")
    url = _miniforge_url()
    print(f"   URL: {url}")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path.home() / "miniforge3"

        if SYSTEM == "Windows":
            installer = Path(tmp) / "Miniforge3.exe"
            print("   Downloading (this may take a minute)…")
            urllib.request.urlretrieve(url, installer)
            # NSIS silent install — /D must be the last argument and no quotes
            run([str(installer), "/S", f"/D={target}"])
            conda_exe = target / "Scripts" / "conda.exe"

        else:
            installer = Path(tmp) / "Miniforge3.sh"
            print("   Downloading (this may take a minute)…")
            urllib.request.urlretrieve(url, installer)
            installer.chmod(0o755)
            run(["bash", str(installer), "-b", "-p", str(target)])
            conda_exe = target / "bin" / "conda"

    if not conda_exe.exists():
        err("Miniforge installation seems to have failed. "
            "Please install it manually from https://github.com/conda-forge/miniforge and re-run.")
        sys.exit(1)

    ok(f"Miniforge installed → {target}")
    return conda_exe


def conda_base(conda_exe: Path) -> Path:
    r = run([conda_exe, "info", "--base"], capture=True)
    return Path(r.stdout.strip())


def env_exists(base: Path, name: str) -> bool:
    return (base / "envs" / name).exists()


def env_python(base: Path, name: str) -> Path:
    if SYSTEM == "Windows":
        return base / "envs" / name / "python.exe"
    return base / "envs" / name / "bin" / "python"


def env_bin(base: Path, env: str, binary: str) -> Path:
    """Resolve a binary inside a conda env, Windows-aware."""
    if SYSTEM == "Windows":
        scripts = base / "envs" / env / "Scripts"
        for suffix in (".exe", ".cmd", ""):
            p = scripts / f"{binary}{suffix}"
            if p.exists():
                return p
        return scripts / f"{binary}.exe"
    return base / "envs" / env / "bin" / binary


# ══════════════════════════════════════════════════════════════════════════════
#  conda-lock support
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_conda_lock(conda_exe: Path):
    r = run([conda_exe, "run", "-n", "base", "conda-lock", "--version"],
            check=False, capture=True)
    if r.returncode != 0:
        step("Installing conda-lock into base env (one-time setup)…")
        run([conda_exe, "install", "-n", "base", "conda-lock",
             "-c", "conda-forge", "-y"])


def _conda_lock_exe(conda_exe: Path, base: Path) -> Path:
    if SYSTEM == "Windows":
        p = base / "Scripts" / "conda-lock.exe"
    else:
        p = base / "bin" / "conda-lock"
    return p if p.exists() else Path("conda-lock")


# ══════════════════════════════════════════════════════════════════════════════
#  Environment creation
# ══════════════════════════════════════════════════════════════════════════════

def create_env(conda_exe: Path, env_name: str, repo_dir: Path, base: Path):
    """
    Create a conda env from conda-lock.yml (preferred) or environment.yml.
    Skips silently if the env already exists.
    """
    if env_exists(base, env_name):
        ok(f"Env '{env_name}' already exists — skipping "
           f"(delete it with  conda env remove -n {env_name}  to reinstall)")
        return

    lock_file = repo_dir / "conda-lock.yml"
    env_file  = repo_dir / "environment.yml"

    if lock_file.exists():
        step(f"Creating env '{env_name}' from conda-lock.yml…")
        _ensure_conda_lock(conda_exe)
        cl = _conda_lock_exe(conda_exe, base)
        run([cl, "install", "-n", env_name, str(lock_file)])

    elif env_file.exists():
        step(f"Creating env '{env_name}' from environment.yml…")
        run([conda_exe, "env", "create", "-n", env_name, "-f", str(env_file)])

    else:
        warn(f"No conda-lock.yml or environment.yml found in {repo_dir.name}. "
             f"Creating a minimal Python 3.11 env.")
        run([conda_exe, "create", "-n", env_name,
             "python=3.11", "-c", "conda-forge", "-y"])

    ok(f"Env '{env_name}' ready")


def pip_install(conda_exe: Path, env_name: str, package_dir: Path):
    """pip install -e a local package into a conda env."""
    step(f"pip install -e {package_dir.name} → env '{env_name}'")
    run([conda_exe, "run", "--no-capture-output",
         "-n", env_name,
         "pip", "install", "-e", str(package_dir)])
    ok(f"{package_dir.name} installed")


# ══════════════════════════════════════════════════════════════════════════════
#  Git
# ══════════════════════════════════════════════════════════════════════════════

def check_git():
    if shutil.which("git") is None:
        err("git is not installed.\n"
            "   Please install it from https://git-scm.com and re-run this installer.")
        sys.exit(1)
    ok("git found")


def inject_pat(url: str, pat: str) -> str:
    """Turn https://github.com/… into https://PAT@github.com/…"""
    return url.replace("https://", f"https://{pat}@")


def clone_or_pull(url: str, dest: Path, pat: str = ""):
    if dest.exists():
        ok(f"{dest.name} already present — pulling latest…")
        run(["git", "-C", str(dest), "pull"])
        return
    auth_url = inject_pat(url, pat) if pat else url
    run(["git", "clone", auth_url, str(dest)])
    ok(f"Cloned {dest.name}")


# ══════════════════════════════════════════════════════════════════════════════
#  Config file  (config.py written directly into the app source tree)
# ══════════════════════════════════════════════════════════════════════════════

def write_app_config(repo_dir: Path, conda_base: Path,
                     napari_env: str, data_dir: Path) -> Path:
    """
    Generate src/skinnervation3d_app/config.py with values specific to this
    machine.  The file is intentionally NOT committed to git (.gitignore it).
    """
    napari_env_root = conda_base / "envs" / napari_env

    # Represent paths with forward slashes even on Windows so the generated
    # Python source is readable; Path() will normalise them at runtime anyway.
    def py_path(p: Path) -> str:
        return str(p).replace("\\", "/")

    content = f'''\
# ──────────────────────────────────────────────────────────────────────────────
#  SkInnervation3D — machine-specific configuration
#  AUTO-GENERATED by the installer — do not edit by hand.
#  Re-run the installer to regenerate, or edit carefully if you know what
#  you are doing.
# ──────────────────────────────────────────────────────────────────────────────

from pathlib import Path

CONDA_NAPARI_ENV_NAME = "{napari_env}"
CONDA_NAPARI_ENV_ROOT = Path("{py_path(napari_env_root)}")
ANALYSIS_DIR_INIT     = Path("{py_path(data_dir)}")
'''

    config_path = repo_dir / "src" / "skinnervation3d_app" / "config.py"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(content, encoding="utf-8")
    ok(f"config.py written → {config_path}")
    return config_path


# ══════════════════════════════════════════════════════════════════════════════
#  Desktop shortcut
# ══════════════════════════════════════════════════════════════════════════════

def create_shortcut(base: Path):
    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)

    if SYSTEM == "Windows":
        _shortcut_windows(desktop, base)
    elif SYSTEM == "Darwin":
        _shortcut_mac(desktop, base)
    else:
        _shortcut_linux(desktop, base)


def _shortcut_windows(desktop: Path, base: Path):
    """
    Two files:
      SkInnervation3D.vbs  — launches without a console window
      SkInnervation3D.bat  — fallback / what the .vbs calls
    """
    app_exe = base / "envs" / APP_ENV / "Scripts" / "skin3d-app.exe"

    # .bat (used internally)
    bat = desktop / "SkInnervation3D.bat"
    bat.write_text(
        f'@echo off\n'
        f'call "{base}\\Scripts\\activate.bat" {APP_ENV}\n'
        f'if exist "{app_exe}" (\n'
        f'    start "" "{app_exe}"\n'
        f') else (\n'
        f'    python -m skinnervation3d_app\n'
        f')\n'
    )

    # .vbs wrapper — hides the console entirely
    vbs = desktop / "SkInnervation3D.vbs"
    vbs.write_text(
        'Set oShell = CreateObject("WScript.Shell")\n'
        f'oShell.Run chr(34) & "{app_exe}" & chr(34), 0, False\n'
    )
    ok(f"Desktop shortcut created → {vbs}")
    ok(f"Batch fallback          → {bat}")


def _shortcut_mac(desktop: Path, base: Path):
    """A .command file the user can double-click in Finder."""
    conda_sh = base / "etc" / "profile.d" / "conda.sh"
    script   = desktop / "SkInnervation3D.command"
    script.write_text(
        f'#!/usr/bin/env bash\n'
        f'source "{conda_sh}"\n'
        f'conda activate {APP_ENV}\n'
        f'skin3d-app\n'
    )
    script.chmod(0o755)
    ok(f"Desktop shortcut created → {script}")
    print("   Tip: right-click → Open the first time to bypass Gatekeeper.")


def _shortcut_linux(desktop: Path, base: Path):
    conda_sh = base / "etc" / "profile.d" / "conda.sh"
    df = desktop / "SkInnervation3D.desktop"
    df.write_text(
        "[Desktop Entry]\n"
        f"Name={APP_NAME}\n"
        "Type=Application\n"
        "Terminal=false\n"
        f'Exec=bash -c \'source "{conda_sh}" && conda activate {APP_ENV} && skin3d-app\'\n'
        "Icon=\n"
        "Categories=Science;\n"
    )
    df.chmod(0o755)
    ok(f"Desktop shortcut created → {df}")


# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    header(f"{APP_NAME} Installer")
    print(
        "\n  This script will:\n"
        "    1. Install Miniforge (if needed)\n"
        "    2. Download all source code from GitHub\n"
        "    3. Create two conda environments\n"
        "    4. Install all packages\n"
        "    5. Write your configuration file\n"
        "    6. Create a desktop shortcut\n"
        "\n  Estimated time: 10–25 minutes depending on internet speed.\n"
    )
    input("  Press Enter to begin (Ctrl+C to cancel)… ")

    # ── Prerequisites ──────────────────────────────────────────────────────────
    header("Step 1 / 6 — Prerequisites")

    check_git()

    conda_exe = find_conda()
    if conda_exe:
        ok(f"Conda found → {conda_exe}")
    else:
        conda_exe = install_miniforge()

    base = conda_base(conda_exe)
    ok(f"Conda base  → {base}")

    # ── User configuration ─────────────────────────────────────────────────────
    header("Step 2 / 6 — Your configuration")

    print("  Please answer a few questions.\n")

    default_install = Path.home() / "SkInnervation3D"
    install_dir = Path(ask(
        "Installation folder (source code will be cloned here)",
        str(default_install)
    ))
    install_dir.mkdir(parents=True, exist_ok=True)

    data_dir = Path(ask(
        "Data directory (where your imaging data lives)",
        str(Path.home() / "data")
    ))

    print(
        "\n  A GitHub Personal Access Token (PAT) is required to download\n"
        "  private repositories.\n"
        "  → Create one at: https://github.com/settings/tokens\n"
        "  → Required scope: 'Contents: Read-only' (classic token: 'repo')\n"
        "  The token is used only during installation and never stored.\n"
    )
    pat = ask_secret("GitHub PAT (input is hidden)")

    # ── Clone repos ────────────────────────────────────────────────────────────
    header("Step 3 / 6 — Downloading source code")

    repos = install_dir / "repos"
    repos.mkdir(exist_ok=True)

    for name, url in PUBLIC_REPOS.items():
        clone_or_pull(url, repos / name)

    for name, url in PRIVATE_REPOS.items():
        clone_or_pull(url, repos / name, pat=pat)

    # ── Napari environment ─────────────────────────────────────────────────────
    header(f"Step 4 / 6 — Environment '{NAPARI_ENV}'")
    create_env(conda_exe, NAPARI_ENV, repos / "napari-crop-tool", base)

    # pip install the napari plugin into its own env
    pip_install(conda_exe, NAPARI_ENV, repos / "napari-crop-tool")

    # ── App environment ────────────────────────────────────────────────────────
    header(f"Step 5 / 6 — Environment '{APP_ENV}'")
    create_env(conda_exe, APP_ENV, repos / "skinnervation3d-app", base)

    # Install the app itself
    pip_install(conda_exe, APP_ENV, repos / "skinnervation3d-app")

    # Install analysis packages into the app env
    pip_install(conda_exe, APP_ENV, repos / "mesospim-fractal-tasks")
    pip_install(conda_exe, APP_ENV, repos / "skinnervation3d-fractal-tasks")

    # ── Config + shortcut ──────────────────────────────────────────────────────
    header("Step 6 / 6 — Configuration & desktop shortcut")

    config_path = write_app_config(
        repo_dir   = repos / "skinnervation3d-app",
        conda_base = base,
        napari_env = NAPARI_ENV,
        data_dir   = data_dir,
    )

    create_shortcut(base)

    # ── Done ───────────────────────────────────────────────────────────────────
    header("Installation complete! 🎉")
    print(
        f"\n  App installed to : {install_dir}"
        f"\n  config.py        : {config_path}"
        f"\n  Conda envs       : {APP_ENV}  |  {NAPARI_ENV}"
        f"\n"
        f"\n  ▶  Double-click the SkInnervation3D shortcut on your Desktop to launch."
        f"\n"
        f"\n  Manual launch (if shortcut fails):"
        f"\n      conda activate {APP_ENV}"
        f"\n      skin3d-app"
        f"\n"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Installation cancelled.")
        sys.exit(0)
    except subprocess.CalledProcessError as e:
        err(f"A command failed (exit code {e.returncode}):\n   {e.cmd}")
        sys.exit(1)
    except Exception as e:
        err(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)