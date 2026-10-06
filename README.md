# PC Hardware Monitor 🖥️⚡📡

A high-performance, networked PC telemetry monitoring system. Real-time CPU, RAM, and GPU metrics are harvested from a host PC (Windows/Linux) and streamed over local Wi-Fi to a Raspberry Pi Pico W microcontroller, featuring visual LED activity pulses and a formatted REPL dashboard.

---

## Architecture & Data Flow

```
+-------------------------------------------------------------------+
|                            HOST PC                                |
|  [HardwareReader]                                                 |
|    - CPU Load / Temp / Frequency  (psutil + WMI)                  |
|    - RAM Used / Free / Swap       (psutil)                        |
|    - GPU Utilization / VRAM / Temp (nvidia-smi / WMI)             |
|                                                                   |
|  [JSON Serializer]  ==> Compact Telemetry Payload                 |
|  [HttpTransmitter]  ==> HTTP POST /api/metrics                    |
+---------------------------------+---------------------------------+
                                  |
                           Local Wi-Fi (HTTP)
                                  |
                                  v
+-------------------------------------------------------------------+
|                     RASPBERRY PI PICO W                           |
|  [boot.py]       -> MicroPython Boot, GC, Hardware Self-Test      |
|  [server.py]     -> CYW43439 Wi-Fi Station & Low-Power Disable    |
|                  -> Lightweight TCP/HTTP Socket Server (Port 80)  |
|                  -> JSON Stream Parser & Validator                |
|                  -> Visual Status Feedback (CYW43 Onboard LED)    |
|                  -> Live REPL Metrics Dashboard & Memory GC       |
+-------------------------------------------------------------------+
```

---

## Features

- **Low-Latency Polling**: Configurable polling intervals (default: 2.0s).
- **Comprehensive Hardware Telemetry**:
  - **CPU**: Utilization %, core counts (logical/physical), clock frequency (MHz), package temperature (°C).
  - **RAM**: Memory utilization %, used GB, total GB, free GB, swap file statistics.
  - **GPU**: NVIDIA GPU monitoring (`nvidia-smi`) with Windows WMI / OpenHardwareMonitor fallbacks (GPU name, load %, VRAM usage, temperature).
- **Resilient Network Handling**:
  - Auto-reconnect handling and CYW43 power-save disabling to prevent dropped packets.
  - Granular timeout and connection retry logic on both sender and receiver.
- **Hardware Status Feedback**:
  - Power-on blink sequence on boot.
  - Real-time pulse toggle on incoming telemetry packets.
  - Rapid alert flashes on transmission or payload errors.
- **Interactive REPL Telemetry Dashboard**:
  - Live ASCII visual progress bars for CPU, RAM, and GPU.
  - MicroPython heap memory monitoring and automatic garbage collection.

---

## Hardware Requirements & Wiring Guide

### Core Components
1. **Raspberry Pi Pico W** (RP2040 microcontroller with CYW43439 Wi-Fi chip).
2. **Micro-USB Cable** for power and serial REPL console monitoring.
3. Host Windows or Linux PC connected to the same local Wi-Fi / LAN network.

### Onboard Status Indicator
- **Raspberry Pi Pico W**: Onboard LED is controlled internally via the CYW43 wireless chip (`machine.Pin("LED")`).
- **Standard Pico (Fallback)**: Pin `GP25`.

### Optional I2C OLED Display Wiring (SSD1306 128x64 / 128x32)
If you wish to attach an external I2C OLED display directly to the Pico W:

| OLED Display Pin | Raspberry Pi Pico W Pin | Pin Physical Number | Notes |
| :--- | :--- | :--- | :--- |
| **VCC** | **3V3 (OUT)** | Pin 36 | 3.3V DC Power |
| **GND** | **GND** | Pin 38 | Ground |
| **SDA** | **GP0** (or GP4) | Pin 1 (or Pin 6) | I2C0 SDA / I2C1 SDA |
| **SCL** | **GP1** (or GP5) | Pin 2 (or Pin 7) | I2C0 SCL / I2C1 SCL |

---

## Software Installation & Setup

### 1. Raspberry Pi Pico W Setup

1. **Install MicroPython Firmware**:
   - Download the latest Pico W MicroPython UF2 firmware from [micropython.org](https://micropython.org/download/rp2-pico-w/).
   - Hold the **BOOTSEL** button on the Pico W while connecting it via USB.
   - Drag and drop the `.uf2` file into the `RPI-RP2` mass storage drive.

2. **Configure Wi-Fi Credentials**:
   - Open [`pico/config.py`](file:///pico/config.py) and enter your local Wi-Fi details:
     ```python
     WIFI_SSID = "MyHomeNetwork"
     WIFI_PASSWORD = "MySecretPassword123"
     SERVER_PORT = 80
     ```

3. **Deploy Files to Pico W**:
   - Using **Thonny IDE**, **mpremote**, or **rshell**, copy the following files to the root directory `/` of your Pico W:
     - [`pico/boot.py`](file:///pico/boot.py) -> `/boot.py`
     - [`pico/config.py`](file:///pico/config.py) -> `/config.py`
     - [`pico/server.py`](file:///pico/server.py) -> `/main.py` *(or run directly from Thonny)*

4. **Verify Pico Server Startup**:
   - When restarted, the Pico W blinks twice, connects to Wi-Fi, and outputs its assigned IP address in the console:
     ```text
     Wi-Fi Connected Successfully!
     IP Address:   192.168.1.105
     Socket server listening on 0.0.0.0:80...
     ```

---

### 2. PC Sender Setup

1. **Prerequisites**: Python 3.8+ installed on your PC.

2. **Clone & Install Dependencies**:
   ```powershell
   git clone <repo-url> pc-hardware-monitor
   cd pc-hardware-monitor

   # Create and activate virtual environment
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # Install required telemetry packages
   pip install -r requirements.txt
   ```

3. **Configure Connection**:
   - Copy the template file:
     ```powershell
     copy pc\config.template.json pc\config.json
     ```
   - Edit `pc/config.json` with your Pico W's IP address:
     ```json
     {
       "pico_ip": "192.168.1.105",
       "pico_port": 80,
       "polling_interval_seconds": 2.0,
       "request_timeout_seconds": 3.0
     }
     ```

---

## Usage Examples

### Running the PC Sender

#### Standard Mode (continuous stream using config file)
```powershell
python pc/sender.py
```

#### Override IP & Polling Interval via CLI
```powershell
python pc/sender.py --ip 192.168.1.105 --interval 1.0
```

#### Dry-Run Mode (inspect metrics in terminal without network transmission)
```powershell
python pc/sender.py --dry-run
```

#### Single Transmission & Exit
```powershell
python pc/sender.py --ip 192.168.1.105 --once
```

#### Verbose Debug Logging
```powershell
python pc/sender.py --verbose
```

---

## API Specification

### `POST /api/metrics`
Transmits real-time PC telemetry to the Pico W.

#### Request Headers:
```http
POST /api/metrics HTTP/1.1
Content-Type: application/json
Content-Length: 320
```

#### Request Payload Schema:
```json
{
  "timestamp": 1791382400,
  "hostname": "DESKTOP-RIG",
  "uptime": 14200,
  "cpu": {
    "usage": 24.5,
    "temp": 48.0,
    "freq": 4200.0,
    "cores": 16
  },
  "ram": {
    "usage": 45.2,
    "used_gb": 14.46,
    "total_gb": 32.0,
    "free_gb": 17.54
  },
  "gpu": {
    "detected": true,
    "name": "NVIDIA GeForce RTX 4070",
    "usage": 18.0,
    "temp": 44.0,
    "mem_usage": 26.5,
    "mem_used_mb": 3250.0,
    "mem_total_mb": 12288.0
  }
}
```

#### Response (`200 OK`):
```json
{
  "status": "success",
  "message": "Telemetry metrics received",
  "timestamp": 1791382400,
  "packets_processed": 42
}
```

---

### `GET /health`
Verifies network connectivity and checks Pico W internal heap memory.

#### Response (`200 OK`):
```json
{
  "status": "online",
  "free_memory_bytes": 184512,
  "time": 1791382400,
  "packets_processed": 42
}
```

---

## Troubleshooting & Verification

For solutions to common issues including 2.4GHz Wi-Fi requirements, Windows WMI sensor permissions, GPU detection fallbacks, and MicroPython memory optimization, refer to the detailed [Troubleshooting Guide](file:///TROUBLESHOOTING.md).

