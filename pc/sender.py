"""
PC Hardware Monitor - Sender Client
Collects CPU, RAM, and GPU hardware telemetry from the host PC
and transmits real-time JSON packets to a Raspberry Pi Pico W receiver over HTTP.
"""

import os
import sys
import time
import json
import shutil
import logging
import argparse
import platform
import subprocess
from typing import Dict, Any, Optional

try:
    import psutil
except ImportError:
    psutil = None

# Optional Windows-specific WMI support for hardware sensors
try:
    import wmi
except ImportError:
    wmi = None

try:
    import requests
except ImportError:
    requests = None

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("pc-monitor")


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from JSON file with sensible default fallbacks."""
    default_config = {
        "pico_ip": "192.168.1.105",
        "pico_port": 80,
        "endpoint": "/api/metrics",
        "polling_interval_seconds": 2.0,
        "request_timeout_seconds": 3.0
    }

    candidates = [
        config_path,
        os.path.join(os.path.dirname(__file__), "config.json"),
        os.path.join(os.path.dirname(__file__), "config.template.json")
    ]

    for path in candidates:
        if path and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    default_config.update(data)
                    logger.debug(f"Loaded configuration from {path}")
                    break
            except Exception as e:
                logger.warning(f"Failed to parse config file at {path}: {e}")

    return default_config


class HardwareReader:
    """Reads system performance metrics including CPU, RAM, and GPU."""

    def __init__(self):
        self._wmi_obj = None
        self._has_nvidia_smi = shutil.which("nvidia-smi") is not None
        if sys.platform == "win32" and wmi is not None:
            try:
                # Initialize WMI namespace for hardware queries
                self._wmi_obj = wmi.WMI(namespace="root\\cimv2")
            except Exception as e:
                logger.warning(f"Could not initialize WMI cimv2 namespace: {e}")

    def get_cpu_temperature(self) -> Optional[float]:
        """Attempt to read CPU temperature via WMI thermal zone or LibreHardwareMonitor."""
        if sys.platform == "win32" and wmi is not None:
            try:
                w_thermal = wmi.WMI(namespace="root\\wmi")
                thermal_zones = w_thermal.MSAcpi_ThermalZoneTemperature()
                if thermal_zones:
                    # Raw temperature in tenths of Kelvin
                    raw_temp = thermal_zones[0].CurrentTemperature
                    temp_c = (raw_temp / 10.0) - 273.15
                    return round(temp_c, 1)
            except Exception:
                pass

            # Fallback to OpenHardwareMonitor / LibreHardwareMonitor if running
            try:
                w_ohm = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                sensors = w_ohm.Sensor()
                for sensor in sensors:
                    if sensor.SensorType == "Temperature" and "CPU" in sensor.Name:
                        return round(float(sensor.Value), 1)
            except Exception:
                pass

        return None

    def get_cpu_metrics(self) -> Dict[str, Any]:
        """Fetch real-time CPU usage, core count, frequency, and temperature."""
        if not psutil:
            return {"error": "psutil library not available"}

        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False) or cpu_count_logical

        freq = psutil.cpu_freq()
        cpu_freq_mhz = round(freq.current, 1) if freq else None

        cpu_temp = self.get_cpu_temperature()

        return {
            "usage_percent": cpu_percent,
            "cores_logical": cpu_count_logical,
            "cores_physical": cpu_count_physical,
            "freq_mhz": cpu_freq_mhz,
            "temp_c": cpu_temp
        }

    def get_ram_metrics(self) -> Dict[str, Any]:
        """Fetch system memory (RAM) and swap allocation statistics."""
        if not psutil:
            return {"error": "psutil library not available"}

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round(mem.used / (1024 ** 3), 2),
            "free_gb": round(mem.available / (1024 ** 3), 2),
            "usage_percent": mem.percent,
            "swap_used_gb": round(swap.used / (1024 ** 3), 2),
            "swap_percent": swap.percent
        }
