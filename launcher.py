"""
Argon Hybrid Launcher (Build Once, Hot-Update Forever)
------------------------------------------------------
This launcher bundles all heavy dependencies (PyQt5, Pillow, mss, pytesseract,
requests, keyboard) into ArgonTranslator.exe ONCE.

On every launch:
1. It checks config.json for `update_url` (or local `.git`) and silently pulls
   the latest `argon_overlay_translator.py` from GitHub in < 0.5s.
2. It executes the external `argon_overlay_translator.py` directly using the
   bundled Python runtime — so you NEVER need to re-run PyInstaller after
   pushing code changes to Git.
"""

import sys
import os
import json
import time
import runpy
import shutil
import subprocess

# Pre-import all required packages so PyInstaller bundles them into the .exe
import requests
from PIL import Image
import mss
import pytesseract
import keyboard
import PyQt5.QtCore
import PyQt5.QtGui
import PyQt5.QtWidgets

_EXE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
if (
    os.path.basename(_EXE_DIR).lower() == "dist"
    and os.path.exists(os.path.join(os.path.dirname(_EXE_DIR), "argon_overlay_translator.py"))
):
    APP_DIR = os.path.dirname(_EXE_DIR)
else:
    APP_DIR = _EXE_DIR

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
EXTERNAL_SCRIPT = os.path.join(APP_DIR, "argon_overlay_translator.py")


def normalize_github_raw_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if "github.com/" in url and "/blob/" in url:
        return url.replace("github.com/", "raw.githubusercontent.com/").replace("/blob/", "/")
    if "github.com/" in url and "raw.githubusercontent.com" not in url:
        clean = url.rstrip("/")
        if clean.endswith(".git"):
            clean = clean[:-4]
        parts = clean.split("github.com/")[-1].split("/")
        if len(parts) == 2:
            owner, repo = parts[0], parts[1]
            return f"https://raw.githubusercontent.com/{owner}/{repo}/main/argon_overlay_translator.py"
    return url


def ensure_external_script_exists():
    """If running from a single-file .exe and external script is missing, extract bundled copy."""
    if os.path.exists(EXTERNAL_SCRIPT):
        return
    bundled_dir = getattr(sys, "_MEIPASS", APP_DIR)
    bundled_script = os.path.join(bundled_dir, "argon_overlay_translator.py")
    if os.path.exists(bundled_script) and bundled_script != EXTERNAL_SCRIPT:
        try:
            shutil.copyfile(bundled_script, EXTERNAL_SCRIPT)
        except Exception as e:
            print(f"Warning: Could not extract initial script: {e}")


DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/HocTrinh-dev/overlay-translater/main/argon_overlay_translator.py"


def auto_update_before_launch():
    """Silently fetch latest argon_overlay_translator.py from git or GitHub before launching UI."""
    update_url = DEFAULT_UPDATE_URL
    auto_update = True

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            update_url = normalize_github_raw_url(cfg.get("update_url", DEFAULT_UPDATE_URL)) or DEFAULT_UPDATE_URL
            auto_update = cfg.get("auto_update_on_start", True)
        except Exception:
            pass

    if not auto_update:
        return

    git_dir = os.path.join(APP_DIR, ".git")
    if os.path.isdir(git_dir):
        try:
            proc = subprocess.run(
                ["git", "pull", "--rebase", "--autostash"],
                cwd=APP_DIR,
                capture_output=True,
                timeout=4,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            )
            if proc.returncode == 0:
                return
        except Exception:
            pass

    if update_url:
        try:
            sep = "&" if "?" in update_url else "?"
            resp = requests.get(f"{update_url}{sep}t={int(time.time())}", timeout=3.5)
            if resp.status_code == 200 and "MainStudioWindow" in resp.text:
                with open(EXTERNAL_SCRIPT, "w", encoding="utf-8") as f:
                    f.write(resp.text)
                return
        except Exception:
            pass


if __name__ == "__main__":
    ensure_external_script_exists()
    auto_update_before_launch()

    if os.path.exists(EXTERNAL_SCRIPT):
        sys.path.insert(0, APP_DIR)
        runpy.run_path(EXTERNAL_SCRIPT, run_name="__main__")
    else:
        import argon_overlay_translator
        app = PyQt5.QtWidgets.QApplication(sys.argv)
        studio = argon_overlay_translator.MainStudioWindow()
        studio.show()
        sys.exit(app.exec_())
