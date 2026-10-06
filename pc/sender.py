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

    def get_gpu_metrics(self) -> Dict[str, Any]:
        """Parse GPU hardware telemetry using nvidia-smi with WMI fallback."""
        # 1. Try querying NVIDIA Management Interface (nvidia-smi)
        if self._has_nvidia_smi:
            try:
                cmd = [
                    "nvidia-smi",
                    "--query-gpu=name,utilization.gpu,utilization.memory,memory.total,memory.used,temperature.gpu",
                    "--format=csv,noheader,nounits"
                ]
                output = subprocess.check_output(cmd, encoding="utf-8", stderr=subprocess.DEVNULL)
                lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
                if lines:
                    parts = [p.strip() for p in lines[0].split(",")]
                    if len(parts) >= 6:
                        gpu_name = parts[0]
                        gpu_util = float(parts[1]) if parts[1].replace(".", "", 1).isdigit() else 0.0
                        mem_total_mb = float(parts[3]) if parts[3].replace(".", "", 1).isdigit() else 0.0
                        mem_used_mb = float(parts[4]) if parts[4].replace(".", "", 1).isdigit() else 0.0
                        gpu_temp = float(parts[5]) if parts[5].replace(".", "", 1).isdigit() else None
                        mem_percent = round((mem_used_mb / mem_total_mb * 100), 1) if mem_total_mb > 0 else 0.0

                        return {
                            "detected": True,
                            "name": gpu_name,
                            "usage_percent": gpu_util,
                            "memory_used_mb": mem_used_mb,
                            "memory_total_mb": mem_total_mb,
                            "memory_percent": mem_percent,
                            "temp_c": gpu_temp
                        }
            except Exception as e:
                logger.debug(f"nvidia-smi query failed: {e}")

        # 2. Check OpenHardwareMonitor / LibreHardwareMonitor sensors if active
        if sys.platform == "win32" and wmi is not None:
            try:
                w_ohm = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                sensors = w_ohm.Sensor()
                gpu_load = None
                gpu_temp = None
                for s in sensors:
                    if "GPU" in s.Name:
                        if s.SensorType == "Load" and "Core" in s.Name:
                            gpu_load = round(float(s.Value), 1)
                        elif s.SensorType == "Temperature" and "Core" in s.Name:
                            gpu_temp = round(float(s.Value), 1)

                if gpu_load is not None or gpu_temp is not None:
                    return {
                        "detected": True,
                        "name": "Discrete GPU",
                        "usage_percent": gpu_load if gpu_load is not None else 0.0,
                        "memory_used_mb": None,
                        "memory_total_mb": None,
                        "memory_percent": None,
                        "temp_c": gpu_temp
                    }
            except Exception:
                pass

        # 3. Fallback to Windows WMI Video Controller query
        if self._wmi_obj:
            try:
                controllers = self._wmi_obj.Win32_VideoController()
                if controllers:
                    primary_gpu = controllers[0]
                    gpu_name = getattr(primary_gpu, "Name", "Unknown GPU")
                    raw_ram = getattr(primary_gpu, "AdapterRAM", 0)
                    total_ram_mb = round(int(raw_ram) / (1024 ** 2), 1) if raw_ram else None
                    return {
                        "detected": True,
                        "name": gpu_name,
                        "usage_percent": None,
                        "memory_used_mb": None,
                        "memory_total_mb": total_ram_mb,
                        "memory_percent": None,
                        "temp_c": None
                    }
            except Exception as e:
                logger.debug(f"WMI video controller lookup failed: {e}")

        return {
            "detected": False,
            "name": "N/A",
            "usage_percent": None,
            "memory_used_mb": None,
            "memory_total_mb": None,
            "memory_percent": None,
            "temp_c": None
        }
