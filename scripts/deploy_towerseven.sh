#!/bin/bash
# Deploy swarm node to TowerSeven (Raspberry Pi 3)
# Run from Mac: ./scripts/deploy_towerseven.sh
#
# NOTE: Pi 3 has 1GB RAM. We use the TINY model (156K params, ~50MB RAM).
# No GPU — CPU-only inference. Still useful for anomaly detection and 
# pattern observation in the "natural" domain (weather, earthquakes, etc.)
#
# Prerequisites on Pi:
#   - Python 3 installed (comes with Raspberry Pi OS)
#   - pip installed: sudo apt install python3-pip
#   - PyTorch for ARM: pip3 install torch --index-url https://download.pytorch.org/whl/cpu

set -e

REMOTE_USER="webber"
REMOTE_HOST="TowerSeven.local"  # or 192.168.1.222
REMOTE_DIR="/home/webber/swarm"

echo "=== Deploying to TowerSeven (Raspberry Pi 3) ==="

# Create remote directory
echo "📁 Creating swarm directory..."
ssh -o StrictHostKeyChecking=no "$REMOTE_USER@$REMOTE_HOST" \
    "mkdir -p $REMOTE_DIR/models $REMOTE_DIR/patterns $REMOTE_DIR/checkpoints"

# Copy swarm node code
echo "📦 Copying node code..."
scp -o StrictHostKeyChecking=no \
    src/node/config.py \
    src/node/swarm_node.py \
    src/node/network.py \
    "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

# Copy vocab and expertise scores
echo "📦 Copying model assets..."
scp -o StrictHostKeyChecking=no \
    experiments/models/vocab.json \
    experiments/models/expertise_scores.json \
    "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/models/"

# Install Python dependencies (minimal for Pi)
echo "📦 Installing dependencies..."
ssh -o StrictHostKeyChecking=no "$REMOTE_USER@$REMOTE_HOST" \
    "pip3 install numpy --quiet 2>/dev/null || sudo pip3 install numpy --quiet"

echo ""
echo "✅ TowerSeven deployment complete!"
echo ""
echo "⚠️  FIRST TIME SETUP (run on Pi once):"
echo "   sudo apt install python3-pip python3-dev -y"
echo "   pip3 install torch --index-url https://download.pytorch.org/whl/cpu"
echo ""
echo "   Then run:"
echo "   cd /home/webber/swarm && python3 swarm_node.py --profile towerseven"
echo ""
echo "   Memory usage will be ~50-100MB (tiny model on CPU)"
echo "   Pi has 1GB total — this leaves room for Pi-hole and other services"
