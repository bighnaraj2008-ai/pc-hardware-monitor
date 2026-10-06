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


def format_payload(
    cpu_metrics: Dict[str, Any],
    ram_metrics: Dict[str, Any],
    gpu_metrics: Dict[str, Any]
) -> Dict[str, Any]:
    """Format collected telemetry into a standardized, compact dictionary payload for transmission."""
    boot_time = psutil.boot_time() if psutil else time.time()
    uptime_seconds = int(time.time() - boot_time)

    payload = {
        "timestamp": int(time.time()),
        "hostname": platform.node(),
        "uptime": uptime_seconds,
        "cpu": {
            "usage": float(cpu_metrics.get("usage_percent", 0.0) or 0.0),
            "temp": cpu_metrics.get("temp_c"),
            "freq": cpu_metrics.get("freq_mhz"),
            "cores": cpu_metrics.get("cores_logical", 1)
        },
        "ram": {
            "usage": float(ram_metrics.get("usage_percent", 0.0) or 0.0),
            "used_gb": float(ram_metrics.get("used_gb", 0.0) or 0.0),
            "total_gb": float(ram_metrics.get("total_gb", 0.0) or 0.0),
            "free_gb": float(ram_metrics.get("free_gb", 0.0) or 0.0)
        },
        "gpu": {
            "detected": bool(gpu_metrics.get("detected", False)),
            "name": str(gpu_metrics.get("name", "N/A")),
            "usage": gpu_metrics.get("usage_percent"),
            "temp": gpu_metrics.get("temp_c"),
            "mem_usage": gpu_metrics.get("memory_percent"),
            "mem_used_mb": gpu_metrics.get("memory_used_mb"),
            "mem_total_mb": gpu_metrics.get("memory_total_mb")
        }
    }
    return payload


def format_payload_json(
    cpu_metrics: Dict[str, Any],
    ram_metrics: Dict[str, Any],
    gpu_metrics: Dict[str, Any]
) -> str:
    """Format and serialize telemetry payload to compact JSON string."""
    return json.dumps(format_payload(cpu_metrics, ram_metrics, gpu_metrics), separators=(",", ":"))


class HttpTransmitter:
    """Handles HTTP POST transmissions of telemetry data with error handling and retry logic."""

    def __init__(self, target_url: str, timeout: float = 3.0):
        self.target_url = target_url
        self.timeout = timeout
        self.session = requests.Session() if requests else None
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": "PCHardwareMonitor/1.0"
        }

    def send(self, payload: Dict[str, Any]) -> bool:
        """Transmit payload via HTTP POST to the Pico W server."""
        if not requests or not self.session:
            logger.error("requests library is not installed. Cannot transmit payload.")
            return False

        json_data = json.dumps(payload, separators=(",", ":"))
        start_time = time.perf_counter()

        try:
            response = self.session.post(
                self.target_url,
                data=json_data,
                headers=self.headers,
                timeout=self.timeout
            )
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)

            if response.status_code == 200:
                logger.info(f"POST {self.target_url} -> 200 OK ({elapsed_ms}ms)")
                return True
            else:
                logger.warning(
                    f"POST {self.target_url} -> HTTP {response.status_code} ({elapsed_ms}ms): {response.text.strip()}"
                )
                return False

        except requests.exceptions.ConnectTimeout:
            logger.error(f"Connection timeout reaching Pico W at {self.target_url} (limit: {self.timeout}s)")
        except requests.exceptions.ReadTimeout:
            logger.error(f"Read timeout waiting for Pico W response at {self.target_url} (limit: {self.timeout}s)")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error reaching Pico W at {self.target_url}: {e}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error during transmission: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Unexpected network error during transmission: {e}")

        return False

    def close(self):
        """Clean up active HTTP session connections."""
        if self.session:
            self.session.close()


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


def parse_arguments() -> argparse.Namespace:
    """Parse command-line options and flags."""
    parser = argparse.ArgumentParser(
        description="PC Hardware Monitor - Real-time telemetry sender for Raspberry Pi Pico W"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to JSON configuration file"
    )
    parser.add_argument(
        "--ip",
        type=str,
        default=None,
        help="Raspberry Pi Pico W IP address (overrides config)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="Target HTTP server port on Pico W (default: 80)"
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="Target API endpoint route (default: /api/metrics)"
    )
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=None,
        help="Telemetry polling and broadcast interval in seconds (default: 2.0)"
    )
    parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=None,
        help="HTTP request connection and read timeout in seconds (default: 3.0)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and print telemetry metrics without sending network requests"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Poll and transmit a single metric packet, then exit"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose debug logging"
    )
    return parser.parse_args()


def main():
    """Main execution loop for continuous hardware telemetry collection and dispatch."""
    args = parse_arguments()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    cfg = load_config(args.config)

    # CLI arguments override JSON config values
    target_ip = args.ip or cfg.get("pico_ip", "192.168.1.105")
    target_port = args.port or cfg.get("pico_port", 80)
    endpoint = args.endpoint or cfg.get("endpoint", "/api/metrics")
    interval = args.interval or cfg.get("polling_interval_seconds", 2.0)
    timeout = args.timeout or cfg.get("request_timeout_seconds", 3.0)

    target_url = f"http://{target_ip}:{target_port}{endpoint}"

    logger.info("=========================================")
    logger.info("   PC Hardware Monitor - Sender Daemon   ")
    logger.info("=========================================")
    logger.info(f"Target URL:        {target_url}")
    logger.info(f"Polling Interval:  {interval}s")
    logger.info(f"Request Timeout:   {timeout}s")
    logger.info(f"Dry Run Mode:      {args.dry_run}")
    logger.info("Press Ctrl+C to terminate sender daemon.\n")

    reader = HardwareReader()
    transmitter = HttpTransmitter(target_url, timeout=timeout) if not args.dry_run else None

    # Warm-up psutil cpu_percent (first call returns 0.0)
    if psutil:
        psutil.cpu_percent(interval=None)

    iteration = 0
    try:
        while True:
            iteration += 1
            start_loop = time.time()

            cpu = reader.get_cpu_metrics()
            ram = reader.get_ram_metrics()
            gpu = reader.get_gpu_metrics()
            payload = format_payload(cpu, ram, gpu)

            cpu_info = f"CPU: {payload['cpu']['usage']}%"
            if payload['cpu']['temp'] is not None:
                cpu_info += f" ({payload['cpu']['temp']}°C)"

            ram_info = f"RAM: {payload['ram']['usage']}% ({payload['ram']['used_gb']}/{payload['ram']['total_gb']}GB)"

            gpu_info = "GPU: N/A"
            if payload['gpu']['detected']:
                gpu_usage = f"{payload['gpu']['usage']}%" if payload['gpu']['usage'] is not None else "Active"
                gpu_info = f"GPU: {gpu_usage}"
                if payload['gpu']['temp'] is not None:
                    gpu_info += f" ({payload['gpu']['temp']}°C)"

            logger.info(f"[#{iteration:04d}] {cpu_info} | {ram_info} | {gpu_info}")

            if args.dry_run:
                print(json.dumps(payload, indent=2))
            else:
                if transmitter:
                    transmitter.send(payload)

            if args.once:
                logger.info("Completed single run iteration (--once). Exiting cleanly.")
                break

            # Calculate remaining sleep time to maintain steady interval
            elapsed = time.time() - start_loop
            sleep_time = max(0.0, interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("\nSender interrupted by user (SIGINT). Shutting down cleanly...")
    finally:
        if transmitter:
            transmitter.close()
        logger.info("PC sender shutdown complete.")


if __name__ == "__main__":
    main()
