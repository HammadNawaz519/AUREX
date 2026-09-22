"""Design tokens, color palettes, and stylesheets for AUREX."""

class AurexTheme:
    # Color Palette (Futuristic Obsidian & Radiant Cyan)
    BG_DARK = "#090b10"
    BG_CARD = "#11141c"
    BG_SURFACE = "#161b26"
    BG_HOVER = "#1c2333"

    BORDER_SUBTLE = "#1e2433"
    BORDER_ACCENT = "#00e5ff"

    TEXT_PRIMARY = "#f8fafc"
    TEXT_SECONDARY = "#94a3b8"
    TEXT_MUTED = "#64748b"

    ACCENT_CYAN = "#00e5ff"
    ACCENT_BLUE = "#38bdf8"
    ACCENT_VIOLET = "#a855f7"
    ACCENT_EMERALD = "#10b981"
    ACCENT_AMBER = "#f59e0b"
    ACCENT_ROSE = "#f43f5e"

    @classmethod
    def get_main_stylesheet(cls) -> str:
        return f"""
        QWidget {{
            background-color: {cls.BG_DARK};
            color: {cls.TEXT_PRIMARY};
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            font-size: 13px;
        }}

        QMainWindow {{
            background-color: {cls.BG_DARK};
        }}

        QFrame#cardFrame {{
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER_SUBTLE};
            border-radius: 12px;
        }}

        QPushButton {{
            background-color: {cls.BG_SURFACE};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER_SUBTLE};
            border-radius: 8px;
            padding: 8px 16px;
            font-weight: 500;
        }}

        QPushButton:hover {{
            background-color: {cls.BG_HOVER};
            border: 1px solid {cls.ACCENT_CYAN};
        }}

        QPushButton:pressed {{
            background-color: #0c0f17;
        }}

        QPushButton#primaryButton {{
            background-color: {cls.ACCENT_CYAN};
            color: #040810;
            border: none;
            font-weight: 600;
        }}

        QPushButton#primaryButton:hover {{
            background-color: #33ecff;
        }}

        QPushButton#dangerButton {{
            background-color: rgba(244, 63, 94, 0.15);
            color: {cls.ACCENT_ROSE};
            border: 1px solid rgba(244, 63, 94, 0.4);
        }}

        QPushButton#dangerButton:hover {{
            background-color: rgba(244, 63, 94, 0.3);
            border: 1px solid {cls.ACCENT_ROSE};
        }}

        QLineEdit {{
            background-color: {cls.BG_SURFACE};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER_SUBTLE};
            border-radius: 20px;
            padding: 10px 18px;
            font-size: 14px;
            selection-background-color: {cls.ACCENT_CYAN};
            selection-color: #040810;
        }}

        QLineEdit:focus {{
            border: 1px solid {cls.ACCENT_CYAN};
            background-color: #171d2b;
        }}

        QScrollBar:vertical {{
            border: none;
            background: {cls.BG_DARK};
            width: 6px;
            margin: 0px;
        }}

        QScrollBar::handle:vertical {{
            background: {cls.BORDER_SUBTLE};
            min-height: 20px;
            border-radius: 3px;
        }}

        QScrollBar::handle:vertical:hover {{
            background: {cls.TEXT_MUTED};
        }}

        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}

        QTableWidget {{
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER_SUBTLE};
            border-radius: 8px;
            gridline-color: {cls.BORDER_SUBTLE};
        }}

        QHeaderView::section {{
            background-color: {cls.BG_SURFACE};
            color: {cls.TEXT_SECONDARY};
            padding: 6px;
            border: 1px solid {cls.BORDER_SUBTLE};
            font-weight: 600;
        }}

        QListWidget {{
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER_SUBTLE};
            border-radius: 8px;
            padding: 6px;
        }}

        QListWidget::item {{
            padding: 8px;
            border-radius: 6px;
        }}

        QListWidget::item:hover {{
            background-color: {cls.BG_HOVER};
        }}

        QListWidget::item:selected {{
            background-color: rgba(0, 229, 255, 0.15);
            color: {cls.ACCENT_CYAN};
            border: 1px solid {cls.ACCENT_CYAN};
        }}
        """
