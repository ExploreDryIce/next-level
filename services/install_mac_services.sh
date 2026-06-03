#!/bin/bash
# Install DVCE swarm services on Mac (launchd)
# These run as background daemons — start on boot, restart if they crash

set -e

echo "=== Installing DVCE Swarm Services ==="

# Create log directory
mkdir -p ~/.dvce/logs

# Copy plist files to LaunchAgents
cp services/com.dvce.broker.plist ~/Library/LaunchAgents/
cp services/com.dvce.node.plist ~/Library/LaunchAgents/

# Load them (starts immediately + will start on next boot)
launchctl load ~/Library/LaunchAgents/com.dvce.broker.plist
echo "✅ Broker service installed and started"

# Wait for broker to be ready
sleep 2

launchctl load ~/Library/LaunchAgents/com.dvce.node.plist
echo "✅ Node service installed and started"

echo ""
echo "Services running:"
echo "  • com.dvce.broker (Pattern Broker on :9876)"
echo "  • com.dvce.node   (Financial specialist, MPS)"
echo ""
echo "Logs at: ~/.dvce/logs/"
echo ""
echo "Commands:"
echo "  Stop:    launchctl unload ~/Library/LaunchAgents/com.dvce.broker.plist"
echo "  Start:   launchctl load ~/Library/LaunchAgents/com.dvce.broker.plist"
echo "  Status:  launchctl list | grep dvce"
echo "  Logs:    tail -f ~/.dvce/logs/broker.log"
