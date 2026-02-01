#!/usr/bin/env python3
"""
DualSense Output Demo - Demonstrate all writable features

Features demonstrated:
- Lightbar RGB colors
- Player indicator LEDs
- Haptic feedback (rumble)
- Adaptive trigger effects
- Mute LED

Run with: sudo python3 demo_write.py
"""

import sys
import time
from dualsense import DualSense, PlayerLED, TriggerMode


def demo_lightbar(ds: DualSense):
    """Cycle through colors"""
    print("\n▶ Lightbar RGB Demo")
    print("  Cycling through colors...")

    colors = [
        (255, 0, 0, "Red"),
        (255, 128, 0, "Orange"),
        (255, 255, 0, "Yellow"),
        (0, 255, 0, "Green"),
        (0, 255, 255, "Cyan"),
        (0, 0, 255, "Blue"),
        (128, 0, 255, "Purple"),
        (255, 0, 255, "Magenta"),
        (255, 255, 255, "White"),
    ]

    for r, g, b, name in colors:
        print(f"    {name}...")
        ds.set_lightbar(r, g, b)
        ds.send()
        time.sleep(0.4)

    # Fade out
    for i in range(255, -1, -15):
        ds.set_lightbar(i, i, i)
        ds.send()
        time.sleep(0.02)

    print("  ✓ Done")


def demo_player_leds(ds: DualSense):
    """Demonstrate player indicator LEDs"""
    print("\n▶ Player LED Demo")

    patterns = [
        (PlayerLED.LEFT, "Left"),
        (PlayerLED.MIDDLE_LEFT, "Middle-Left"),
        (PlayerLED.MIDDLE, "Middle"),
        (PlayerLED.MIDDLE_RIGHT, "Middle-Right"),
        (PlayerLED.RIGHT, "Right"),
        (PlayerLED.PLAYER_1, "Player 1 pattern"),
        (PlayerLED.PLAYER_2, "Player 2 pattern"),
        (PlayerLED.PLAYER_3, "Player 3 pattern"),
        (PlayerLED.PLAYER_4, "Player 4 pattern"),
        (PlayerLED.ALL, "All LEDs"),
    ]

    for led, name in patterns:
        print(f"    {name}...")
        ds.set_player_leds(led)
        ds.send()
        time.sleep(0.4)

    ds.set_player_leds(PlayerLED.OFF)
    ds.send()
    print("  ✓ Done")


def demo_haptic(ds: DualSense):
    """Demonstrate haptic motors"""
    print("\n▶ Haptic Feedback Demo")

    print("    Left motor ramp up...")
    for i in range(0, 256, 32):
        ds.set_haptic(i, 0)
        ds.send()
        time.sleep(0.1)

    ds.set_haptic(0, 0)
    ds.send()
    time.sleep(0.2)

    print("    Right motor ramp up...")
    for i in range(0, 256, 32):
        ds.set_haptic(0, i)
        ds.send()
        time.sleep(0.1)

    ds.set_haptic(0, 0)
    ds.send()
    time.sleep(0.2)

    print("    Both motors pulse...")
    for _ in range(3):
        ds.set_haptic(200, 200)
        ds.send()
        time.sleep(0.15)
        ds.set_haptic(0, 0)
        ds.send()
        time.sleep(0.15)

    print("  ✓ Done")


def demo_triggers(ds: DualSense):
    """Demonstrate adaptive triggers"""
    print("\n▶ Adaptive Trigger Demo")

    print("    L2: Rigid resistance (pull to feel)")
    ds.set_trigger_effect('L2', TriggerMode.RIGID, start=50, force=200)
    ds.send()
    time.sleep(2)

    print("    R2: Rigid resistance (pull to feel)")
    ds.set_trigger_effect('R2', TriggerMode.RIGID, start=50, force=200)
    ds.send()
    time.sleep(2)

    print("    Both: Clearing effects...")
    ds.clear_trigger_effect('both')
    ds.send()
    time.sleep(0.5)

    print("  ✓ Done")


def demo_mute_led(ds: DualSense):
    """Demonstrate mute button LED"""
    print("\n▶ Mute LED Demo")

    print("    Blinking mute LED...")
    for _ in range(5):
        ds.set_mute_led(True)
        ds.send()
        time.sleep(0.2)
        ds.set_mute_led(False)
        ds.send()
        time.sleep(0.2)

    print("  ✓ Done")


def demo_interactive(ds: DualSense):
    """Interactive demo - respond to button presses"""
    print("\n▶ Interactive Demo")
    print("  Press buttons to trigger effects:")
    print("    - Cross (X): Blue flash")
    print("    - Circle: Red flash")
    print("    - Square: Purple flash")
    print("    - Triangle: Green flash")
    print("    - L1/R1: Rumble that side")
    print("    - L2/R2: Feel adaptive trigger")
    print("    - Touchpad: Rainbow cycle")
    print("    - PS button: Exit")

    # Set up trigger effects
    ds.set_trigger_effect('L2', TriggerMode.RIGID, start=80, force=150)
    ds.set_trigger_effect('R2', TriggerMode.RIGID, start=80, force=150)
    ds.set_player_leds(PlayerLED.PLAYER_1)
    ds.send()

    try:
        while True:
            state = ds.read()
            if not state:
                time.sleep(0.01)
                continue

            # Exit on PS button
            if state.ps:
                print("    PS button pressed - exiting")
                break

            # Face buttons -> lightbar
            if state.cross:
                ds.set_lightbar(0, 0, 255)
            elif state.circle:
                ds.set_lightbar(255, 0, 0)
            elif state.square:
                ds.set_lightbar(128, 0, 255)
            elif state.triangle:
                ds.set_lightbar(0, 255, 0)
            elif state.touchpad_click:
                # Rainbow based on time
                import colorsys
                hue = (time.time() * 2) % 1.0
                r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                ds.set_lightbar(int(r * 255), int(g * 255), int(b * 255))
            else:
                ds.set_lightbar(0, 0, 0)

            # Shoulders -> haptic
            left_haptic = 200 if state.l1 else 0
            right_haptic = 200 if state.r1 else 0
            ds.set_haptic(left_haptic, right_haptic)

            ds.send()
            time.sleep(0.016)

    except KeyboardInterrupt:
        pass

    # Clean up
    ds.set_lightbar(0, 0, 0)
    ds.set_haptic(0, 0)
    ds.clear_trigger_effect('both')
    ds.set_player_leds(PlayerLED.OFF)
    ds.send()
    print("  ✓ Done")


def main():
    print("═══════════════════════════════════════════════════════════════")
    print("            DUALSENSE CONTROLLER - OUTPUT DEMO")
    print("═══════════════════════════════════════════════════════════════")
    print("\nConnecting to controller...")

    ds = DualSense()
    if not ds.open():
        print("\nFailed to connect. Try:")
        print("  1. Run with sudo")
        print("  2. Set up udev rules (see setup_udev.sh)")
        sys.exit(1)

    print("Connected!")

    try:
        demo_lightbar(ds)
        demo_player_leds(ds)
        demo_haptic(ds)
        demo_triggers(ds)
        demo_mute_led(ds)
        demo_interactive(ds)

    except KeyboardInterrupt:
        print("\n\nInterrupted!")
    finally:
        # Reset everything
        ds.set_lightbar(0, 0, 0)
        ds.set_haptic(0, 0)
        ds.clear_trigger_effect('both')
        ds.set_player_leds(PlayerLED.OFF)
        ds.set_mute_led(False)
        ds.send()
        ds.close()

    print("\n═══════════════════════════════════════════════════════════════")
    print("                        DEMO COMPLETE")
    print("═══════════════════════════════════════════════════════════════")


if __name__ == '__main__':
    main()
