#!/bin/bash
# Start the 3-node swarm
# Run from Mac: ./scripts/start_swarm.sh
#
# Architecture:
#   Mac (M4 Max)     → Broker + Financial Node (MPS GPU)
#   TerrorNode (MSI) → Tech/Cyber Node (CUDA GPU)  
#   TowerSeven (Pi)  → Natural/Weather Node (CPU, tiny model)

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  DVCE DISTRIBUTED INTELLIGENCE SWARM                        ║"
echo "║  3-Node Proof of Concept                                    ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║                                                              ║"
echo "║  Node 1: MacBook M4 Max (Coordinator + Financial)           ║"
echo "║  Node 2: TerrorNode MSI (Tech/Cyber, CUDA)                  ║"
echo "║  Node 3: TowerSeven Pi  (Natural/Weather, Edge)             ║"
echo "║                                                              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Step 1: Start the broker on this machine (Mac)
echo "🌐 Starting Pattern Broker on localhost:9876..."
python3 src/swarm/broker.py --host 0.0.0.0 --port 9876 &
BROKER_PID=$!
echo "   Broker PID: $BROKER_PID"
sleep 2

# Step 2: Start local node (Mac = financial specialist)
echo "🧠 Starting local node (financial specialist, MPS)..."
cd src/node && python3 swarm_node.py --profile mac &
LOCAL_NODE_PID=$!
echo "   Local node PID: $LOCAL_NODE_PID"
cd ../..
sleep 1

# Step 3: Start remote nodes (if reachable)
echo ""
echo "📡 Remote nodes should be started manually:"
echo "   TerrorNode: python C:\\Users\\jwebb\\swarm\\swarm_node.py --profile terrornode"
echo "   TowerSeven: python3 /home/webber/swarm/swarm_node.py --profile towerseven"
echo ""
echo "─────────────────────────────────────────────────────────────"
echo "  Swarm is running. Press Ctrl+C to stop."
echo "─────────────────────────────────────────────────────────────"

# Wait for interrupt
trap "echo ''; echo 'Stopping swarm...'; kill $BROKER_PID $LOCAL_NODE_PID 2>/dev/null; echo 'Done.'" INT
wait
