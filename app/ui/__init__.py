"""UI package for AUREX."""

from app.ui.themes import AurexTheme
from app.ui.orb import AurexOrb
from app.ui.sidebar import AurexSidebar
from app.ui.activity import ActivityFeedWidget
from app.ui.dialogs import ConfirmationDialog, show_confirmation_modal
from app.ui.main_window import AurexMainWindow

__all__ = [
    "AurexTheme",
    "AurexOrb",
    "AurexSidebar",
    "ActivityFeedWidget",
    "ConfirmationDialog",
    "show_confirmation_modal",
    "AurexMainWindow"
]
