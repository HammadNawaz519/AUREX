"""System hardware monitoring, process diagnostics, and telemetry tools for AUREX."""

import os
import psutil
import datetime
from typing import Dict, Any, List
from app.tools.base import BaseTool, ToolResult


class GetSystemInfoTool(BaseTool):
    name = "get_system_information"
    description = "Retrieve comprehensive system hardware metrics: CPU, RAM, Disk, Battery, and top resource consumers."
    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }
    is_write = False

    def execute(self, **kwargs) -> ToolResult:
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.2)
            cpu_count = psutil.cpu_count(logical=True)
            cpu_freq = psutil.cpu_freq()

            # RAM
            mem = psutil.virtual_memory()

            # Disks
            disks = []
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "device": part.device,
                        "mountpoint": part.mountpoint,
                        "total_gb": round(usage.total / (1024 ** 3), 1),
                        "used_gb": round(usage.used / (1024 ** 3), 1),
                        "free_gb": round(usage.free / (1024 ** 3), 1),
                        "percent": usage.percent
                    })
                except Exception:
                    continue

            # Battery
            battery = psutil.sensors_battery()
            battery_info = None
            if battery:
                battery_info = {
                    "percent": battery.percent,
                    "power_plugged": battery.power_plugged,
                    "secsleft": battery.secsleft if battery.secsleft != psutil.POWER_TIME_UNLIMITED else -1
                }

            # Top CPU consuming processes
            top_cpu = []
            for proc in sorted(psutil.process_iter(['pid', 'name', 'cpu_percent']), key=lambda p: p.info.get('cpu_percent') or 0, reverse=True)[:5]:
                try:
                    top_cpu.append({
                        "pid": proc.info['pid'],
                        "name": proc.info['name'],
                        "cpu_percent": proc.info['cpu_percent']
                    })
                except Exception:
                    continue

            data = {
                "cpu": {
                    "usage_percent": cpu_percent,
                    "cores": cpu_count,
                    "current_freq_mhz": round(cpu_freq.current, 1) if cpu_freq else None
                },
                "memory": {
                    "total_gb": round(mem.total / (1024 ** 3), 1),
                    "used_gb": round(mem.used / (1024 ** 3), 1),
                    "available_gb": round(mem.available / (1024 ** 3), 1),
                    "percent": mem.percent
                },
                "disks": disks,
                "battery": battery_info,
                "top_cpu_processes": top_cpu
            }

            msg = (
                f"CPU Usage: {cpu_percent}% across {cpu_count} cores. "
                f"RAM Usage: {mem.percent}% ({round(mem.used / (1024**3), 1)}GB / {round(mem.total / (1024**3), 1)}GB). "
            )
            if top_cpu and top_cpu[0]["cpu_percent"] and top_cpu[0]["cpu_percent"] > 5.0:
                msg += f"Top process is {top_cpu[0]['name']} at {top_cpu[0]['cpu_percent']}% CPU."

            return ToolResult(success=True, data=data, message=msg)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to gather system information: {e}")


class ListProcessesTool(BaseTool):
    name = "list_processes"
    description = "List currently running processes sorted by memory or CPU consumption."
    parameters = {
        "type": "object",
        "properties": {
            "sort_by": {"type": "string", "enum": ["cpu", "memory"], "description": "Sort criteria"},
            "limit": {"type": "integer", "description": "Number of processes to return (default 15)"}
        }
    }
    is_write = False

    def execute(self, sort_by: str = "cpu", limit: int = 15, **kwargs) -> ToolResult:
        try:
            procs = []
            for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
                try:
                    mem_mb = round(p.info['memory_info'].rss / (1024 * 1024), 1) if p.info.get('memory_info') else 0
                    procs.append({
                        "pid": p.info['pid'],
                        "name": p.info['name'],
                        "cpu_percent": p.info.get('cpu_percent') or 0.0,
                        "memory_mb": mem_mb
                    })
                except Exception:
                    continue

            key = "cpu_percent" if sort_by == "cpu" else "memory_mb"
            procs.sort(key=lambda x: x[key], reverse=True)
            subset = procs[:limit]
            return ToolResult(success=True, data=subset, message=f"Retrieved top {len(subset)} processes sorted by {sort_by}")
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to list processes: {e}")
