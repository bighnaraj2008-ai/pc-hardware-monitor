"""
Raspberry Pi Pico W - Telemetry HTTP Receiver Server
Receives real-time PC hardware metrics and processes payloads.
"""

import gc
import time
import network
import machine

try:
    import ujson as json
except ImportError:
    import json

try:
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

            except Exception as e:
                print(f"Error servicing request: {e}")
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
