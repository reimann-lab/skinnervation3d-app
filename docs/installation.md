# Installation Guide

## What you need before starting

| Requirement | Notes |
|---|---|
| **Internet connection** | To download Miniforge, conda packages, and source code |
| **Git** | [git-scm.com](https://git-scm.com) — the installer will tell you if it's missing |
| **GitHub PAT** | Personal Access Token for the private repositories (see below) |
| **~5 GB free disk space** | For Miniforge, two conda environments, and source code |

---

## Getting a GitHub Personal Access Token (PAT)

1. Go to <https://github.com/settings/tokens>
2. Click **"Generate new token (classic)"**
3. Give it a name (e.g. `SkInnervation3D install`)
4. Under *Scopes*, tick **`repo`** (full control of private repositories)
5. Click **"Generate token"** and copy it — you'll paste it during installation
6. ⚠ The token is shown only once. Keep it somewhere safe until the install is done.

---

## Installation steps

### macOS / Linux

1. Download **`install.sh`** and **`install.py`** into the same folder
2. Open a terminal in that folder and run:
   ```bash
   bash install.sh
   ```
   Or on macOS you can double-click `install.sh` in Finder (right-click → Open).

### Windows

1. Download **`install.bat`** and **`install.py`** into the same folder
2. Double-click **`install.bat`**
   - If Windows shows a security warning, click **"Run anyway"**
   - If you get a permission error, right-click → **"Run as administrator"**

---

## What the installer does

1. **Checks for Git** — exits with an error if not found
2. **Installs Miniforge** — if conda is not already on your system, Miniforge is downloaded and installed silently into `~/miniforge3`
3. **Asks you three questions:**
   - Where to install the app files (default: `~/SkInnervation3D`)
   - Where your imaging data lives (used to pre-populate the file browser)
   - Your GitHub PAT (typed invisibly, used only for cloning — never stored)
4. **Clones all repositories** into `<install_dir>/repos/`
5. **Creates two conda environments:**
   - `napari-crop` — for the napari plugin
   - `skin3d-app` — for the UI app and analysis packages
6. **Writes a config file** at `<install_dir>/config/settings.env`
7. **Creates a desktop shortcut** — double-click to launch the app

---

## Updating

To update all packages to the latest version, re-run the installer. It will
`git pull` each repo instead of re-cloning, and skip environment creation if
the envs already exist.

To force a full reinstall of an environment:
```bash
conda env remove -n skin3d-app
conda env remove -n napari-crop
```
Then re-run the installer.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `git: command not found` | Install Git from [git-scm.com](https://git-scm.com) |
| `Authentication failed` cloning repos | Check your PAT has `repo` scope and hasn't expired |
| App shortcut doesn't open | Open a terminal, run `conda activate skin3d-app` then `skin3d-app` |
| Windows: PowerShell execution policy error | Run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` in PowerShell, then re-run `install.bat` |
| Conda env creation fails | Delete the partial env with `conda env remove -n skin3d-app` and re-run |

---

## Note on conda-lock (reproducible environments)

If your `environment.yml` files are converted to `conda-lock.yml` lock files, the
installer will automatically prefer them — giving you faster, fully reproducible
installs.  To generate lock files from your repos:

```bash
pip install conda-lock
conda-lock lock -f environment.yml  # run inside each repo
```

Commit the resulting `conda-lock.yml` to each repo.
