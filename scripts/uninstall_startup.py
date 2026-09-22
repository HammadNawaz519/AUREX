"""Unregister AUREX from Windows startup."""

import sys
import winreg

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "AUREX_Assistant"


def uninstall():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        print(f"SUCCESS: AUREX unregistered from Windows startup.")
    except FileNotFoundError:
        print("AUREX was not registered in Windows startup.")
    except Exception as e:
        print(f"Error unregistering: {e}")


if __name__ == "__main__":
    uninstall()
