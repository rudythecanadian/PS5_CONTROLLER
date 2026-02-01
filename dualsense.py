"""
DualSense PS5 Controller Library

Full read/write access to all DualSense features via USB HID:
- Buttons, sticks, triggers (analog)
- Touchpad (2 points with coordinates)
- Gyroscope and accelerometer
- Haptic feedback (left/right motors)
- Adaptive triggers (resistance profiles)
- Lightbar RGB LED
- Player indicator LEDs
- Mute button LED

Protocol reference: https://controllers.fandom.com/wiki/Sony_DualSense
"""

import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import Optional, Tuple
import hid


# Sony DualSense USB IDs
VENDOR_ID = 0x054C
PRODUCT_ID = 0x0CE6

# Report IDs
USB_INPUT_REPORT_ID = 0x01
USB_OUTPUT_REPORT_ID = 0x02


class Button(IntFlag):
    """DualSense button flags"""
    NONE = 0

    # Byte 8 - D-pad is in lower nibble as value 0-8
    SQUARE = 0x10
    CROSS = 0x20
    CIRCLE = 0x40
    TRIANGLE = 0x80

    # Byte 9
    L1 = 0x01
    R1 = 0x02
    L2 = 0x04
    R2 = 0x08
    CREATE = 0x10
    OPTIONS = 0x20
    L3 = 0x40
    R3 = 0x80

    # Byte 10
    PS = 0x01
    TOUCHPAD = 0x02
    MUTE = 0x04


class DPad(IntEnum):
    """D-pad direction values (lower nibble of byte 8)"""
    UP = 0
    UP_RIGHT = 1
    RIGHT = 2
    DOWN_RIGHT = 3
    DOWN = 4
    DOWN_LEFT = 5
    LEFT = 6
    UP_LEFT = 7
    NONE = 8


class TriggerMode(IntEnum):
    """Adaptive trigger effect modes"""
    OFF = 0x00
    RIGID = 0x01
    PULSE = 0x02
    RIGID_A = 0x01
    RIGID_B = 0x02
    RIGID_AB = 0x01 | 0x02
    PULSE_A = 0x01 | 0x20
    PULSE_B = 0x02 | 0x20
    PULSE_AB = 0x01 | 0x02 | 0x20
    CALIBRATION = 0xFC


class PlayerLED(IntFlag):
    """Player indicator LED positions"""
    OFF = 0x00
    LEFT = 0x01
    MIDDLE_LEFT = 0x02
    MIDDLE = 0x04
    MIDDLE_RIGHT = 0x08
    RIGHT = 0x10

    # Common patterns
    PLAYER_1 = MIDDLE
    PLAYER_2 = LEFT | RIGHT
    PLAYER_3 = LEFT | MIDDLE | RIGHT
    PLAYER_4 = LEFT | MIDDLE_LEFT | MIDDLE_RIGHT | RIGHT
    ALL = LEFT | MIDDLE_LEFT | MIDDLE | MIDDLE_RIGHT | RIGHT


class LightbarPulse(IntEnum):
    """Lightbar pulse options"""
    OFF = 0x00
    FADE_BLUE = 0x01
    FADE_OUT = 0x02


@dataclass
class TouchPoint:
    """Single touch point on the touchpad"""
    active: bool = False
    id: int = 0
    x: int = 0  # 0-1920
    y: int = 0  # 0-1080


@dataclass
class DualSenseState:
    """Complete controller input state"""
    # Sticks (0-255, center ~128)
    left_stick_x: int = 128
    left_stick_y: int = 128
    right_stick_x: int = 128
    right_stick_y: int = 128

    # Triggers (0-255)
    l2_trigger: int = 0
    r2_trigger: int = 0

    # D-pad
    dpad: DPad = DPad.NONE

    # Face buttons
    square: bool = False
    cross: bool = False
    circle: bool = False
    triangle: bool = False

    # Shoulder buttons
    l1: bool = False
    r1: bool = False
    l2_button: bool = False  # Digital click
    r2_button: bool = False  # Digital click

    # Stick clicks
    l3: bool = False
    r3: bool = False

    # Center buttons
    create: bool = False
    options: bool = False
    ps: bool = False
    touchpad_click: bool = False
    mute: bool = False

    # Touchpad (2 touch points)
    touch1: TouchPoint = field(default_factory=TouchPoint)
    touch2: TouchPoint = field(default_factory=TouchPoint)

    # Motion sensors
    gyro_x: int = 0  # Pitch rate
    gyro_y: int = 0  # Yaw rate
    gyro_z: int = 0  # Roll rate
    accel_x: int = 0
    accel_y: int = 0
    accel_z: int = 0

    # Misc
    timestamp: int = 0
    battery_level: int = 0
    battery_charging: bool = False
    headphones: bool = False
    microphone: bool = False


class DualSense:
    """
    DualSense PS5 Controller interface

    Usage:
        ds = DualSense()
        ds.open()

        # Read inputs
        state = ds.read()
        print(f"Left stick: {state.left_stick_x}, {state.left_stick_y}")

        # Set outputs
        ds.set_lightbar(255, 0, 0)  # Red
        ds.set_player_leds(PlayerLED.PLAYER_1)
        ds.set_haptic(100, 100)
        ds.send()

        ds.close()
    """

    def __init__(self):
        self._device: Optional[hid.device] = None
        self._state = DualSenseState()

        # Output state (sent with send())
        self._lightbar_r = 0
        self._lightbar_g = 0
        self._lightbar_b = 0
        self._player_leds = PlayerLED.OFF
        self._haptic_left = 0
        self._haptic_right = 0
        self._l2_trigger_mode = TriggerMode.OFF
        self._l2_trigger_params = bytes(10)
        self._r2_trigger_mode = TriggerMode.OFF
        self._r2_trigger_params = bytes(10)
        self._mute_led = False
        self._lightbar_pulse = LightbarPulse.OFF

    def open(self) -> bool:
        """Open connection to DualSense controller"""
        try:
            self._device = hid.device()
            self._device.open(VENDOR_ID, PRODUCT_ID)
            self._device.set_nonblocking(True)
            return True
        except Exception as e:
            print(f"Failed to open DualSense: {e}")
            print("Hint: You may need to run with sudo or set up udev rules")
            return False

    def close(self):
        """Close connection"""
        if self._device:
            self._device.close()
            self._device = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    def read(self) -> Optional[DualSenseState]:
        """
        Read current controller state

        Returns None if no data available (non-blocking)
        """
        if not self._device:
            return None

        try:
            data = self._device.read(64)
            if not data:
                return self._state  # Return last known state

            self._parse_input(bytes(data))
            return self._state

        except Exception as e:
            print(f"Read error: {e}")
            return None

    def read_blocking(self, timeout_ms: int = 1000) -> Optional[DualSenseState]:
        """Read with blocking wait for data"""
        if not self._device:
            return None

        self._device.set_nonblocking(False)
        try:
            data = self._device.read(64, timeout_ms)
            if data:
                self._parse_input(bytes(data))
            return self._state
        finally:
            self._device.set_nonblocking(True)

    def _parse_input(self, data: bytes):
        """Parse USB input report into state"""
        if len(data) < 64 or data[0] != USB_INPUT_REPORT_ID:
            return

        s = self._state

        # Sticks (bytes 1-4)
        s.left_stick_x = data[1]
        s.left_stick_y = data[2]
        s.right_stick_x = data[3]
        s.right_stick_y = data[4]

        # Triggers (bytes 5-6)
        s.l2_trigger = data[5]
        s.r2_trigger = data[6]

        # Timestamp (byte 7)
        s.timestamp = data[7]

        # Buttons byte 8: D-pad (lower nibble) + face buttons (upper nibble)
        s.dpad = DPad(data[8] & 0x0F)
        s.square = bool(data[8] & 0x10)
        s.cross = bool(data[8] & 0x20)
        s.circle = bool(data[8] & 0x40)
        s.triangle = bool(data[8] & 0x80)

        # Buttons byte 9: shoulders and center
        s.l1 = bool(data[9] & 0x01)
        s.r1 = bool(data[9] & 0x02)
        s.l2_button = bool(data[9] & 0x04)
        s.r2_button = bool(data[9] & 0x08)
        s.create = bool(data[9] & 0x10)
        s.options = bool(data[9] & 0x20)
        s.l3 = bool(data[9] & 0x40)
        s.r3 = bool(data[9] & 0x80)

        # Buttons byte 10: PS, touchpad, mute
        s.ps = bool(data[10] & 0x01)
        s.touchpad_click = bool(data[10] & 0x02)
        s.mute = bool(data[10] & 0x04)

        # Gyroscope (bytes 16-21, signed 16-bit)
        s.gyro_x = struct.unpack_from('<h', data, 16)[0]
        s.gyro_y = struct.unpack_from('<h', data, 18)[0]
        s.gyro_z = struct.unpack_from('<h', data, 20)[0]

        # Accelerometer (bytes 22-27, signed 16-bit)
        s.accel_x = struct.unpack_from('<h', data, 22)[0]
        s.accel_y = struct.unpack_from('<h', data, 24)[0]
        s.accel_z = struct.unpack_from('<h', data, 26)[0]

        # Touchpad (bytes 33-41)
        # Touch point 1
        touch1_data = data[33:37]
        s.touch1.active = not bool(touch1_data[0] & 0x80)
        s.touch1.id = touch1_data[0] & 0x7F
        s.touch1.x = ((touch1_data[2] & 0x0F) << 8) | touch1_data[1]
        s.touch1.y = (touch1_data[3] << 4) | ((touch1_data[2] & 0xF0) >> 4)

        # Touch point 2
        touch2_data = data[37:41]
        s.touch2.active = not bool(touch2_data[0] & 0x80)
        s.touch2.id = touch2_data[0] & 0x7F
        s.touch2.x = ((touch2_data[2] & 0x0F) << 8) | touch2_data[1]
        s.touch2.y = (touch2_data[3] << 4) | ((touch2_data[2] & 0xF0) >> 4)

        # Battery and status (byte 53)
        s.battery_level = data[53] & 0x0F
        s.battery_charging = bool(data[53] & 0x10)

        # Audio status (byte 54)
        s.headphones = bool(data[54] & 0x01)
        s.microphone = bool(data[54] & 0x02)

    # ========== Output Methods ==========

    def set_lightbar(self, r: int, g: int, b: int):
        """Set lightbar RGB color (0-255 each)"""
        self._lightbar_r = max(0, min(255, r))
        self._lightbar_g = max(0, min(255, g))
        self._lightbar_b = max(0, min(255, b))

    def set_player_leds(self, leds: PlayerLED):
        """Set player indicator LEDs"""
        self._player_leds = leds

    def set_mute_led(self, on: bool):
        """Set mute button LED"""
        self._mute_led = on

    def set_haptic(self, left: int, right: int):
        """Set haptic motor intensity (0-255)"""
        self._haptic_left = max(0, min(255, left))
        self._haptic_right = max(0, min(255, right))

    def set_trigger_effect(self, trigger: str, mode: TriggerMode,
                          start: int = 0, force: int = 0):
        """
        Set adaptive trigger effect

        Args:
            trigger: 'L2' or 'R2'
            mode: TriggerMode
            start: Start position (0-255)
            force: Resistance force (0-255)
        """
        params = bytearray(10)

        if mode == TriggerMode.RIGID:
            # Rigid resistance from start position
            params[0] = start
            params[1] = force
        elif mode == TriggerMode.PULSE:
            # Pulsing resistance
            params[0] = start
            params[1] = force
            params[2] = 0x02  # Frequency

        if trigger.upper() == 'L2':
            self._l2_trigger_mode = mode
            self._l2_trigger_params = bytes(params)
        else:
            self._r2_trigger_mode = mode
            self._r2_trigger_params = bytes(params)

    def clear_trigger_effect(self, trigger: str = 'both'):
        """Clear adaptive trigger effect"""
        if trigger.lower() in ('l2', 'both'):
            self._l2_trigger_mode = TriggerMode.OFF
            self._l2_trigger_params = bytes(10)
        if trigger.lower() in ('r2', 'both'):
            self._r2_trigger_mode = TriggerMode.OFF
            self._r2_trigger_params = bytes(10)

    def send(self) -> bool:
        """Send output report to controller"""
        if not self._device:
            return False

        # Build output report (48 bytes for USB)
        report = bytearray(48)
        report[0] = USB_OUTPUT_REPORT_ID

        # Flags for what we're setting
        # Byte 1: Enable flags 1
        report[1] = 0xFF  # Enable haptic, triggers
        # Byte 2: Enable flags 2
        report[2] = 0xF7  # Enable lightbar, player LEDs, mute LED

        # Haptic motors (bytes 3-4)
        report[3] = self._haptic_right
        report[4] = self._haptic_left

        # Headphone volume, speaker, mic (bytes 5-8) - leave default

        # Mute LED (byte 9)
        report[9] = 0x01 if self._mute_led else 0x00

        # Audio control (byte 10) - leave default

        # Right trigger (bytes 11-21)
        report[11] = int(self._r2_trigger_mode)
        report[12:22] = self._r2_trigger_params[:10]

        # Left trigger (bytes 22-32)
        report[22] = int(self._l2_trigger_mode)
        report[23:33] = self._l2_trigger_params[:10]

        # Lightbar pulse (byte 39)
        report[39] = int(self._lightbar_pulse)

        # Lightbar brightness (byte 43) - 0 = max
        report[43] = 0x02  # Full brightness

        # Player LEDs (byte 44)
        report[44] = int(self._player_leds)

        # Lightbar RGB (bytes 45-47)
        report[45] = self._lightbar_r
        report[46] = self._lightbar_g
        report[47] = self._lightbar_b

        try:
            self._device.write(bytes(report))
            return True
        except Exception as e:
            print(f"Write error: {e}")
            return False

    # ========== Convenience Methods ==========

    def rumble(self, left: int = 128, right: int = 128, duration: float = 0.2):
        """Simple rumble effect"""
        self.set_haptic(left, right)
        self.send()
        time.sleep(duration)
        self.set_haptic(0, 0)
        self.send()

    def flash_lightbar(self, r: int, g: int, b: int,
                       times: int = 3, on_time: float = 0.1, off_time: float = 0.1):
        """Flash the lightbar"""
        for _ in range(times):
            self.set_lightbar(r, g, b)
            self.send()
            time.sleep(on_time)
            self.set_lightbar(0, 0, 0)
            self.send()
            time.sleep(off_time)


def list_devices():
    """List all connected DualSense controllers"""
    devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    for d in devices:
        print(f"Found: {d['product_string']}")
        print(f"  Path: {d['path']}")
        print(f"  Serial: {d['serial_number']}")
        print(f"  Interface: {d['interface_number']}")
    return devices


if __name__ == '__main__':
    print("DualSense device scan:")
    list_devices()
