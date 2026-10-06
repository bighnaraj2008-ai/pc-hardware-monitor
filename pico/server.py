"""
Raspberry Pi Pico W - Telemetry HTTP Receiver Server
Receives real-time PC hardware metrics and processes payloads.
"""

import gc
import time
# pyrefly: ignore [missing-import]
import network
# pyrefly: ignore [missing-import]
import machine

try:
    # pyrefly: ignore [missing-import]
    import ujson as json
except ImportError:
    import json

try:
    # pyrefly: ignore [missing-import]
    import usocket as socket
except ImportError:
    import socket

# Attempt to load local credentials and configurations
try:
    import config
    WIFI_SSID = getattr(config, "WIFI_SSID", "YOUR_WIFI_SSID")
    WIFI_PASSWORD = getattr(config, "WIFI_PASSWORD", "YOUR_WIFI_PASSWORD")
    SERVER_PORT = getattr(config, "SERVER_PORT", 80)
    CONNECTION_TIMEOUT_SECONDS = getattr(config, "CONNECTION_TIMEOUT_SECONDS", 15)
    ENABLE_LED_INDICATOR = getattr(config, "ENABLE_LED_INDICATOR", True)
    ENABLE_SERIAL_LOGGING = getattr(config, "ENABLE_SERIAL_LOGGING", True)
    STATIC_IP_CONFIG = getattr(config, "STATIC_IP_CONFIG", None)
except ImportError:
    WIFI_SSID = "YOUR_WIFI_SSID"
    WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
    SERVER_PORT = 80
    CONNECTION_TIMEOUT_SECONDS = 15
    ENABLE_LED_INDICATOR = True
    ENABLE_SERIAL_LOGGING = True
    STATIC_IP_CONFIG = None

# Hardware LED setup
try:
    led = machine.Pin("LED", machine.Pin.OUT)
except Exception:
    try:
        led = machine.Pin(25, machine.Pin.OUT)
    except Exception:
        led = None

# Telemetry session state
packet_counter = 0
boot_start_time = time.time()


def render_progress_bar(percent: float, width: int = 10) -> str:
    """Create a compact ASCII progress bar for console telemetry visualization."""
    if percent is None:
        return "[" + " " * width + "]"
    clamped = max(0.0, min(100.0, float(percent)))
    filled = int(round((clamped / 100.0) * width))
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}]"


def display_telemetry_dashboard(payload: dict, client_ip: str):
    """
    Renders a formatted real-time telemetry dashboard in the Pico REPL console.
    """
    global packet_counter
    packet_counter += 1

    if not ENABLE_SERIAL_LOGGING:
        return

    hostname = payload.get("hostname", "PC")
    cpu = payload.get("cpu", {})
    ram = payload.get("ram", {})
    gpu = payload.get("gpu", {})

    cpu_usage = cpu.get("usage", 0.0)
    cpu_temp = cpu.get("temp")
    cpu_freq = cpu.get("freq")
    cpu_cores = cpu.get("cores", 1)

    ram_usage = ram.get("usage", 0.0)
    ram_used = ram.get("used_gb", 0.0)
    ram_total = ram.get("total_gb", 0.0)

    gpu_detected = gpu.get("detected", False)
    gpu_name = gpu.get("name", "N/A")
    gpu_usage = gpu.get("usage")
    gpu_temp = gpu.get("temp")
    gpu_mem_used = gpu.get("mem_used_mb")
    gpu_mem_total = gpu.get("mem_total_mb")

    temp_str = f"{cpu_temp}°C" if cpu_temp is not None else "--.-°C"
    freq_str = f"{cpu_freq}MHz" if cpu_freq is not None else "---MHz"

    print("\n" + "=" * 56)
    print(f" [#{packet_counter:05d}] TELEMETRY | Host: {hostname} ({client_ip})")
    print("-" * 56)
    print(f" CPU: {render_progress_bar(cpu_usage)} {cpu_usage:5.1f}% | {temp_str} | {freq_str} ({cpu_cores}C)")
    print(f" RAM: {render_progress_bar(ram_usage)} {ram_usage:5.1f}% | {ram_used:.1f} / {ram_total:.1f} GB")

    if gpu_detected:
        gpu_u_str = f"{gpu_usage:5.1f}%" if gpu_usage is not None else "  N/A "
        gpu_t_str = f"{gpu_temp}°C" if gpu_temp is not None else "--.-°C"
        gpu_bar = render_progress_bar(gpu_usage if gpu_usage is not None else 0.0)
        gpu_mem_str = f"{gpu_mem_used:.0f}/{gpu_mem_total:.0f}MB" if gpu_mem_used and gpu_mem_total else ""
        print(f" GPU: {gpu_bar} {gpu_u_str} | {gpu_t_str} | {gpu_name[:16]} {gpu_mem_str}")
    else:
        print(" GPU: [----------]   N/A  | Not Detected")

    uptime_s = time.time() - boot_start_time
    print(f" PICO: Heap Free: {gc.mem_free()} B | Server Uptime: {uptime_s}s")
    print("=" * 56)


def indicate_reception_success():
    """Toggle onboard LED to provide visual pulse feedback upon receiving valid telemetry."""
    if not led or not ENABLE_LED_INDICATOR:
        return
    current_state = led.value()
    led.value(0 if current_state else 1)
    time.sleep_ms(60)
    led.value(current_state)


def indicate_error():
    """Flash onboard LED rapidly to signal a rejected request or parsing failure."""
    if not led or not ENABLE_LED_INDICATOR:
        return
    for _ in range(3):
        led.value(0)
        time.sleep_ms(40)
        led.value(1)
        time.sleep_ms(40)


def connect_wifi(
    ssid: str = WIFI_SSID,
    password: str = WIFI_PASSWORD,
    timeout_s: int = CONNECTION_TIMEOUT_SECONDS
) -> str:
    """
    Connect the Raspberry Pi Pico W to local Wi-Fi network.
    Returns the assigned local IP address string upon successful connection.
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    try:
        wlan.config(pm=0xa11140)
    except Exception:
        pass

    if STATIC_IP_CONFIG:
        try:
            wlan.ifconfig(STATIC_IP_CONFIG)
            print(f"Applied static network configuration: {STATIC_IP_CONFIG}")
        except Exception as e:
            print(f"Could not set static IP configuration: {e}")

    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print(f"Already connected to Wi-Fi. IP: {ip}")
        if led and ENABLE_LED_INDICATOR:
            led.value(1)
        return ip

    print(f"Connecting to Wi-Fi SSID '{ssid}'...")
    wlan.connect(ssid, password)

    start_time = time.time()
    while not wlan.isconnected():
        if led and ENABLE_LED_INDICATOR:
            led.toggle()
        time.sleep_ms(300)

        elapsed = time.time() - start_time
        if elapsed > timeout_s:
            if led and ENABLE_LED_INDICATOR:
                led.value(0)
            status_code = wlan.status()
            raise RuntimeError(f"Wi-Fi connection timed out after {timeout_s}s (WLAN status code: {status_code})")

    if led and ENABLE_LED_INDICATOR:
        led.value(1)

    ip_info = wlan.ifconfig()
    print("----------------------------------------")
    print("Wi-Fi Connected Successfully!")
    print(f"IP Address:   {ip_info[0]}")
    print(f"Subnet Mask:  {ip_info[1]}")
    print(f"Gateway:      {ip_info[2]}")
    print(f"DNS Server:   {ip_info[3]}")
    print("----------------------------------------")

    return ip_info[0]


def parse_http_request(client_sock):
    """
    Reads and parses incoming HTTP stream into method, path, headers, and decoded JSON body.
    """
    request_data = b""
    while b"\r\n\r\n" not in request_data:
        chunk = client_sock.recv(512)
        if not chunk:
            break
        request_data += chunk

    if not request_data:
        return None, None, {}, None

    header_bytes, body_bytes = request_data.split(b"\r\n\r\n", 1)
    header_lines = header_bytes.decode("utf-8", "ignore").split("\r\n")

    if not header_lines or not header_lines[0]:
        return None, None, {}, None

    request_tokens = header_lines[0].split(" ")
    if len(request_tokens) < 2:
        return None, None, {}, None

    method = request_tokens[0].upper()
    path = request_tokens[1]

    headers = {}
    for line in header_lines[1:]:
        if ":" in line:
            key, val = line.split(":", 1)
            headers[key.strip().lower()] = val.strip()

    content_length = int(headers.get("content-length", 0))
    while len(body_bytes) < content_length:
        needed = content_length - len(body_bytes)
        chunk = client_sock.recv(min(needed, 512))
        if not chunk:
            break
        body_bytes += chunk

    json_payload = None
    if body_bytes:
        try:
            json_payload = json.loads(body_bytes.decode("utf-8", "ignore"))
        except Exception as e:
            print(f"Failed to decode JSON payload: {e}")

    return method, path, headers, json_payload


def build_response(status_code: int, status_text: str, data: dict) -> bytes:
    """Construct an HTTP response packet with JSON body."""
    body_str = json.dumps(data)
    body_bytes = body_str.encode("utf-8")
    header_str = (
        f"HTTP/1.1 {status_code} {status_text}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    return header_str.encode("utf-8") + body_bytes


def start_server(host: str = "0.0.0.0", port: int = SERVER_PORT):
    """
    Initializes lightweight socket server and listens for incoming HTTP connections.
    """
    addr = (host, port)
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_sock.bind(addr)
        server_sock.listen(2)
        print(f"Socket server listening on {host}:{port}...")

        while True:
            gc.collect()

            client_sock = None
            try:
                client_sock, client_addr = server_sock.accept()
                client_sock.settimeout(5.0)

                method, path, headers, payload = parse_http_request(client_sock)
                if not method:
                    continue

                if method == "POST" and path == "/api/metrics":
                    if payload and isinstance(payload, dict):
                        # Visual LED pulse feedback indicating valid packet reception
                        indicate_reception_success()

                        # Output formatted telemetry dashboard to REPL console
                        display_telemetry_dashboard(payload, client_addr[0])

                        response = build_response(200, "OK", {
                            "status": "success",
                            "message": "Telemetry metrics received",
                            "timestamp": time.time(),
                            "packets_processed": packet_counter
                        })
                    else:
                        indicate_error()
                        response = build_response(400, "Bad Request", {
                            "status": "error",
                            "message": "Invalid or missing JSON payload"
                        })
                elif method == "GET" and path in ("/", "/health"):
                    response = build_response(200, "OK", {
                        "status": "online",
                        "free_memory_bytes": gc.mem_free(),
                        "time": time.time(),
                        "packets_processed": packet_counter
                    })
                else:
                    response = build_response(404, "Not Found", {
                        "status": "error",
                        "message": f"Resource {path} not found"
                    })

                client_sock.sendall(response)

            except Exception as e:
                print(f"Error servicing request: {e}")
                indicate_error()
            finally:
                if client_sock:
                    try:
                        client_sock.close()
                    except Exception:
                        pass

    except KeyboardInterrupt:
        print("\nServer stopped by user.")
    finally:
        server_sock.close()
        print("Socket server closed.")


if __name__ == "__main__":
    try:
        assigned_ip = connect_wifi()
        start_server(host="0.0.0.0", port=SERVER_PORT)
    except Exception as err:
        print(f"Fatal server error: {err}")
