# Troubleshooting Guide & Operational Notes 🛠️

This document addresses common edge cases, operating system quirks, network configurations, and MicroPython nuances encountered when running the PC Hardware Monitor.

---

## 1. Network & Wi-Fi Connectivity

### Issue: Pico W Fails to Connect to Wi-Fi (`Wi-Fi connection timed out`)
- **2.4 GHz Band Requirement**: The Infineon CYW43439 chip on the Raspberry Pi Pico W **only supports 2.4 GHz Wi-Fi networks (802.11 b/g/n)**. If your home router broadcasts dual-band under a unified SSID and forces 5 GHz band steering, configure a dedicated 2.4 GHz SSID or guest network.
- **WPA3 Compatibility**: The Pico W CYW43 driver works most reliably on **WPA2-PSK (AES)**. If your router uses strict WPA3-Personal, try switching the security mode to WPA2/WPA3 Mixed mode.
- **SSID & Password Special Characters**: Ensure your Wi-Fi SSID and password in [`pico/config.py`](file:///pico/config.py) do not contain trailing whitespace or unescaped characters.

### Issue: PC Sender Cannot Reach Pico W (`ConnectionRefusedError` or `ConnectTimeout`)
- **AP / Client Isolation**: Many guest Wi-Fi networks enable "Client Isolation" (or "Station Isolation"), which forbids Wi-Fi clients from communicating with each other. Ensure both your PC and Pico W are on the primary LAN or a non-isolated subnet.
- **Windows Firewall**: Port 80 outbound is generally permitted, but third-party antivirus suites (e.g., Norton, Bitdefender) may flag non-standard Python HTTP requests to local IPs. Add a temporary exception for Python if needed.
- **Testing Direct Connectivity via PowerShell**:
  Test whether your PC can reach the Pico W server directly from terminal:
  ```powershell
  # Test ICMP Ping
  Test-Connection -TargetName 192.168.1.105 -Count 3

  # Test HTTP Health Endpoint
  Invoke-RestMethod -Uri "http://192.168.1.105:80/health" -Method Get
  ```

---

## 2. PC Telemetry Sensors & Windows Permissions

### Issue: CPU Temperature Returns `null` or Does Not Update
- **Windows WMI Permissions**: Querying `root\wmi` (`MSAcpi_ThermalZoneTemperature`) in Windows typically requires Administrator privileges. Run PowerShell / Windows Terminal as **Administrator**:
  ```powershell
  Start-Process powershell -Verb runAs
  ```
- **Hardware Sensor Driver Limitation**: Some modern desktop motherboards (AMD AM4/AM5, Intel LGA1700) do not populate standard ACPI thermal zones.
  - **Recommended Solution**: Run [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) in the background with **Options -> WMI Provider Enabled**. The sender script will automatically detect and query temperatures through the LibreHardwareMonitor WMI namespace without requiring custom drivers.

### Issue: GPU Metrics Show `detected: false`
- **NVIDIA GPU Detection**: The script inspects `PATH` for `nvidia-smi.exe`. On Windows, `nvidia-smi` is normally located at:
  ```text
  C:\Windows\System32\nvidia-smi.exe
  # Or:
  C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe
  ```
  If `nvidia-smi` is not in your system `PATH`, add its directory to your Windows System Environment Variables.
- **Integrated Graphics (Intel UHD / AMD Radeon Graphics)**: If you do not have a dedicated NVIDIA GPU, the script falls back to querying `Win32_VideoController` via WMI. Utilization percentages are not exposed by standard video controller drivers without third-party tools like LibreHardwareMonitor.

---

## 3. MicroPython & Raspberry Pi Pico W Performance

### Issue: Memory Leak or `MemoryError: out of memory` (`ENOMEM`)
- The Pico RP2040 microcontroller has 264 KB of SRAM. While small, this is more than sufficient for high-speed telemetry if memory fragmentation is minimized.
- In [`pico/server.py`](file:///pico/server.py):
  - `gc.collect()` is explicitly called at the top of each request loop to reclaim memory immediately after processing each packet.
  - TCP client sockets are wrapped in `try...finally` blocks to guarantee `client_sock.close()` is invoked even on malformed or aborted connections.
  - Sockets use a 5.0-second timeout to prevent zombie connections from consuming file descriptors.

### Issue: Packet Dropouts / High Latency
- The CYW43439 chip has an aggressive default power-management mode that puts the radio to sleep between beacon intervals.
- The server code disables CYW43 power management upon boot via:
  ```python
  wlan.config(pm=0xa11140)
  ```
  This reduces HTTP response latency from ~120ms down to ~5-15ms.

---

## 4. Verification Checklist

- [x] Initialized project directory structure with `pc/` and `pico/`
- [x] Added `README.md` with architecture, setup, pinouts, and API specs
- [x] Added `LICENSE` (MIT) and comprehensive `.gitignore`
- [x] Added `requirements.txt` with `psutil`, `requests`, `wmi`, `pywin32`
- [x] Created `pc/config.template.json` with IP and polling placeholders
- [x] Implemented core CPU/RAM sensors in `pc/sender.py`
- [x] Added GPU metrics parsing logic with `nvidia-smi` and WMI
- [x] Implemented compact JSON payload formatting
- [x] Added HTTP POST transmission with robust error handling
- [x] Added CLI arguments (`--ip`, `--interval`, `--dry-run`, `--once`, `--verbose`)
- [x] Created `pico/boot.py` for hardware POST and memory initialization
- [x] Created `pico/config.py` for Wi-Fi and network configuration
- [x] Implemented resilient Wi-Fi connection handler in `pico/server.py`
- [x] Implemented lightweight TCP socket server skeleton
- [x] Added HTTP POST parser and JSON extractor
- [x] Added onboard LED pulse feedback on telemetry reception
- [x] Added ASCII progress bar dashboard logging to Pico REPL console
- [x] Expanded documentation with wiring guides and API schemas
- [x] Added troubleshooting manual and completed repository verification
