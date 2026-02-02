#!/bin/bash
#
# Start DualSense Web UI
#

cd "$(dirname "$0")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if already running
if pgrep -f "python3 web_ui.py" > /dev/null; then
    echo -e "${YELLOW}Web UI is already running (PID: $(pgrep -f 'python3 web_ui.py'))${NC}"
    echo "Use ./stop_webui.bash to stop it first"
    exit 1
fi

# Check connection status
echo "Checking DualSense connection..."

USB_CONNECTED=false
BT_CONNECTED=false
BT_MAC=""

# Check for USB
if lsusb 2>/dev/null | grep -q "054c:0ce6"; then
    USB_CONNECTED=true
fi

# Check for Bluetooth (look for hidraw with Bluetooth HID_ID starting with 0005)
for uevent in /sys/class/hidraw/hidraw*/device/uevent; do
    if grep -q "054C" "$uevent" 2>/dev/null && grep -q "0CE6" "$uevent" 2>/dev/null; then
        if grep -q "HID_ID=0005" "$uevent" 2>/dev/null; then
            BT_CONNECTED=true
            BT_MAC=$(grep "HID_UNIQ" "$uevent" 2>/dev/null | cut -d= -f2)
        fi
    fi
done

# Report status
echo ""
if $USB_CONNECTED; then
    echo -e "USB:       ${GREEN}Connected${NC}"
else
    echo -e "USB:       ${RED}Not connected${NC}"
fi

if $BT_CONNECTED; then
    echo -e "Bluetooth: ${GREEN}Connected${NC} ($BT_MAC)"
else
    echo -e "Bluetooth: ${RED}Not connected${NC}"
fi
echo ""

# Warn about dual connection
if $USB_CONNECTED && $BT_CONNECTED; then
    echo -e "${YELLOW}⚠ Both USB and Bluetooth are connected!${NC}"
    echo ""
    echo "This can cause issues. USB is preferred for full features (adaptive triggers)."
    echo ""
    read -p "Disconnect Bluetooth and use USB? [Y/n] " -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        echo "Disconnecting Bluetooth..."
        bluetoothctl disconnect "$BT_MAC" 2>/dev/null
        sleep 2

        # Verify disconnection
        BT_STILL=$(grep -l "HID_ID=0005" /sys/class/hidraw/hidraw*/device/uevent 2>/dev/null | xargs grep -l "054C" 2>/dev/null | xargs grep -l "0CE6" 2>/dev/null)
        if [ -z "$BT_STILL" ]; then
            echo -e "${GREEN}Bluetooth disconnected${NC}"
        else
            echo -e "${YELLOW}Bluetooth may still be connected. Try disconnecting manually.${NC}"
        fi
        echo ""
    fi
fi

# Check if no controller connected
if ! $USB_CONNECTED && ! $BT_CONNECTED; then
    echo -e "${RED}No DualSense controller detected!${NC}"
    echo "Please connect via USB or Bluetooth first."
    exit 1
fi

# Activate virtual environment and start
echo "Starting Web UI..."
source venv/bin/activate
python3 web_ui.py &
PID=$!

sleep 2

# Verify it started
if ps -p $PID > /dev/null 2>&1; then
    echo ""
    echo -e "${GREEN}DualSense Web UI started${NC} (PID: $PID)"
    echo ""
    echo "  Open in browser: http://localhost:5000"
    echo "  Stop with:       ./stop_webui.bash"
    echo ""

    # Show which mode will be used
    source venv/bin/activate
    python3 -c "
from dualsense import DualSense
ds = DualSense()
if ds.open():
    mode = ds.connection_type
    if mode in ('usb', 'usb_hidraw'):
        print('  Mode: USB (all features available)')
    elif mode == 'bluetooth_sysfs':
        print('  Mode: Bluetooth (adaptive triggers disabled)')
    else:
        print(f'  Mode: {mode}')
    ds.close()
" 2>/dev/null
else
    echo -e "${RED}Failed to start Web UI${NC}"
    exit 1
fi
