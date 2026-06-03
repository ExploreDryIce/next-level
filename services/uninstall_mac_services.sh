#!/bin/bash
# Uninstall DVCE swarm services from Mac
# Stops the services and removes them from auto-start

echo "=== Removing DVCE Swarm Services ==="

launchctl unload ~/Library/LaunchAgents/com.dvce.broker.plist 2>/dev/null && echo "✅ Broker stopped" || echo "⚠️  Broker wasn't running"
launchctl unload ~/Library/LaunchAgents/com.dvce.node.plist 2>/dev/null && echo "✅ Node stopped" || echo "⚠️  Node wasn't running"

rm -f ~/Library/LaunchAgents/com.dvce.broker.plist
rm -f ~/Library/LaunchAgents/com.dvce.node.plist

echo ""
echo "Services removed. They will NOT start on next boot."
echo "Logs still at ~/.dvce/logs/ (delete manually if desired)"
