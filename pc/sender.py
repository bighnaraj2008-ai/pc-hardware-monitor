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
