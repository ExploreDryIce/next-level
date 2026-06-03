#!/bin/bash
# Deploy swarm node to TerrorNode (MSI GP63 - Windows)
# Run from Mac: ./scripts/deploy_terrornode.sh

set -e

REMOTE_USER="jwebber533@gmail.com"
REMOTE_HOST="100.99.237.66"
REMOTE_DIR="C:/Users/jwebb/swarm"
PASSWORD="3614"

echo "=== Deploying to TerrorNode ==="

# Copy swarm node code
echo "📦 Copying node code..."
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no -r \
    src/node/config.py \
    src/node/swarm_node.py \
    src/node/network.py \
    "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/"

# Copy vocab and expertise scores
echo "📦 Copying model assets..."
sshpass -p "$PASSWORD" scp -o StrictHostKeyChecking=no \
    experiments/models/vocab.json \
    experiments/models/expertise_scores.json \
    "$REMOTE_USER@$REMOTE_HOST:$REMOTE_DIR/models/"

# Install Python dependencies
echo "📦 Installing dependencies..."
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no \
    "$REMOTE_USER@$REMOTE_HOST" \
    "python -m pip install numpy nats-py --quiet"

echo "✅ TerrorNode deployment complete!"
echo "   Run on TerrorNode: python C:\\Users\\jwebb\\swarm\\swarm_node.py --profile terrornode"
