"""
DualSense PS5 Controller Library

Full read/write access to all DualSense features via USB or Bluetooth HID:
- Buttons, sticks, triggers (analog)
- Touchpad (2 points with coordinates)
- Gyroscope and accelerometer
- Haptic feedback (left/right motors)
- Adaptive triggers (resistance profiles)
- Lightbar RGB LED
- Player indicator LEDs
- Mute button LED

Protocol reference: https://controllers.fandom.com/wiki/Sony_DualSense

Bluetooth Note:
    When the Linux hid-playstation kernel driver is active, LED control
    is handled via sysfs (/sys/class/leds/) instead of raw HID reports.
    This library auto-detects the driver and uses the appropriate method.
"""

import struct
import time
import os
import glob
import re
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from typing import Optional, Tuple, Dict

try:
    import hid
except ImportError:
    hid = None

try:
    import evdev
    from evdev import ecodes
except ImportError:
    evdev = None


# Sony DualSense USB IDs
VENDOR_ID = 0x054C
PRODUCT_ID = 0x0CE6

# Report IDs
USB_INPUT_REPORT_ID = 0x01
USB_OUTPUT_REPORT_ID = 0x02
BT_INPUT_REPORT_ID = 0x31
BT_OUTPUT_REPORT_ID = 0x31


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


def _crc32(data: bytes) -> int:
    """Calculate CRC32 for Bluetooth output reports"""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
    return crc ^ 0xFFFFFFFF


def _find_dualsense_hidraw() -> Optional[Tuple[str, bool]]:
    """
    Find DualSense hidraw device path.

    Returns:
        Tuple of (path, is_bluetooth) or None if not found
        is_bluetooth is True if connected via Bluetooth (HID_ID starts with 0005)
    """
    for hidraw in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        try:
            with open(hidraw) as f:
                content = f.read()
                if "054C" in content and "0CE6" in content:
                    # Extract hidraw number
                    hidraw_name = hidraw.split("/")[4]
                    path = f"/dev/{hidraw_name}"

                    # Check if Bluetooth (HID_ID=0005:...) or USB (HID_ID=0003:...)
                    is_bluetooth = "HID_ID=0005:" in content

                    return (path, is_bluetooth)
        except:
            pass
    return None


def _get_dualsense_driver() -> Optional[str]:
    """Check which kernel driver is handling the DualSense"""
    for hidraw in glob.glob("/sys/class/hidraw/hidraw*/device/uevent"):
        try:
            with open(hidraw) as f:
                content = f.read()
                if "054C" in content and "0CE6" in content:
                    for line in content.split('\n'):
                        if line.startswith('DRIVER='):
                            return line.split('=')[1]
        except:
            pass
    return None


def _find_sysfs_leds() -> Dict[str, str]:
    """
    Find sysfs LED paths for DualSense when using hid-playstation driver.

    Returns dict with keys:
        'rgb' -> path to rgb:indicator (lightbar)
        'player1' through 'player5' -> paths to player LEDs
    """
    leds = {}

    # Find the RGB indicator (lightbar)
    for led_path in glob.glob("/sys/class/leds/*:rgb:indicator"):
        # Verify it's a DualSense by checking the device
        device_uevent = os.path.join(led_path, "device", "uevent")
        try:
            with open(device_uevent) as f:
                content = f.read()
                if "054C" in content and "0CE6" in content:
                    leds['rgb'] = led_path
                    break
        except:
            # Try alternative path structure
            pass

    # If not found via device link, search by pattern
    if 'rgb' not in leds:
        for led_path in glob.glob("/sys/class/leds/input*:rgb:indicator"):
            leds['rgb'] = led_path
            break

    # Find player LEDs (they're named player-1 through player-5)
    if 'rgb' in leds:
        # Extract the input number from rgb path (e.g., input28)
        match = re.search(r'input(\d+)', leds['rgb'])
        if match:
            input_num = match.group(1)
            for i in range(1, 6):
                player_path = f"/sys/class/leds/input{input_num}:white:player-{i}"
                if os.path.exists(player_path):
                    leds[f'player{i}'] = player_path

    return leds


def _find_ff_device() -> Optional[str]:
    """Find the evdev device for force feedback (haptics)"""
    if evdev is None:
        return None

    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            if "DualSense" in dev.name and "Motion" not in dev.name and "Touchpad" not in dev.name:
                # Check if it supports force feedback
                caps = dev.capabilities()
                if ecodes.EV_FF in caps:
                    return path
                dev.close()
        except:
            pass
    return None


def _find_evdev_devices() -> Dict[str, str]:
    """
    Find all evdev devices for DualSense controller.

    Returns dict with keys:
        'main' -> main controller (buttons, sticks, triggers)
        'motion' -> motion sensors (gyro, accel)
        'touchpad' -> touchpad (touch coordinates, click)
    """
    devices = {}
    if evdev is None:
        return devices

    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            if "DualSense" in dev.name:
                if "Motion" in dev.name:
                    devices['motion'] = path
                elif "Touchpad" in dev.name:
                    devices['touchpad'] = path
                else:
                    devices['main'] = path
            dev.close()
        except:
            pass

    return devices


class DualSense:
    """
    DualSense PS5 Controller interface

    Supports both USB and Bluetooth connections.

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
        self._device = None  # hid.device for USB
        self._hidraw_fd: Optional[int] = None  # File descriptor for Bluetooth
        self._is_bluetooth = False
        self._state = DualSenseState()

        # Sysfs mode (when hid-playstation driver is active)
        self._use_sysfs = False
        self._sysfs_leds: Dict[str, str] = {}
        self._ff_device = None  # evdev device for force feedback
        self._ff_effect_id = -1  # Uploaded FF effect ID

        # Evdev input devices (when hid-playstation driver is active)
        self._use_evdev = False
        self._evdev_main = None      # Main controller (buttons, sticks, triggers)
        self._evdev_motion = None    # Motion sensors (gyro, accel)
        self._evdev_touchpad = None  # Touchpad
        self._hat_x = 0  # D-pad X: -1=left, 0=center, 1=right
        self._hat_y = 0  # D-pad Y: -1=up, 0=center, 1=down

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
        """Open connection to DualSense controller (USB or Bluetooth)"""
        # Try USB first via hid library
        if hid:
            try:
                self._device = hid.device()
                self._device.open(VENDOR_ID, PRODUCT_ID)
                self._device.set_nonblocking(True)
                self._is_bluetooth = False
                self._use_sysfs = False
                print("Connected via USB (hidapi)")
                return True
            except Exception:
                self._device = None

        # Check if hid-playstation driver is active
        driver = _get_dualsense_driver()

        # Try hidraw (works for both USB and Bluetooth when playstation driver is active)
        hidraw_result = _find_dualsense_hidraw()
        if hidraw_result:
            hidraw_path, is_bluetooth = hidraw_result
            try:
                self._hidraw_fd = os.open(hidraw_path, os.O_RDWR | os.O_NONBLOCK)
                self._is_bluetooth = is_bluetooth

                # If playstation driver is active, use evdev for d-pad/buttons input
                # The driver intercepts these from raw HID and routes to evdev
                # For Bluetooth: also use sysfs for LED output
                # For USB: use hidraw for LED output, but evdev for button input
                if driver == "playstation":
                    # Bluetooth uses sysfs for LED output, USB uses hidraw
                    if is_bluetooth:
                        self._use_sysfs = True
                        self._sysfs_leds = _find_sysfs_leds()
                    else:
                        self._use_sysfs = False

                    # Try to open evdev devices for inputs (both USB and Bluetooth)
                    # The playstation driver routes d-pad/buttons to evdev
                    evdev_paths = _find_evdev_devices()
                    if evdev and evdev_paths.get('main'):
                        try:
                            self._evdev_main = evdev.InputDevice(evdev_paths['main'])
                            self._evdev_main.grab()  # Exclusive access
                            self._use_evdev = True

                            # Try to open motion sensors
                            if 'motion' in evdev_paths:
                                try:
                                    self._evdev_motion = evdev.InputDevice(evdev_paths['motion'])
                                except:
                                    pass

                            # Try to open touchpad
                            if 'touchpad' in evdev_paths:
                                try:
                                    self._evdev_touchpad = evdev.InputDevice(evdev_paths['touchpad'])
                                except:
                                    pass
                        except Exception as e:
                            print(f"  Warning: Could not open evdev ({e}), using hidraw for input")
                            self._use_evdev = False

                    # Try to open force feedback device for haptics
                    ff_path = _find_ff_device()
                    if ff_path and evdev and not self._ff_device:
                        try:
                            # Use the already-opened main device if it has FF
                            if self._evdev_main:
                                caps = self._evdev_main.capabilities()
                                if ecodes.EV_FF in caps:
                                    self._ff_device = self._evdev_main
                            if not self._ff_device:
                                self._ff_device = evdev.InputDevice(ff_path)
                        except:
                            self._ff_device = None

                    conn_type = "Bluetooth" if is_bluetooth else "USB"
                    output_mode = "sysfs" if self._use_sysfs else "hidraw"
                    input_mode = "evdev" if self._use_evdev else "hidraw"
                    ff_status = "yes" if self._ff_device else "no"
                    motion_status = "yes" if self._evdev_motion else "no"
                    touch_status = "yes" if self._evdev_touchpad else "no"
                    print(f"Connected via {conn_type} ({hidraw_path})")
                    print(f"  Driver: hid-playstation (kernel)")
                    print(f"  Input: {input_mode}, Output: {output_mode}")
                    print(f"  FF: {ff_status}, Motion: {motion_status}, Touchpad: {touch_status}")
                else:
                    # USB with playstation driver OR Bluetooth without playstation driver
                    self._use_sysfs = False
                    conn_type = "Bluetooth" if is_bluetooth else "USB"
                    print(f"Connected via {conn_type} ({hidraw_path})")
                    print(f"  Using raw HID (driver: {driver})")

                return True
            except Exception as e:
                print(f"Failed to open {hidraw_path}: {e}")
                self._hidraw_fd = None

        print("Failed to open DualSense")
        print("Hint: You may need to run with sudo or set up udev rules")
        return False

    def close(self):
        """Close connection"""
        if self._device:
            self._device.close()
            self._device = None
        if self._hidraw_fd is not None:
            os.close(self._hidraw_fd)
            self._hidraw_fd = None

        # Clean up evdev devices
        if self._evdev_main:
            try:
                self._evdev_main.ungrab()
            except:
                pass
            # Don't close if it's also the FF device
            if self._evdev_main != self._ff_device:
                self._evdev_main.close()
            self._evdev_main = None
        if self._evdev_motion:
            self._evdev_motion.close()
            self._evdev_motion = None
        if self._evdev_touchpad:
            self._evdev_touchpad.close()
            self._evdev_touchpad = None

        if self._ff_device:
            # Erase any uploaded effect
            if self._ff_effect_id >= 0:
                try:
                    self._ff_device.erase_effect(self._ff_effect_id)
                except:
                    pass
            self._ff_device.close()
            self._ff_device = None
            self._ff_effect_id = -1

        self._is_bluetooth = False
        self._use_sysfs = False
        self._use_evdev = False
        self._sysfs_leds = {}

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    @property
    def connection_type(self) -> str:
        """Return the connection type: 'usb', 'usb_hidraw', 'bluetooth_sysfs', 'bluetooth_raw', or 'none'"""
        if self._device:
            return 'usb'
        elif self._hidraw_fd is not None:
            if self._is_bluetooth:
                return 'bluetooth_sysfs' if self._use_sysfs else 'bluetooth_raw'
            else:
                return 'usb_hidraw'
        return 'none'

    @property
    def using_sysfs(self) -> bool:
        """Check if using sysfs for outputs (kernel driver mode)"""
        return self._use_sysfs

    def read(self) -> Optional[DualSenseState]:
        """
        Read current controller state

        Returns None if no data available (non-blocking)
        """
        try:
            # Prefer evdev when available (better for Bluetooth with hid-playstation)
            if self._use_evdev and self._evdev_main:
                self._read_evdev()
                return self._state

            elif self._hidraw_fd is not None:
                # Bluetooth via hidraw (fallback)
                import select
                r, _, _ = select.select([self._hidraw_fd], [], [], 0)
                if r:
                    data = os.read(self._hidraw_fd, 128)
                    if data:
                        self._parse_input(bytes(data))
                return self._state

            elif self._device:
                # USB via hid library
                data = self._device.read(64)
                if not data:
                    return self._state
                self._parse_input(bytes(data))
                return self._state

            return None
        except Exception as e:
            print(f"Read error: {e}")
            return None

    def read_blocking(self, timeout_ms: int = 1000) -> Optional[DualSenseState]:
        """Read with blocking wait for data"""
        import select

        try:
            # Prefer evdev when available
            if self._use_evdev and self._evdev_main:
                # Build list of file descriptors to wait on
                fds = [self._evdev_main.fd]
                if self._evdev_motion:
                    fds.append(self._evdev_motion.fd)
                if self._evdev_touchpad:
                    fds.append(self._evdev_touchpad.fd)

                r, _, _ = select.select(fds, [], [], timeout_ms / 1000.0)
                if r:
                    self._read_evdev()
                return self._state

            elif self._hidraw_fd is not None:
                # Bluetooth via hidraw (fallback)
                r, _, _ = select.select([self._hidraw_fd], [], [], timeout_ms / 1000.0)
                if r:
                    data = os.read(self._hidraw_fd, 128)
                    if data:
                        self._parse_input(bytes(data))
                return self._state

            elif self._device:
                # USB via hid library
                self._device.set_nonblocking(False)
                try:
                    data = self._device.read(64, timeout_ms)
                    if data:
                        self._parse_input(bytes(data))
                    return self._state
                finally:
                    self._device.set_nonblocking(True)

            return None
        except Exception as e:
            print(f"Read error: {e}")
            return self._state

    def _parse_input(self, data: bytes):
        """Parse input report into state (USB or Bluetooth)"""
        if len(data) < 10:
            return

        s = self._state

        # Determine format based on report ID
        if data[0] == BT_INPUT_REPORT_ID and len(data) >= 78:
            # Bluetooth format: data starts at offset 2
            offset = 2
        elif data[0] == USB_INPUT_REPORT_ID and len(data) >= 64:
            # USB format: data starts at offset 1
            offset = 1
        else:
            return

        # Sticks (bytes 0-3 from offset)
        s.left_stick_x = data[offset + 0]
        s.left_stick_y = data[offset + 1]
        s.right_stick_x = data[offset + 2]
        s.right_stick_y = data[offset + 3]

        # Triggers (bytes 4-5 from offset)
        s.l2_trigger = data[offset + 4]
        s.r2_trigger = data[offset + 5]

        # Timestamp (byte 6 from offset)
        s.timestamp = data[offset + 6]

        # Buttons byte 7: D-pad (lower nibble) + face buttons (upper nibble)
        btn0 = data[offset + 7]
        s.dpad = DPad(btn0 & 0x0F)
        s.square = bool(btn0 & 0x10)
        s.cross = bool(btn0 & 0x20)
        s.circle = bool(btn0 & 0x40)
        s.triangle = bool(btn0 & 0x80)

        # Buttons byte 8: shoulders and center
        btn1 = data[offset + 8]
        s.l1 = bool(btn1 & 0x01)
        s.r1 = bool(btn1 & 0x02)
        s.l2_button = bool(btn1 & 0x04)
        s.r2_button = bool(btn1 & 0x08)
        s.create = bool(btn1 & 0x10)
        s.options = bool(btn1 & 0x20)
        s.l3 = bool(btn1 & 0x40)
        s.r3 = bool(btn1 & 0x80)

        # Buttons byte 9: PS, touchpad, mute
        btn2 = data[offset + 9]
        s.ps = bool(btn2 & 0x01)
        s.touchpad_click = bool(btn2 & 0x02)
        s.mute = bool(btn2 & 0x04)

        # Gyroscope (bytes 15-20 from offset, signed 16-bit)
        gyro_offset = offset + 15
        if len(data) >= gyro_offset + 6:
            s.gyro_x = struct.unpack_from('<h', data, gyro_offset)[0]
            s.gyro_y = struct.unpack_from('<h', data, gyro_offset + 2)[0]
            s.gyro_z = struct.unpack_from('<h', data, gyro_offset + 4)[0]

        # Accelerometer (bytes 21-26 from offset, signed 16-bit)
        accel_offset = offset + 21
        if len(data) >= accel_offset + 6:
            s.accel_x = struct.unpack_from('<h', data, accel_offset)[0]
            s.accel_y = struct.unpack_from('<h', data, accel_offset + 2)[0]
            s.accel_z = struct.unpack_from('<h', data, accel_offset + 4)[0]

        # Touchpad (bytes 32-40 from offset)
        touch_offset = offset + 32
        if len(data) >= touch_offset + 8:
            # Touch point 1
            touch1_data = data[touch_offset:touch_offset + 4]
            s.touch1.active = not bool(touch1_data[0] & 0x80)
            s.touch1.id = touch1_data[0] & 0x7F
            s.touch1.x = ((touch1_data[2] & 0x0F) << 8) | touch1_data[1]
            s.touch1.y = (touch1_data[3] << 4) | ((touch1_data[2] & 0xF0) >> 4)

            # Touch point 2
            touch2_data = data[touch_offset + 4:touch_offset + 8]
            s.touch2.active = not bool(touch2_data[0] & 0x80)
            s.touch2.id = touch2_data[0] & 0x7F
            s.touch2.x = ((touch2_data[2] & 0x0F) << 8) | touch2_data[1]
            s.touch2.y = (touch2_data[3] << 4) | ((touch2_data[2] & 0xF0) >> 4)

        # Battery and status (byte 52 from offset)
        batt_offset = offset + 52
        if len(data) > batt_offset + 1:
            s.battery_level = data[batt_offset] & 0x0F
            s.battery_charging = bool(data[batt_offset] & 0x10)

            # Audio status
            s.headphones = bool(data[batt_offset + 1] & 0x01)
            s.microphone = bool(data[batt_offset + 1] & 0x02)

    def _read_evdev(self):
        """Read input from evdev devices (when using hid-playstation driver)"""
        if not evdev:
            return

        s = self._state

        # Read main controller events (buttons, sticks, triggers, d-pad)
        if self._evdev_main:
            try:
                for event in self._evdev_main.read():
                    if event.type == ecodes.EV_KEY:
                        pressed = event.value == 1
                        code = event.code

                        # Face buttons (Sony layout: Cross=South, Circle=East, etc.)
                        if code == ecodes.BTN_SOUTH:  # Cross
                            s.cross = pressed
                        elif code == ecodes.BTN_EAST:  # Circle
                            s.circle = pressed
                        elif code == ecodes.BTN_NORTH:  # Triangle
                            s.triangle = pressed
                        elif code == ecodes.BTN_WEST:  # Square
                            s.square = pressed
                        # Shoulders
                        elif code == ecodes.BTN_TL:
                            s.l1 = pressed
                        elif code == ecodes.BTN_TR:
                            s.r1 = pressed
                        elif code == ecodes.BTN_TL2:
                            s.l2_button = pressed
                        elif code == ecodes.BTN_TR2:
                            s.r2_button = pressed
                        # Center buttons
                        elif code == ecodes.BTN_SELECT:
                            s.create = pressed
                        elif code == ecodes.BTN_START:
                            s.options = pressed
                        elif code == ecodes.BTN_MODE:
                            s.ps = pressed
                        # Stick clicks
                        elif code == ecodes.BTN_THUMBL:
                            s.l3 = pressed
                        elif code == ecodes.BTN_THUMBR:
                            s.r3 = pressed

                    elif event.type == ecodes.EV_ABS:
                        code = event.code
                        value = event.value

                        # Sticks
                        if code == ecodes.ABS_X:
                            s.left_stick_x = value
                        elif code == ecodes.ABS_Y:
                            s.left_stick_y = value
                        elif code == ecodes.ABS_RX:
                            s.right_stick_x = value
                        elif code == ecodes.ABS_RY:
                            s.right_stick_y = value
                        # Triggers (analog)
                        elif code == ecodes.ABS_Z:
                            s.l2_trigger = value
                        elif code == ecodes.ABS_RZ:
                            s.r2_trigger = value
                        # D-pad
                        elif code == ecodes.ABS_HAT0X:
                            # -1=left, 0=center, 1=right
                            self._hat_x = value
                            self._update_dpad_from_hat()
                        elif code == ecodes.ABS_HAT0Y:
                            # -1=up, 0=center, 1=down
                            self._hat_y = value
                            self._update_dpad_from_hat()
            except BlockingIOError:
                pass  # No events available

        # Read motion sensor events (gyro, accel)
        if self._evdev_motion:
            try:
                for event in self._evdev_motion.read():
                    if event.type == ecodes.EV_ABS:
                        code = event.code
                        value = event.value

                        # Gyroscope (RX, RY, RZ)
                        if code == ecodes.ABS_RX:
                            s.gyro_x = value
                        elif code == ecodes.ABS_RY:
                            s.gyro_y = value
                        elif code == ecodes.ABS_RZ:
                            s.gyro_z = value
                        # Accelerometer (X, Y, Z)
                        elif code == ecodes.ABS_X:
                            s.accel_x = value
                        elif code == ecodes.ABS_Y:
                            s.accel_y = value
                        elif code == ecodes.ABS_Z:
                            s.accel_z = value
            except BlockingIOError:
                pass

        # Read touchpad events
        if self._evdev_touchpad:
            try:
                for event in self._evdev_touchpad.read():
                    if event.type == ecodes.EV_KEY:
                        pressed = event.value == 1
                        # Touchpad click is BTN_LEFT on the touchpad device
                        if event.code == ecodes.BTN_LEFT:
                            s.touchpad_click = pressed
                        # Some firmwares report mute here
                        elif event.code == ecodes.BTN_RIGHT:
                            s.mute = pressed

                    elif event.type == ecodes.EV_ABS:
                        code = event.code
                        value = event.value

                        # Touch point 0
                        if code == ecodes.ABS_MT_POSITION_X:
                            s.touch1.x = value
                            s.touch1.active = True
                        elif code == ecodes.ABS_MT_POSITION_Y:
                            s.touch1.y = value
                            s.touch1.active = True
                        elif code == ecodes.ABS_MT_TRACKING_ID:
                            if value == -1:
                                s.touch1.active = False
                            else:
                                s.touch1.id = value
                                s.touch1.active = True
            except BlockingIOError:
                pass

    def _update_dpad_from_hat(self):
        """Update d-pad state from HAT0X/HAT0Y values"""
        s = self._state
        hat_x = self._hat_x
        hat_y = self._hat_y

        old_dpad = s.dpad

        # Map HAT values to DPad enum
        # HAT0X: -1=left, 0=center, 1=right
        # HAT0Y: -1=up, 0=center, 1=down
        if hat_x == 0 and hat_y == 0:
            s.dpad = DPad.NONE
        elif hat_x == 0 and hat_y == -1:
            s.dpad = DPad.UP
        elif hat_x == 1 and hat_y == -1:
            s.dpad = DPad.UP_RIGHT
        elif hat_x == 1 and hat_y == 0:
            s.dpad = DPad.RIGHT
        elif hat_x == 1 and hat_y == 1:
            s.dpad = DPad.DOWN_RIGHT
        elif hat_x == 0 and hat_y == 1:
            s.dpad = DPad.DOWN
        elif hat_x == -1 and hat_y == 1:
            s.dpad = DPad.DOWN_LEFT
        elif hat_x == -1 and hat_y == 0:
            s.dpad = DPad.LEFT
        elif hat_x == -1 and hat_y == -1:
            s.dpad = DPad.UP_LEFT

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
        if self._use_sysfs:
            return self._send_sysfs()
        elif self._hidraw_fd is not None:
            # USB via hidraw uses USB format, Bluetooth uses BT format
            if self._is_bluetooth:
                return self._send_bluetooth()
            else:
                return self._send_usb_hidraw()
        elif self._device:
            return self._send_usb()
        return False

    def _send_usb(self) -> bool:
        """Send USB output report"""
        # Build output report (48 bytes for USB)
        report = bytearray(48)
        report[0] = USB_OUTPUT_REPORT_ID

        # Flags for what we're setting
        report[1] = 0xFF  # Enable haptic, triggers
        report[2] = 0xF7  # Enable lightbar, player LEDs, mute LED

        # Haptic motors (bytes 3-4)
        report[3] = self._haptic_right
        report[4] = self._haptic_left

        # Mute LED (byte 9)
        report[9] = 0x01 if self._mute_led else 0x00

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

    def _send_usb_hidraw(self) -> bool:
        """Send USB output report via hidraw (playstation driver)"""
        # Build output report (48 bytes for USB)
        report = bytearray(48)
        report[0] = USB_OUTPUT_REPORT_ID

        # Flags for what we're setting
        report[1] = 0xFF  # Enable haptic, triggers
        report[2] = 0xF7  # Enable lightbar, player LEDs, mute LED

        # Haptic motors (bytes 3-4)
        report[3] = self._haptic_right
        report[4] = self._haptic_left

        # Mute LED (byte 9)
        report[9] = 0x01 if self._mute_led else 0x00

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
            os.write(self._hidraw_fd, bytes(report))
            return True
        except Exception as e:
            print(f"USB hidraw write error: {e}")
            return False

    def _send_bluetooth(self) -> bool:
        """Send Bluetooth output report (with CRC32)"""
        # Bluetooth report is 78 bytes total
        report = bytearray(78)
        report[0] = BT_OUTPUT_REPORT_ID  # 0x31
        report[1] = 0x02  # Sequence tag
        report[2] = 0x10  # Enable HID output (CRITICAL - was 0x00)

        # Valid flags - same meaning as USB but offset +2
        # Byte 3: flags0 - 0x01=rumble, 0x02=rumble, 0x04=headphone LED, 0x10=mic LED
        # Byte 4: flags1 - 0x01=mic mute LED, 0x02=power save, 0x04=lightbar, 0x08=player LEDs, 0x10=haptic
        report[3] = 0x03  # Enable rumble motors
        report[4] = 0x15  # Enable lightbar (0x04) + player LEDs (0x08) + haptics (0x01) + motor power (0x10)

        # Haptic motors (bytes 5-6)
        report[5] = self._haptic_right
        report[6] = self._haptic_left

        # Mute LED (byte 11)
        report[11] = 0x01 if self._mute_led else 0x00

        # Right trigger (byte 13+)
        report[13] = int(self._r2_trigger_mode)
        report[14:24] = self._r2_trigger_params[:10]

        # Left trigger (byte 24+)
        report[24] = int(self._l2_trigger_mode)
        report[25:35] = self._l2_trigger_params[:10]

        # Lightbar pulse (byte 41)
        report[41] = int(self._lightbar_pulse)

        # Lightbar brightness (byte 45): 0=high, 1=medium, 2=low
        report[45] = 0x00  # Full brightness

        # Player LEDs (byte 46)
        report[46] = int(self._player_leds)

        # Lightbar RGB (bytes 47-49)
        report[47] = self._lightbar_r
        report[48] = self._lightbar_g
        report[49] = self._lightbar_b

        # Calculate CRC32 over seed + first 74 bytes
        seed = bytes([0xA2])  # BT output report seed
        crc = _crc32(seed + bytes(report[:74]))
        struct.pack_into('<I', report, 74, crc)

        try:
            os.write(self._hidraw_fd, bytes(report))
            return True
        except Exception as e:
            print(f"Write error: {e}")
            return False

    def _send_sysfs(self) -> bool:
        """Send outputs via sysfs (when hid-playstation driver is active)"""
        success = True

        # Set lightbar RGB via sysfs
        if 'rgb' in self._sysfs_leds:
            rgb_path = self._sysfs_leds['rgb']
            try:
                # Set the RGB intensity
                intensity_path = os.path.join(rgb_path, 'multi_intensity')
                with open(intensity_path, 'w') as f:
                    f.write(f"{self._lightbar_r} {self._lightbar_g} {self._lightbar_b}")

                # Ensure brightness is on (255 = full)
                brightness_path = os.path.join(rgb_path, 'brightness')
                with open(brightness_path, 'w') as f:
                    f.write("255")
            except PermissionError:
                print("Permission denied writing to LED sysfs. Try:")
                print("  sudo chmod 666 /sys/class/leds/input*:rgb:indicator/*")
                success = False
            except Exception as e:
                print(f"Lightbar sysfs error: {e}")
                success = False

        # Set player LEDs via sysfs
        # PlayerLED flags: LEFT=0x01, MIDDLE_LEFT=0x02, MIDDLE=0x04, MIDDLE_RIGHT=0x08, RIGHT=0x10
        # Sysfs has player-1 through player-5 (left to right)
        led_mapping = {
            'player1': PlayerLED.LEFT,        # 0x01
            'player2': PlayerLED.MIDDLE_LEFT, # 0x02
            'player3': PlayerLED.MIDDLE,      # 0x04
            'player4': PlayerLED.MIDDLE_RIGHT,# 0x08
            'player5': PlayerLED.RIGHT,       # 0x10
        }

        for led_name, flag in led_mapping.items():
            if led_name in self._sysfs_leds:
                try:
                    brightness = "1" if (self._player_leds & flag) else "0"
                    brightness_path = os.path.join(self._sysfs_leds[led_name], 'brightness')
                    with open(brightness_path, 'w') as f:
                        f.write(brightness)
                except PermissionError:
                    pass  # Don't spam for each LED
                except Exception:
                    pass

        # Haptic feedback via force feedback (if available)
        if self._ff_device and evdev and (self._haptic_left > 0 or self._haptic_right > 0):
            try:
                from evdev import ff

                # Create a rumble effect
                # evdev expects values 0-65535, we have 0-255
                strong = int((self._haptic_left / 255.0) * 65535)
                weak = int((self._haptic_right / 255.0) * 65535)

                # Build effect using correct ctypes structure
                effect = ff.Effect()
                effect.type = ecodes.FF_RUMBLE
                effect.id = -1  # Let kernel assign ID
                effect.u.ff_rumble_effect.strong_magnitude = strong
                effect.u.ff_rumble_effect.weak_magnitude = weak
                effect.ff_replay.length = 100  # ms
                effect.ff_replay.delay = 0

                # Erase old effect if exists
                if self._ff_effect_id >= 0:
                    try:
                        self._ff_device.erase_effect(self._ff_effect_id)
                    except:
                        pass

                # Upload and play the effect
                self._ff_effect_id = self._ff_device.upload_effect(effect)
                self._ff_device.write(ecodes.EV_FF, self._ff_effect_id, 1)
            except Exception as e:
                # Force feedback can be finicky, don't fail the whole send
                pass
        elif self._ff_device and self._haptic_left == 0 and self._haptic_right == 0:
            # Stop any playing effect
            if self._ff_effect_id >= 0:
                try:
                    self._ff_device.write(ecodes.EV_FF, self._ff_effect_id, 0)
                except:
                    pass

        return success

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
    """List all connected DualSense controllers (USB and Bluetooth)"""
    found = []

    # Check USB via hid library
    if hid:
        devices = hid.enumerate(VENDOR_ID, PRODUCT_ID)
        for d in devices:
            print(f"Found (USB): {d['product_string']}")
            print(f"  Path: {d['path']}")
            print(f"  Serial: {d['serial_number']}")
            print(f"  Interface: {d['interface_number']}")
            found.append(('usb', d))

    # Check hidraw (USB or Bluetooth with playstation driver)
    hidraw_result = _find_dualsense_hidraw()
    if hidraw_result:
        hidraw_path, is_bluetooth = hidraw_result
        driver = _get_dualsense_driver()
        conn_type = "Bluetooth" if is_bluetooth else "USB"
        print(f"Found ({conn_type} hidraw): DualSense Wireless Controller")
        print(f"  Path: {hidraw_path}")
        print(f"  Driver: {driver or 'unknown'}")

        if driver == "playstation" and is_bluetooth:
            sysfs_leds = _find_sysfs_leds()
            print(f"  Sysfs LEDs: {list(sysfs_leds.keys())}")
            ff_path = _find_ff_device()
            print(f"  Force feedback: {ff_path or 'not found'}")

        found.append((conn_type.lower(), hidraw_path))

    if not found:
        print("No DualSense controllers found")

    return found


if __name__ == '__main__':
    print("DualSense device scan:")
    list_devices()
