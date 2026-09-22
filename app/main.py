"""AUREX - Personal Desktop AI Assistant Entry Point."""

import sys
import os
import logging
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

# Ensure root folder is on Python sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.config.settings import get_settings
from app.memory.database import get_db
from app.ui.main_window import AurexMainWindow
from app.ai import get_ai_provider


def setup_logging():
    settings = get_settings()
    log_dir = Path(settings.workspace_root) / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "aurex.log"
    except Exception:
        log_file = root_dir / "aurex.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )


def main():
    # 1. Setup logging and workspace paths
    setup_logging()
    logger = logging.getLogger("AUREX")
    logger.info("Initializing AUREX Desktop AI Assistant...")

    # 2. Initialize settings and memory
    settings = get_settings()
    db = get_db()

    # 3. Asynchronously check AI Provider health (non-blocking for fast startup)
    import threading
    def _check_ai():
        try:
            provider = get_ai_provider()
            healthy = provider.health_check()
            if healthy:
                logger.info(f"AI Provider '{settings.ai_provider}' is connected and ready.")
            else:
                logger.warning(f"AI Provider '{settings.ai_provider}' connectivity check returned false. Local fallback active.")
        except Exception as e:
            logger.warning(f"AI Provider initialization warning: {e}. System tools remain fully functional.")

    threading.Thread(target=_check_ai, daemon=True, name="AurexProviderCheck").start()

    # 4. Launch PySide6 GUI Application
    app = QApplication(sys.argv)
    app.setApplicationName("AUREX")
    app.setOrganizationName("AUREX")

    window = AurexMainWindow()
    window.show()

    logger.info("AUREX GUI running.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
