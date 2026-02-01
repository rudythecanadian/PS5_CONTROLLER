#!/usr/bin/env python3
"""
DualSense Input Demo - Real-time display of all controller inputs

Run with: sudo python3 demo_read.py
"""

import sys
import time
from dualsense import DualSense, DPad


def clear_screen():
    print('\033[2J\033[H', end='')


def draw_stick(x: int, y: int, label: str) -> str:
    """Draw ASCII representation of stick position"""
    # Normalize to -1 to 1
    nx = (x - 128) / 128
    ny = (y - 128) / 128

    # 5x5 grid
    grid = [['·' for _ in range(5)] for _ in range(5)]

    # Map position to grid
    gx = int((nx + 1) * 2)
    gy = int((ny + 1) * 2)
    gx = max(0, min(4, gx))
    gy = max(0, min(4, gy))
    grid[gy][gx] = '●'

    lines = [f"  {label}: ({x:3d},{y:3d})"]
    for row in grid:
        lines.append("  " + " ".join(row))
    return "\n".join(lines)


def draw_dpad(dpad: DPad) -> str:
    """Draw ASCII d-pad"""
    u = '▲' if dpad in (DPad.UP, DPad.UP_LEFT, DPad.UP_RIGHT) else '△'
    d = '▼' if dpad in (DPad.DOWN, DPad.DOWN_LEFT, DPad.DOWN_RIGHT) else '▽'
    l = '◀' if dpad in (DPad.LEFT, DPad.UP_LEFT, DPad.DOWN_LEFT) else '◁'
    r = '▶' if dpad in (DPad.RIGHT, DPad.UP_RIGHT, DPad.DOWN_RIGHT) else '▷'
    return f"    {u}\n  {l}   {r}\n    {d}"


def format_button(pressed: bool, label: str) -> str:
    """Format button state"""
    return f"[{label}]" if pressed else f" {label} "


def main():
    print("DualSense Input Demo")
    print("=" * 50)
    print("Connecting to controller...")

    ds = DualSense()
    if not ds.open():
        print("\nFailed to connect. Try:")
        print("  1. Run with sudo")
        print("  2. Set up udev rules (see setup_udev.sh)")
        sys.exit(1)

    print("Connected! Press Ctrl+C to exit.\n")
    time.sleep(0.5)

    try:
        while True:
            state = ds.read()
            if not state:
                time.sleep(0.01)
                continue

            clear_screen()
            print("═══════════════════════════════════════════════════════════════")
            print("              DUALSENSE CONTROLLER - LIVE INPUT")
            print("═══════════════════════════════════════════════════════════════")

            # Row 1: Sticks side by side
            left_lines = draw_stick(state.left_stick_x, state.left_stick_y, "Left").split('\n')
            right_lines = draw_stick(state.right_stick_x, state.right_stick_y, "Right").split('\n')
            print("\n  ANALOG STICKS")
            for l, r in zip(left_lines, right_lines):
                print(f"{l:25s} {r}")

            # Row 2: Triggers
            print("\n  TRIGGERS")
            l2_bar = '█' * (state.l2_trigger // 16) + '░' * (16 - state.l2_trigger // 16)
            r2_bar = '█' * (state.r2_trigger // 16) + '░' * (16 - state.r2_trigger // 16)
            print(f"  L2: [{l2_bar}] {state.l2_trigger:3d}  {'(click)' if state.l2_button else ''}")
            print(f"  R2: [{r2_bar}] {state.r2_trigger:3d}  {'(click)' if state.r2_button else ''}")

            # Row 3: D-pad and face buttons
            print("\n  D-PAD                    FACE BUTTONS")
            dpad_lines = draw_dpad(state.dpad).split('\n')
            triangle = format_button(state.triangle, '△')
            square = format_button(state.square, '□')
            circle = format_button(state.circle, '○')
            cross = format_button(state.cross, '✕')
            face_lines = [
                f"        {triangle}",
                f"    {square}     {circle}",
                f"        {cross}"
            ]
            for dp, fb in zip(dpad_lines, face_lines):
                print(f"{dp:25s} {fb}")

            # Row 4: Shoulder buttons
            print("\n  SHOULDERS")
            l1 = format_button(state.l1, 'L1')
            r1 = format_button(state.r1, 'R1')
            l3 = format_button(state.l3, 'L3')
            r3 = format_button(state.r3, 'R3')
            print(f"  {l1}                           {r1}")
            print(f"  {l3} (stick)              {r3} (stick)")

            # Row 5: Center buttons
            print("\n  CENTER BUTTONS")
            create = format_button(state.create, 'CREATE')
            ps = format_button(state.ps, 'PS')
            options = format_button(state.options, 'OPTIONS')
            touchpad = format_button(state.touchpad_click, 'TOUCHPAD')
            mute = format_button(state.mute, 'MUTE')
            print(f"  {create}  {ps}  {options}")
            print(f"  {touchpad}  {mute}")

            # Row 6: Touchpad
            print("\n  TOUCHPAD")
            if state.touch1.active or state.touch2.active:
                if state.touch1.active:
                    print(f"    Point 1: ({state.touch1.x:4d}, {state.touch1.y:4d}) id={state.touch1.id}")
                if state.touch2.active:
                    print(f"    Point 2: ({state.touch2.x:4d}, {state.touch2.y:4d}) id={state.touch2.id}")
            else:
                print("    (no touch)")

            # Row 7: Motion sensors
            print("\n  MOTION SENSORS")
            print(f"    Gyro:  X={state.gyro_x:+6d}  Y={state.gyro_y:+6d}  Z={state.gyro_z:+6d}")
            print(f"    Accel: X={state.accel_x:+6d}  Y={state.accel_y:+6d}  Z={state.accel_z:+6d}")

            # Row 8: Status
            print("\n  STATUS")
            battery = '█' * state.battery_level + '░' * (10 - state.battery_level)
            charging = " ⚡" if state.battery_charging else ""
            print(f"    Battery: [{battery}]{charging}")
            print(f"    Headphones: {'Yes' if state.headphones else 'No'}  Mic: {'Yes' if state.microphone else 'No'}")

            print("\n═══════════════════════════════════════════════════════════════")
            print("  Press Ctrl+C to exit")

            time.sleep(0.016)  # ~60 Hz

    except KeyboardInterrupt:
        print("\n\nExiting...")
    finally:
        ds.close()


if __name__ == '__main__':
    main()
