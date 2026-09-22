"""UI Views package for AUREX."""

from app.ui.views.home_view import HomeView
from app.ui.views.tasks_view import TasksView
from app.ui.views.learning_view import LearningView
from app.ui.views.memory_view import MemoryView
from app.ui.views.files_view import FilesView
from app.ui.views.apps_view import AppsView
from app.ui.views.system_view import SystemView
from app.ui.views.automations_view import AutomationsView
from app.ui.views.settings_view import SettingsView

__all__ = [
    "HomeView",
    "TasksView",
    "LearningView",
    "MemoryView",
    "FilesView",
    "AppsView",
    "SystemView",
    "AutomationsView",
    "SettingsView"
]

