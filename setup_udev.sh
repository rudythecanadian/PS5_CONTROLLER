#!/bin/bash
#
# Setup udev rules for DualSense controller
# This allows accessing the controller without root/sudo
#
# Run once with: sudo ./setup_udev.sh
#

RULES_FILE="/etc/udev/rules.d/99-dualsense.rules"

echo "Setting up udev rules for DualSense controller..."

# Create the rules file
cat > "$RULES_FILE" << 'EOF'
# Sony DualSense (PS5) Controller - USB hidraw
KERNEL=="hidraw*", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="0ce6", MODE="0666", TAG+="uaccess"

# Sony DualSense (PS5) Controller - Bluetooth hidraw
KERNEL=="hidraw*", KERNELS=="*054C:0CE6*", MODE="0666", TAG+="uaccess"

# DualSense evdev devices (main controller, motion sensors, touchpad)
# Match by name since Bluetooth doesn't expose vendor/product the same way
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="DualSense Wireless Controller", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="DualSense Wireless Controller Motion Sensors", MODE="0666", TAG+="uaccess"
SUBSYSTEM=="input", KERNEL=="event*", ATTRS{name}=="DualSense Wireless Controller Touchpad", MODE="0666", TAG+="uaccess"

# USB evdev fallback (matches by vendor/product)
SUBSYSTEM=="input", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="0ce6", MODE="0666", TAG+="uaccess"

# DualSense LEDs (when using hid-playstation driver)
# Lightbar RGB
SUBSYSTEM=="leds", KERNEL=="*:rgb:indicator", DRIVERS=="playstation", RUN+="/bin/chmod 666 /sys%p/brightness /sys%p/multi_intensity"

# Player LEDs
SUBSYSTEM=="leds", KERNEL=="*:white:player-*", DRIVERS=="playstation", RUN+="/bin/chmod 666 /sys%p/brightness"
EOF

echo "Created $RULES_FILE"

# Reload udev rules
udevadm control --reload-rules
udevadm trigger

# Also fix permissions on any existing devices
echo "Setting permissions on existing DualSense devices..."

# Fix LED permissions
for led in /sys/class/leds/*:rgb:indicator; do
    if [ -d "$led" ]; then
        chmod 666 "$led/brightness" "$led/multi_intensity" 2>/dev/null && echo "  Fixed LED: $led"
    fi
done
for led in /sys/class/leds/*:white:player-*; do
    if [ -d "$led" ]; then
        chmod 666 "$led/brightness" 2>/dev/null
    fi
done

# Fix evdev permissions (find by name in /proc/bus/input/devices)
echo "Setting permissions on DualSense evdev devices..."
for event in /dev/input/event*; do
    name=$(cat /sys/class/input/$(basename $event)/device/name 2>/dev/null)
    if [[ "$name" == *"DualSense"* ]]; then
        chmod 666 "$event" 2>/dev/null && echo "  Fixed evdev: $event ($name)"
    fi
done

# Bind any unbound USB DualSense devices to playstation driver
echo "Checking for unbound USB DualSense devices..."
for hid_dev in /sys/bus/hid/devices/0003:054C:0CE6.*; do
    if [ -d "$hid_dev" ]; then
        dev_name=$(basename "$hid_dev")
        # Check if it has a hidraw (meaning driver is bound)
        if [ ! -d "$hid_dev/hidraw" ]; then
            echo "  Binding $dev_name to playstation driver..."
            echo "$dev_name" > /sys/bus/hid/drivers/playstation/bind 2>/dev/null || \
            echo "$dev_name" > /sys/bus/hid/drivers/hid-generic/bind 2>/dev/null || \
            echo "    Failed to bind (may need replug)"
        fi
    fi
done

# Fix hidraw permissions
echo "Setting permissions on hidraw devices..."
for hidraw in /dev/hidraw*; do
    # Check if this is a DualSense
    hidraw_name=$(basename "$hidraw")
    uevent="/sys/class/hidraw/$hidraw_name/device/uevent"
    if grep -q "054C" "$uevent" 2>/dev/null && grep -q "0CE6" "$uevent" 2>/dev/null; then
        chmod 666 "$hidraw" 2>/dev/null && echo "  Fixed: $hidraw"
    fi
done

echo ""
echo "Done! Udev rules installed."
echo ""
echo "You may need to:"
echo "  1. Unplug and replug the controller (or reconnect Bluetooth)"
echo "  2. Log out and back in (for 'uaccess' tag to take effect)"
echo ""
echo "After that, you can run the scripts without sudo."
echo ""
echo "For Bluetooth with hid-playstation driver:"
echo "  - LEDs are controlled via sysfs (permissions set automatically)"
echo "  - Haptics use force feedback (evdev)"
echo "  - Adaptive triggers are NOT supported via sysfs (kernel limitation)"
