#!/bin/bash
#
# Stop DualSense Web UI
#

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PID=$(pgrep -f "python3 web_ui.py")

if [ -z "$PID" ]; then
    echo -e "${YELLOW}Web UI is not running${NC}"
    exit 0
fi

echo "Stopping Web UI (PID: $PID)..."
kill $PID 2>/dev/null

# Wait for graceful shutdown
sleep 1

# Force kill if still running
if ps -p $PID > /dev/null 2>&1; then
    echo "Force killing..."
    kill -9 $PID 2>/dev/null
    sleep 1
fi

if ps -p $PID > /dev/null 2>&1; then
    echo -e "${RED}Failed to stop Web UI${NC}"
    exit 1
else
    echo -e "${GREEN}Web UI stopped${NC}"
fi
