#!/usr/bin/env python3
"""
SkInnervation3D — Cross-platform installer
Works on Windows, macOS, and Linux.
Run via install.sh (Mac/Linux) or install.bat (Windows).
"""

from __future__ import annotations

import os
import stat
import json
import time
import sys
import platform
import subprocess
import shutil
import hashlib
import urllib.request
import tempfile
import getpass
from pathlib import Path

# ── Identity ───────────────────────────────────────────────────────────────────

APP_NAME   = "SkInnervation3D"
APP_ENV    = "skin3d-app"
NAPARI_ENV = "napari-crop"

SYSTEM = platform.system()   # 'Windows', 'Darwin', 'Linux'
ARCH   = platform.machine()  # 'x86_64', 'arm64', 'AMD64'

STAMP_NAME = ".skinnervation3d-env.json"

# ── Repositories ───────────────────────────────────────────────────────────────

PUBLIC_REPOS = {
    "napari-crop-tool":        "https://github.com/girochat/napari-crop-tool.git",
    "mesospim-fractal-tasks":    "https://github.com/reimann-lab/mesospim-fractal-tasks.git",
    "skinnervation3d-app":             "https://github.com/reimann-lab/skinnervation3d-app.git",
}
PRIVATE_REPOS = {
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
        val = input(f"\n   {prompt}\n   [current default: {default}]: ").strip()
        if val:
            val = val.strip('"')
            val = val.strip("'")
            return val
        else:
            return default

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

def _stamp_path(base: Path, env_name: str) -> Path:
    return _env_dir(base, env_name) / STAMP_NAME
 
 
def _read_stamp(base: Path, env_name: str) -> dict:
    p = _stamp_path(base, env_name)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_stamp(base: Path, env_name: str, spec: Path, digest: str, method: str):
    p = _stamp_path(base, env_name)
    payload = {
        "env": env_name,
        "spec_file": spec.name,
        "spec_path": str(spec),
        "spec_sha256": digest,
        "method": method,                       # 'create' | 'sync'
        "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "installer_version": 2,
    }
    try:
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as e:
        warn(f"Could not write env stamp ({e}) — the next run will not be able "
             f"to detect lock changes for '{env_name}'.")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _env_spec(repo_dir: Path):
    """Return (spec_path, kind) — kind is 'lock', 'yaml' or 'none'."""
    lock_file = repo_dir / "conda-lock.yml"
    specs = {}
    if lock_file.exists():
        specs["lock"] = lock_file
    env_file = repo_dir / "environment.yml"
    if env_file.exists():
        specs["yaml"] = env_file
    return specs


def _rmtree_force(path: Path):
    """rmtree that also copes with read-only files (common on Windows)."""
    def handler(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass
    kwargs = {"onexc": handler} if sys.version_info >= (3, 12) else {"onerror": handler}
    shutil.rmtree(path, **kwargs)


def remove_env(conda_exe: Path, base: Path, env_name: str):
    step(f"Removing env '{env_name}'…")
    run([conda_exe, "env", "remove", "-n", env_name, "--yes"], check=False)
 
    env_dir = _env_dir(base, env_name)
    if env_dir.exists():
        warn("conda left the env folder behind — deleting it directly…")
        try:
            _rmtree_force(env_dir)
        except Exception as e:
            warn(f"Direct deletion failed: {e}")
 
    if env_dir.exists():
        err(f"Could not remove '{env_dir}'.\n"
            f"   On Windows this usually means a program from that env is still "
            f"running (napari, a terminal with the env activated, an editor…).\n"
            f"   Close them, then re-run the installer.")
        sys.exit(1)
    ok(f"Env '{env_name}' removed")


def _build_env(conda_exe: Path, env_name: str, base: Path,
               specs: dict, repo_dir: Path) -> Path:
    if "lock" in specs.keys():
        try:
            step(f"Creating env '{env_name}' from {specs['lock'].name}…")
            _ensure_conda_lock(conda_exe)
            cl = _conda_lock_exe(conda_exe, base)
            env_path = _env_dir(base, env_name)
            run([cl, "install", "-p", env_path, str(specs["lock"])])
            return specs["lock"]
        except Exception as e:
            warn(f"Could not create env '{env_name}' from "
                 f"{specs['lock'].name}:\n   {e}")
            if env_path.exists():
                warn("Removing the partially created env…")
                remove_env(conda_exe, base, env_name)
    
    if "yaml" in specs.keys():
        step(f"Creating env '{env_name}' from {specs['yaml'].name}…")
        run([conda_exe, "env", "create", "-n", env_name, "-f", str(specs["yaml"])])
        return specs["yaml"]
 
    err(f"Installation using either conda-lock.yml or environment.yml failed. It might be "
        "due to the absence of the files or an error with conda manager.")
    sys.exit(1)


def create_env(conda_exe: Path, env_name: str, repo_dir: Path, base: Path):
    """
    Create a conda env from conda-lock.yml (preferred) or environment.yml.
    
    If the env already exists, the SHA-256 of the spec file is compared against
    the one recorded in <env>/.skinnervation3d-env.json when the env was built:
      • unchanged            → skip (fast path, unchanged behaviour)
      • changed / no stamp   → rebuild from scratch, or sync in place,
                               depending on ENV_UPDATE_POLICY / CLI flags

    """
    specs = _env_spec(repo_dir)
    digest_yaml = _sha256_file(specs["yaml"]) if "yaml" in specs else None
    digest_lock = _sha256_file(specs["lock"]) if "lock" in specs else None

    if env_exists(base, env_name):
        if "yaml" not in specs.keys() and "lock" not in specs.keys():
            ok(f"Env '{env_name}' already exists and {repo_dir.name} has no "
               f"lock/environment file — skipping")
            return
 
        else:
            recorded = _read_stamp(base, env_name).get("spec_sha256")
 
            if recorded and (recorded == digest_yaml or recorded == digest_lock):
                ok(f"Env '{env_name}' is up to date with environment files — skipping")
                return
            else:
                warn(f"Env '{env_name}' exists but has a different (or none) "
                f"installer stamp than {repo_dir.name}. Rebuilding env...")
                remove_env(conda_exe, base, env_name)
 
    used = _build_env(conda_exe, env_name, base, specs, repo_dir)
 
    if not env_exists(base, env_name):
        err(f"Env '{env_name}' was not created at {_env_dir(base, env_name)}.")
        sys.exit(1)
 
    if used:
        _write_stamp(base, env_name, used, _sha256_file(used), "create")
    ok(f"Env '{env_name}' ready")


def pip_install(conda_exe: Path, env_name: str, package_dir: Path):
    """pip install -e a local package into a conda env."""
    step(f"pip install -e {package_dir.name} → env '{env_name}'")
    run([conda_exe, "run", "--no-capture-output",
         "-n", env_name,
         "pip", "install", "--no-cache-dir", "-e", str(package_dir)])
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
#  Launchers + Desktop shortcuts
#
#  Strategy (all platforms):
#    • A launcher script is written INSIDE the conda env (not on the Desktop)
#    • A lightweight desktop shortcut points at that launcher
#
#  Windows  : launcher = <env>/launch.bat
#             shortcut = Desktop/<Name>.lnk  (real Windows shortcut via PowerShell)
#  macOS    : launcher = <env>/bin/launch.command  (executable bash script)
#             shortcut = Desktop/<Name>.command     (tiny wrapper that calls it)
#  Linux    : launcher = <env>/bin/launch.sh
#             shortcut = Desktop/<Name>.desktop
# ══════════════════════════════════════════════════════════════════════════════

# ── helpers ───────────────────────────────────────────────────────────────────

def _env_dir(base: Path, env: str) -> Path:
    return base / "envs" / env


def _write_file(path: Path, content: str, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable and SYSTEM != "Windows":
        path.chmod(0o755)


def _windows_lnk(lnk_path: Path, target: Path, description: str = "",
                 icon: Path = None):
    """Create a real .lnk shortcut on Windows via PowerShell."""
    icon_line = f'$s.IconLocation = "{icon}";' if icon and icon.exists() else ""
    ps = (
        f'$s = (New-Object -ComObject WScript.Shell).CreateShortcut("{lnk_path}");\n'
        f'$s.TargetPath = "{target}";\n'
        f'$s.Description = "{description}";\n'
        f'{icon_line}\n'
        f'$s.Save()'
    )
    run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps])


# ── Windows ───────────────────────────────────────────────────────────────────

def _make_windows_app_launcher(base: Path, env: str, command: str) -> Path:
    """Write a launch.bat inside the conda env and return its path.
    Calls binaries by their full path — no activation needed, avoids PATH issues.
    """
    env_dir = _env_dir(base, env)
    scripts = env_dir / "Scripts"
    exe = scripts / f"{command}.exe"
    if not exe.exists():
        python = env_dir / "python.exe"
        cmd_line = f'"{python}" -m {command}'
    else:
        cmd_line = f'start "" /min "{exe}"'
 
    bat = env_dir / "launch.bat"
    _write_file(bat, (
        "@echo off\n"
        "set OMP_NUM_THREADS=1\n"
        "set MKL_NUM_THREADS=1\n"
        "set NUMEXPR_NUM_THREADS=1\n"
        "set OPENBLAS_NUM_THREADS=1\n"
        "set NUMBA_NUM_THREADS=1\n"
        f"{cmd_line}\n"
    ))
    ok(f"Launcher written → {bat}")
    return bat

def _make_windows_napari_launcher(base: Path, env: str, command: str) -> Path:
    """Write a launch.bat inside the conda env and return its path.
    Calls binaries by their full path — no activation needed, avoids PATH issues.
    """
    env_dir = _env_dir(base, env)
    scripts = base / "Scripts"
    cmd_line = f'start "" /min napari'
 
    bat = env_dir / "launch_napari.bat"
    _write_file(bat, (
        "@echo off\n"
        f"call {scripts / 'activate.bat'} {env}\n"
        f"{cmd_line}\n"
        "exit\n"
    ))
    ok(f"Launcher written → {bat}")
    return bat


def _shortcut_windows(desktop: Path, base: Path, repos: Path):
    # skin3d-app
    app_bat = _make_windows_app_launcher(base, APP_ENV, "skin3d-app")
    app_icon = repos / "skinnervation3d-app" / "src" / "skinnervation3d_app" / "resources" / "skin3d_logo.ico"
    lnk = desktop / "Skinnervation3D.lnk"
    _windows_lnk(lnk, app_bat, "Launch SkInnervation3D App", icon=app_icon)
    ok(f"Desktop shortcut → {lnk}")
 
    # napari-crop
    napari_bat = _make_windows_napari_launcher(base, NAPARI_ENV, "napari")
    napari_icon = _env_dir(base, NAPARI_ENV) / "Lib" / "site-packages" / "napari" / "resources" / "icon.ico"
    lnk2 = desktop / "Napari.lnk"
    _windows_lnk(lnk2, napari_bat, "Launch Napari (crop tool)", icon=napari_icon)
    ok(f"Desktop shortcut → {lnk2}")


# ── macOS/Linux ─────────────────────────────────────────────────────────────────────

def _find_site_packages(env_dir: Path) -> Path | None:
    """Find site-packages dir without hardcoding the Python version."""
    lib = env_dir / "lib"
    if lib.exists():
        for p in sorted(lib.iterdir()):
            sp = p / "site-packages"
            if sp.exists():
                return sp
    return None

# ── macOS ─────────────────────────────────────────────────────────────────────
 
def _ico_to_png_mac(ico: Path, out: Path) -> bool:
    """Convert .ico to .png using sips (built into macOS). Returns True on success."""
    r = run(["sips", "-s", "format", "png", str(ico), "--out", str(out)],
            check=False, capture=True)
    return r.returncode == 0 and out.exists()
 
 
def _make_mac_app_bundle(apps: Path, name: str, launcher: Path,
                         icon_ico: Path = None) -> Path:
    """
    Create a minimal .app bundle in /Applications.
    Structure:
      <name>.app/Contents/MacOS/<name>   ← executable that calls launcher
      <name>.app/Contents/Resources/app.png  ← icon (optional)
      <name>.app/Contents/Info.plist
    """
    bundle = apps / f"{name}.app"
    macos_dir     = bundle / "Contents" / "MacOS"
    resources_dir = bundle / "Contents" / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)
 
    # Executable
    exe = macos_dir / name
    _write_file(exe, (
        "#!/usr/bin/env bash\n"
        f'exec "{launcher}"\n'
    ), executable=True)
 
    # Icon
    icon_name = ""
    if icon_ico and icon_ico.exists():
        png = resources_dir / "app.png"
        if _ico_to_png_mac(icon_ico, png):
            icon_name = "app.png"
            ok(f"Icon converted → {png}")
        else:
            warn("Icon conversion failed (sips), app will use default icon")
 
    # Info.plist
    icon_line = f"<key>CFBundleIconFile</key><string>{icon_name}</string>" if icon_name else ""
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f'  <key>CFBundleName</key><string>{name}</string>\n'
        f'  <key>CFBundleIdentifier</key><string>org.skinnervation.{name.lower()}</string>\n'
        '  <key>CFBundleVersion</key><string>1.0</string>\n'
        '  <key>CFBundlePackageType</key><string>APPL</string>\n'
        f'  <key>CFBundleExecutable</key><string>{name}</string>\n'
        f'  {icon_line}\n'
        '</dict></plist>\n'
    )
    (bundle / "Contents" / "Info.plist").write_text(plist, encoding="utf-8")
 
    ok(f"App bundle → {bundle}")
    return bundle
 
 
def _make_mac_launcher(base: Path, env: str, command: str) -> Path:
    """Write an executable .command script inside <env>/bin/ and return its path."""
    conda_sh = base / "etc" / "profile.d" / "conda.sh"
    script = _env_dir(base, env) / "bin" / "launch.command"
    _write_file(script, (
        "#!/usr/bin/env bash\n"
        f'source "{conda_sh}"\n'
        f"conda activate {env}\n"
        f"{command}\n"
    ), executable=True)
    ok(f"Launcher written → {script}")
    return script
 
 
def _shortcut_mac(_, base: Path, repos: Path):
    apps = Path.home() / "Applications"
    apps.mkdir(parents=True, exist_ok=True)
 
    # skin3d-app
    app_launcher = _make_mac_launcher(base, APP_ENV, "skin3d-app")
    app_icon = repos / "skinnervation3d-app" / "src" / "skinnervation3d_app" / "resources" / "skin3d_logo.ico"
    _make_mac_app_bundle(apps, "Skinnervation3DApp", app_launcher, icon_ico=app_icon)
 
    # napari-crop
    napari_launcher = _make_mac_launcher(base, NAPARI_ENV, "napari")
    sp = _find_site_packages(_env_dir(base, NAPARI_ENV))
    napari_icon = sp / "napari" / "resources" / "icon.ico" if sp else None
    _make_mac_app_bundle(apps, "Napari", napari_launcher, icon_ico=napari_icon)
 
    print("   Tip: right-click → Open the first time to bypass Gatekeeper.")
 
 
# ── Linux ─────────────────────────────────────────────────────────────────────
 
def _ico_to_png_linux(ico: Path, out: Path) -> bool:
    """Convert .ico to .png using Pillow if available. Returns True on success."""
    try:
        from PIL import Image
        img = Image.open(ico)
        # Pick the largest size available in the .ico
        sizes = getattr(img, "ico", None)
        if sizes:
            img = img.ico.getimage(max(img.ico.sizes()))
        img.save(out, format="PNG")
        return out.exists()
    except Exception:
        return False
 

def _shortcut_linux(_, base: Path, repos: Path):
    apps = Path.home() / ".local" / "share" / "applications"
    apps.mkdir(parents=True, exist_ok=True)
 
    # skin3d-app — call exe directly by full path, no icon
    app_exe = _env_dir(base, APP_ENV) / "bin" / "skin3d-app"
    df = apps / "Skinnervation3DApp.desktop"
    _write_file(df, (
        "[Desktop Entry]\n"
        "Name=Skinnervation3DApp\n"
        "Type=Application\n"
        "Terminal=false\n"
        f'Exec="{app_exe}"\n'
        "Icon=\n"
        "Categories=Science;\n"
    ), executable=True)
    ok(f"App menu entry → {df}")
 
    # napari — call exe directly by full path
    napari_exe = _env_dir(base, NAPARI_ENV) / "bin" / "napari"
 
    # Copy napari icon to ~/.local/share/icons/ and reference by name
    icons_dir = Path.home() / ".local" / "share" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)
    napari_icon_name = ""
    sp = _find_site_packages(_env_dir(base, NAPARI_ENV))
    if sp:
        napari_ico = sp / "napari" / "resources" / "icon.ico"
        png_dest = icons_dir / "napari.png"
        if _ico_to_png_linux(napari_ico, png_dest):
            ok(f"Napari icon installed → {png_dest}")
            napari_icon_name = "napari"
            run(["gtk-update-icon-cache", "-f", "-t", str(icons_dir)],
                check=False, capture=True)
        else:
            warn("Icon conversion failed — napari will use default icon")
 
    df2 = apps / "Napari.desktop"
    _write_file(df2, (
        "[Desktop Entry]\n"
        "Name=Napari\n"
        "Type=Application\n"
        "Terminal=false\n"
        f'Exec="{napari_exe}"\n'
        f"Icon={napari_icon_name}\n"
        "Categories=Science;\n"
    ), executable=True)
    ok(f"App menu entry → {df2}")
 


# ── Entry point ───────────────────────────────────────────────────────────────

def create_shortcuts(base: Path, repos: Path):
    if SYSTEM == "Windows":
        desktop = Path.home() / "Desktop"
        desktop.mkdir(exist_ok=True)
        _shortcut_windows(desktop, base, repos)
    elif SYSTEM == "Darwin":
        _shortcut_mac(None, base, repos)
    else:
        _shortcut_linux(None, base, repos)


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
        "Where should the software be installed (source code will be cloned here)? \nNote: "
        "it is important to give a full filesystem path (e.g. C:/Users/JaneDoe). ",
        str(default_install),
    ))

    try:
        install_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        err(f"Could not create installation folder! Please enter a valid path.")
        raise e

    data_dir = Path(ask(
        "Data directory (where your imaging data lives)",
        str(Path.home() / "Documents")
    ))

    if not data_dir.exists():
        err(f"Data directory does not exist! Please enter a valid path.")
        raise FileNotFoundError

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

    create_shortcuts(base, repos)

    # ── Done ───────────────────────────────────────────────────────────────────
    header("Installation complete! 🎉")
    print(
        f"\n  App installed to : {install_dir}"
        f"\n  config.py        : {config_path}"
        f"\n  Conda envs       : {APP_ENV}  |  {NAPARI_ENV}"
        f"\n"
        f"\n  ▶  Windows: double-click the shortcuts on your Desktop."
        f"\n  ▶  macOS: open ~/Applications and double-click the app."
        f"\n  ▶  Linux: find 'Skinnervation3DApp' and 'Napari' in your app launcher."
        f"\n"
        f"\n  Manual launch in Miniforge prompt/terminal (if shortcut fails):"
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
