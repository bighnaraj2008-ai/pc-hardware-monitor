# Raspberry Pi Pico W - Boot Initialization Script
# Runs automatically upon microcontroller power-on or hard reset.

import gc
import time
# pyrefly: ignore [missing-import]
import machine

# Enable automatic garbage collection and perform initial sweep
gc.enable()
gc.collect()

def get_status_led():
    """Resolve onboard LED pin across Raspberry Pi Pico W and standard Pico."""
    try:
        # Raspberry Pi Pico W CYW43 onboard LED
        return machine.Pin("LED", machine.Pin.OUT)
    except Exception:
        try:
            # Standard Raspberry Pi Pico RP2040 GPIO 25
            return machine.Pin(25, machine.Pin.OUT)
        except Exception:
            return None

led = get_status_led()

def boot_blink_sequence(count=2, delay_ms=80):
    """Signal power-on hardware initialization via rapid LED pulses."""
    if not led:
        return
    for _ in range(count):
        led.value(1)
        time.sleep_ms(delay_ms)
        led.value(0)
        time.sleep_ms(delay_ms)

# Perform boot sequence
print("========================================")
print("Raspberry Pi Pico W Hardware Initialized")
print(f"CPU Frequency: {machine.freq() / 1_000_000:.1f} MHz")
print(f"Free Heap Memory: {gc.mem_free()} bytes")
print("========================================")

boot_blink_sequence()
