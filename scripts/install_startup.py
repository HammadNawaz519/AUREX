"""Register AUREX to start on Windows login without admin elevation."""

import sys
import os
import winreg
from pathlib import Path

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "AUREX_Assistant"


def install():
    vbs_path = Path(__file__).resolve().parent.parent / "run_aurex_silent.vbs"
    if not vbs_path.exists():
        vbs_path = Path(__file__).resolve().parent.parent / "run_aurex.bat"

    target_cmd = f'wscript.exe "{vbs_path}"' if vbs_path.suffix == ".vbs" else f'"{vbs_path}"'

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, target_cmd)
        print(f"SUCCESS: AUREX registered to start silently on Windows login (daemon mode).")
        print(f"Startup Command: {target_cmd}")
        print(f"Registry Key: HKCU\\{REG_PATH}\\{APP_NAME}")
    except Exception as e:
        print(f"FAILED to register startup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    install()
