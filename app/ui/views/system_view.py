"""Live hardware monitor and process diagnostics view for AUREX."""

import psutil
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView, QGridLayout
)
from PySide6.QtCore import Qt, QTimer
from app.ui.themes import AurexTheme


class MetricCard(QFrame):
    def __init__(self, title: str, unit: str = "%", parent=None):
        super().__init__(parent)
        self.setObjectName("cardFrame")
        self.unit = unit

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_SECONDARY}; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.title_lbl)

        self.val_lbl = QLabel(f"0{self.unit}")
        self.val_lbl.setStyleSheet(f"font-size: 26px; font-weight: 800; color: {AurexTheme.ACCENT_CYAN};")
        layout.addWidget(self.val_lbl)

        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {AurexTheme.BG_SURFACE};
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {AurexTheme.ACCENT_CYAN};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.bar)

        self.sub_lbl = QLabel("")
        self.sub_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self.sub_lbl)

    def update_val(self, val: float, sub_text: str = ""):
        self.val_lbl.setText(f"{val:.1f}{self.unit}")
        self.bar.setValue(int(val))
        if sub_text:
            self.sub_lbl.setText(sub_text)


class SystemView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

        # Telemetry timer - ONLY active when the view is visible
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_telemetry)

    def showEvent(self, event):
        super().showEvent(event)
        self.update_telemetry()
        if not self.timer.isActive():
            self.timer.start(2500)

    def hideEvent(self, event):
        super().hideEvent(event)
        if self.timer.isActive():
            self.timer.stop()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Header
        top_row = QHBoxLayout()
        header = QLabel("System Hardware & Telemetry")
        header.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {AurexTheme.ACCENT_CYAN};")
        top_row.addWidget(header)
        top_row.addStretch()

        self.uptime_lbl = QLabel("Uptime: -")
        self.uptime_lbl.setStyleSheet(f"color: {AurexTheme.TEXT_MUTED};")
        top_row.addWidget(self.uptime_lbl)
        layout.addLayout(top_row)

        # 4 Metric Cards Grid
        grid = QGridLayout()
        grid.setSpacing(16)

        self.card_cpu = MetricCard("CPU USAGE", "%")
        self.card_ram = MetricCard("MEMORY ALLOCATION", "%")
        self.card_disk_c = MetricCard("C: DRIVE (READ ONLY)", "%")
        self.card_disk_d = MetricCard("D: WORKSPACE DRIVE", "%")

        grid.addWidget(self.card_cpu, 0, 0)
        grid.addWidget(self.card_ram, 0, 1)
        grid.addWidget(self.card_disk_c, 1, 0)
        grid.addWidget(self.card_disk_d, 1, 1)

        layout.addLayout(grid)

        # Process List Section
        proc_header = QLabel("Top Resource Consumers")
        proc_header.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(proc_header)

        self.proc_table = QTableWidget(0, 4)
        self.proc_table.setHorizontalHeaderLabels(["PID", "Process Name", "CPU %", "Memory (MB)"])
        self.proc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.proc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.proc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.proc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.proc_table, 1)

    def update_telemetry(self):
        try:
            # CPU
            cpu_pct = psutil.cpu_percent()
            cores = psutil.cpu_count(logical=True)
            self.card_cpu.update_val(cpu_pct, f"{cores} Logical Cores Active")

            # RAM
            mem = psutil.virtual_memory()
            used_gb = mem.used / (1024 ** 3)
            tot_gb = mem.total / (1024 ** 3)
            self.card_ram.update_val(mem.percent, f"{used_gb:.1f} GB / {tot_gb:.1f} GB Used")

            # Disk C:
            try:
                c_usage = psutil.disk_usage("C:\\")
                c_free = c_usage.free / (1024 ** 3)
                self.card_disk_c.update_val(c_usage.percent, f"{c_free:.1f} GB Free (Protected)")
            except Exception:
                pass

            # Disk D:
            try:
                d_usage = psutil.disk_usage("D:\\")
                d_free = d_usage.free / (1024 ** 3)
                self.card_disk_d.update_val(d_usage.percent, f"{d_free:.1f} GB Free (Workspace)")
            except Exception:
                self.card_disk_d.update_val(0, "D: Drive Not Mounted")

            # Top Processes
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    mem_mb = round(p.info['memory_info'].rss / (1024 * 1024), 1) if p.info.get('memory_info') else 0
                    procs.append({
                        "pid": p.info['pid'],
                        "name": p.info['name'],
                        "cpu": p.info.get('cpu_percent') or 0.0,
                        "mem": mem_mb
                    })
                except Exception:
                    continue

            procs.sort(key=lambda x: (x['cpu'], x['mem']), reverse=True)
            top5 = procs[:5]

            self.proc_table.setRowCount(len(top5))
            for row, p in enumerate(top5):
                self.proc_table.setItem(row, 0, QTableWidgetItem(str(p['pid'])))
                self.proc_table.setItem(row, 1, QTableWidgetItem(str(p['name'])))
                self.proc_table.setItem(row, 2, QTableWidgetItem(f"{p['cpu']:.1f}%"))
                self.proc_table.setItem(row, 3, QTableWidgetItem(f"{p['mem']:.1f} MB"))

        except Exception:
            pass
