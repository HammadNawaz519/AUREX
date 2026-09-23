"""Voice Interaction Surface for AUREX.

Inspired by sound waves and voice flow, creating a calm and responsive experience.
High-performance rendering with zero-CPU idle state (timer stops completely when idle).
"""

import math
from typing import List
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QLinearGradient, QBrush
)
from app.core.events import AgentState, get_event_bus
from app.ui.themes import AurexTheme


class VoiceInteractionSurface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = AgentState.IDLE
        self.tick = 0.0
        self.audio_level = 0.20
        self.num_bars = 58

        # 30 FPS animation timer - ONLY runs during active states
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(33)  # 30 FPS
        self.anim_timer.timeout.connect(self._on_tick)

        self.setMinimumSize(460, 180)
        self.setSizeIncrement(1, 1)

        # Baseline tripartite wave heights matching user reference design
        self._idle_heights = self._generate_idle_envelope(self.num_bars)

        # Subscribe to agent state changes
        get_event_bus().subscribe("state_changed", self._on_state_changed)

    def _generate_idle_envelope(self, count: int) -> List[float]:
        """Pre-compute tripartite wave envelope matching reference design."""
        heights = []
        # Three harmonic peak centers at 0.22, 0.52, 0.80
        centers = [(0.22, 0.82, 0.08), (0.52, 0.95, 0.09), (0.80, 0.88, 0.08)]
        for i in range(count):
            norm = i / (count - 1)
            val = 0.08
            for c, amp, width in centers:
                val += amp * math.exp(-((norm - c) ** 2) / (2.0 * (width ** 2)))

            # Natural voice bar variation
            sub_mod = 0.72 + 0.38 * math.sin(i * 1.85) * math.cos(i * 0.9)
            bar_h = val * sub_mod
            # Taper outer edges
            edge_taper = math.sin(norm * math.pi) ** 0.45
            heights.append(max(0.08, min(0.96, bar_h * edge_taper)))
        return heights

    def _on_state_changed(self, state: AgentState):
        self.set_state(state)

    def set_state(self, state: AgentState):
        self.state = state

        if state == AgentState.IDLE:
            # STOP timer to guarantee 0.0% CPU when idle
            if self.anim_timer.isActive():
                self.anim_timer.stop()
            self.update()
        else:
            # START timer only when assistant is active
            if not self.anim_timer.isActive():
                self.anim_timer.start()

    def set_audio_level(self, level: float):
        self.audio_level = max(0.05, min(1.0, level))
        if self.state == AgentState.LISTENING and not self.anim_timer.isActive():
            self.update()

    def _on_tick(self):
        if self.state == AgentState.LISTENING:
            self.tick += 0.09
        elif self.state == AgentState.SPEAKING:
            self.tick += 0.13
        elif self.state == AgentState.THINKING:
            self.tick += 0.07
        elif self.state == AgentState.EXECUTING:
            self.tick += 0.15
        else:
            self.tick += 0.04

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()
        cy = h / 2.0
        max_bar_h = (h - 20) / 2.0

        bar_count = self.num_bars
        total_spacing = w - 48
        bar_spacing = total_spacing / bar_count
        bar_width = max(2.5, min(4.5, bar_spacing * 0.58))
        start_x = (w - (bar_count * bar_spacing)) / 2.0

        for i in range(bar_count):
            norm = i / (bar_count - 1)
            bx = start_x + (i * bar_spacing) + (bar_spacing / 2.0)

            # Compute bar height fraction (0.05 to 1.0)
            if self.state == AgentState.IDLE:
                amp = self._idle_heights[i]
            elif self.state == AgentState.LISTENING:
                base = self._idle_heights[i]
                ripple = math.sin(norm * 12.0 - self.tick * 3.6) * 0.28 + math.cos(norm * 6.0 + self.tick * 2.1) * 0.08
                amp = max(0.08, min(0.98, base * (1.0 + self.audio_level * 1.6) + ripple * self.audio_level))
            elif self.state == AgentState.THINKING:
                wave1 = math.sin(norm * 9.0 + self.tick * 2.2) * 0.35
                wave2 = math.cos(norm * 15.0 - self.tick * 3.2) * 0.2
                amp = max(0.10, min(0.92, 0.4 + wave1 + wave2))
            elif self.state == AgentState.SPEAKING:
                vocal = (math.sin(self.tick * 6.0 + i * 0.35) * 0.26 +
                         math.sin(self.tick * 11.5 + i * 0.55) * 0.14 +
                         math.cos(self.tick * 3.2 + norm * 4.0) * 0.06)
                amp = max(0.12, min(0.98, self._idle_heights[i] * 1.35 + vocal))
            elif self.state == AgentState.EXECUTING:
                sweep = math.exp(-((norm - ((self.tick * 0.32) % 1.25)) ** 2) / 0.035)
                amp = max(0.08, min(0.95, self._idle_heights[i] * 0.5 + sweep * 0.75))
            elif self.state == AgentState.ERROR:
                amp = max(0.08, min(0.65, self._idle_heights[i] * (0.8 + 0.2 * math.sin(self.tick * 4.0))))
            else:
                amp = self._idle_heights[i]

            bar_half_h = max(2.5, amp * max_bar_h)

            col = self._get_gradient_color(norm)
            pen = QPen(col, bar_width, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(int(bx), int(cy - bar_half_h), int(bx), int(cy + bar_half_h))

    def _get_gradient_color(self, norm: float) -> QColor:
        """Interpolate smooth multi-stop gradient matching user image."""
        if self.state == AgentState.ERROR:
            r = int(244 * (1.0 - norm * 0.3))
            g = int(63 + norm * 40)
            b = int(94 + norm * 60)
            return QColor(r, g, b, 230)

        # Smooth progression: Pink (#EC4899) -> Purple (#A855F7) -> Periwinkle (#818CF8) -> Cyan (#38BDF8)
        if norm < 0.33:
            t = norm / 0.33
            r = int(236 + (168 - 236) * t)
            g = int(72 + (85 - 72) * t)
            b = int(153 + (247 - 153) * t)
        elif norm < 0.66:
            t = (norm - 0.33) / 0.33
            r = int(168 + (129 - 168) * t)
            g = int(85 + (140 - 85) * t)
            b = int(247 + (248 - 247) * t)
        else:
            t = (norm - 0.66) / 0.34
            r = int(129 + (56 - 129) * t)
            g = int(140 + (189 - 140) * t)
            b = int(248 + (248 - 248) * t)

        alpha = 245 if self.state != AgentState.IDLE else 215
        return QColor(r, g, b, alpha)


# Backwards compatibility alias
AurexOrb = VoiceInteractionSurface
