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
# Sony DualSense (PS5) Controller - USB
KERNEL=="hidraw*", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="0ce6", MODE="0666", TAG+="uaccess"

# Sony DualSense (PS5) Controller - Bluetooth
KERNEL=="hidraw*", KERNELS=="*054C:0CE6*", MODE="0666", TAG+="uaccess"

# Also allow access via /dev/input for evdev
SUBSYSTEM=="input", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="0ce6", MODE="0666", TAG+="uaccess"
EOF

echo "Created $RULES_FILE"

# Reload udev rules
udevadm control --reload-rules
udevadm trigger

echo ""
echo "Done! Udev rules installed."
echo ""
echo "You may need to:"
echo "  1. Unplug and replug the controller"
echo "  2. Log out and back in (for 'uaccess' tag to take effect)"
echo ""
echo "After that, you can run the scripts without sudo."
