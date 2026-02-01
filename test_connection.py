#!/usr/bin/env python3
"""Quick connection test - verifies controller communication works"""

from dualsense import DualSense, list_devices
import time

print("DualSense Connection Test")
print("=" * 40)

print("\n1. Scanning for devices...")
list_devices()

print("\n2. Attempting to connect...")
ds = DualSense()
if not ds.open():
    print("\n❌ Failed to open controller.")
    print("   Try: sudo python3 test_connection.py")
    print("   Or run: sudo ./setup_udev.sh")
    exit(1)

print("✓ Connected!")

print("\n3. Reading input (move the sticks)...")
for i in range(10):
    state = ds.read_blocking(timeout_ms=200)
    if state:
        print(f"   L:({state.left_stick_x:3d},{state.left_stick_y:3d}) "
              f"R:({state.right_stick_x:3d},{state.right_stick_y:3d}) "
              f"L2:{state.l2_trigger:3d} R2:{state.r2_trigger:3d}")
    time.sleep(0.1)

print("\n4. Testing output (watch the lightbar)...")
ds.set_lightbar(0, 255, 0)  # Green
ds.set_player_leds(0x04)     # Middle LED
ds.send()
time.sleep(0.5)

ds.set_lightbar(255, 0, 0)  # Red
ds.send()
time.sleep(0.5)

ds.set_lightbar(0, 0, 255)  # Blue
ds.send()
time.sleep(0.5)

# Cleanup
ds.set_lightbar(0, 0, 0)
ds.set_player_leds(0)
ds.send()
ds.close()

print("\n✓ All tests passed!")
print("  Controller is working. Try demo_read.py or demo_write.py")
