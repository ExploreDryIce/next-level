#!/usr/bin/env python3
"""TerrorNode Command — Send tasks to TerrorNode from your Mac.

Usage:
    python src/agent/command.py status
    python src/agent/command.py train
    python src/agent/command.py train --script scripts/terrornode_title_train.py
    python src/agent/command.py pull
    python src/agent/command.py shell "nvidia-smi"
    python src/agent/command.py shell "dir E:\\unreal-projects"
    python src/agent/command.py crawl https://www.gsccca.org/search
    python src/agent/command.py report
    python src/agent/command.py research
    python src/agent/command.py results
"""

import sys
import json
import httpx

TERRORNODE_IP = "100.99.237.66"
AGENT_PORT = 7777
BASE_URL = f"http://{TERRORNODE_IP}:{AGENT_PORT}"


def send_task(action: str, params: dict = None, priority: int = 5):
    """Send a task to TerrorNode agent."""
    try:
        r = httpx.post(f"{BASE_URL}/task", json={
            "action": action,
            "params": params or {},
            "priority": priority,
        }, timeout=10)
        if r.status_code == 200:
            data = r.json()
            print(f"✅ Task queued: {data['task_id']}")
            return data
        else:
            print(f"❌ Error: HTTP {r.status_code}")
    except httpx.ConnectError:
        print("❌ TerrorNode agent not running. Start it with:")
        print("   ssh jwebb@100.99.237.66 'python C:\\Users\\jwebb\\Desktop\\next-level\\src\\agent\\worker.py'")
    except Exception as e:
        print(f"❌ Error: {e}")


def get_status():
    """Get TerrorNode agent status."""
    try:
        r = httpx.get(f"{BASE_URL}/status", timeout=5)
        if r.status_code == 200:
            data = r.json()
            print("🖥️  TerrorNode Agent")
            print(f"   Status: {data['agent']}")
            print(f"   Queue: {data['queue_length']} tasks")
            if data.get("current_task"):
                print(f"   Working on: {data['current_task']['task_id']}")
            else:
                print("   Idle — ready for tasks")
            return data
        else:
            print(f"❌ HTTP {r.status_code}")
    except httpx.ConnectError:
        print("❌ TerrorNode agent not running")
    except Exception as e:
        print(f"❌ {e}")


def get_results():
    """Get recent task results."""
    try:
        r = httpx.get(f"{BASE_URL}/results", timeout=5)
        if r.status_code == 200:
            results = r.json()
            if not results:
                print("No results yet.")
                return
            print(f"📋 Last {len(results)} results:")
            for res in results[-10:]:
                status_icon = "✅" if res["status"] == "completed" else "❌"
                result_preview = str(res.get("result", ""))[:60]
                print(f"   {status_icon} {res['task_id']} → {result_preview}")
    except httpx.ConnectError:
        print("❌ TerrorNode agent not running")
    except Exception as e:
        print(f"❌ {e}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]

    if cmd == "status":
        get_status()

    elif cmd == "results":
        get_results()

    elif cmd == "train":
        script = "scripts/overnight_train.py"
        if "--script" in sys.argv:
            idx = sys.argv.index("--script")
            script = sys.argv[idx + 1]
        send_task("train", {"script": script}, priority=3)

    elif cmd == "pull":
        send_task("pull", {"script": "scripts/us_weather_pull.py"}, priority=4)

    elif cmd == "shell":
        if len(sys.argv) > 2:
            command = " ".join(sys.argv[2:])
        else:
            command = input("Command: ")
        send_task("shell", {"command": command}, priority=5)

    elif cmd == "crawl":
        url = sys.argv[2] if len(sys.argv) > 2 else input("URL: ")
        send_task("crawl", {"url": url}, priority=5)

    elif cmd == "report":
        send_task("report", priority=1)

    elif cmd == "research":
        topic = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        send_task("research", {"topic": topic}, priority=6)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
