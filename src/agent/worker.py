"""TerrorNode Autonomous Agent — picks up tasks and executes them.

Runs as a persistent loop on the MSI. Checks for tasks from:
1. Local task queue file (tasks.json)
2. HTTP endpoint (so Mac can POST tasks)
3. Scheduled recurring tasks

Capabilities:
- train: Run any training script
- pull: Pull data from APIs
- crawl: Scrape a URL or county recorder
- shell: Execute arbitrary commands
- report: Generate and send a status report

Run:
    python src/agent/worker.py

Or as a service (Windows):
    schtasks /create /tn "DVCE-Agent" /tr "python C:\path\to\worker.py" /sc onstart
"""

import json
import time
import subprocess
import logging
import threading
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AGENT] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
TASK_FILE = BASE_DIR / "data" / "agent_tasks" / "queue.json"
RESULTS_FILE = BASE_DIR / "data" / "agent_tasks" / "results.json"
LOG_FILE = BASE_DIR / "logs" / "agent.log"

TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

# HTTP port for receiving tasks from Mac
AGENT_PORT = 7777


class Task:
    def __init__(self, task_id: str, action: str, params: dict = None,
                 priority: int = 5, created_at: str = None):
        self.task_id = task_id
        self.action = action
        self.params = params or {}
        self.priority = priority
        self.created_at = created_at or datetime.now().isoformat()
        self.status = "pending"
        self.result = None
        self.completed_at = None

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "action": self.action,
            "params": self.params,
            "priority": self.priority,
            "created_at": self.created_at,
            "status": self.status,
            "result": self.result,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data):
        t = cls(data["task_id"], data["action"], data.get("params", {}),
                data.get("priority", 5), data.get("created_at"))
        t.status = data.get("status", "pending")
        t.result = data.get("result")
        t.completed_at = data.get("completed_at")
        return t


class AgentWorker:
    def __init__(self):
        self.queue: list = []
        self.results: list = []
        self.running = True
        self.current_task: Optional[Task] = None
        self._load_queue()

    def _load_queue(self):
        if TASK_FILE.exists():
            try:
                data = json.loads(TASK_FILE.read_text())
                self.queue = [Task.from_dict(t) for t in data if t.get("status") == "pending"]
            except:
                self.queue = []

    def _save_queue(self):
        TASK_FILE.write_text(json.dumps([t.to_dict() for t in self.queue], indent=2))

    def _save_results(self, task: Task):
        results = []
        if RESULTS_FILE.exists():
            try:
                results = json.loads(RESULTS_FILE.read_text())
            except:
                pass
        results.append(task.to_dict())
        # Keep last 100 results
        RESULTS_FILE.write_text(json.dumps(results[-100:], indent=2))

    def add_task(self, action: str, params: dict = None, priority: int = 5) -> str:
        task_id = f"{action}_{int(time.time())}"
        task = Task(task_id, action, params or {}, priority)
        self.queue.append(task)
        self.queue.sort(key=lambda t: t.priority)
        self._save_queue()
        logger.info(f"Task added: {task_id} (priority {priority})")
        return task_id

    def execute_task(self, task: Task):
        """Execute a single task based on its action type."""
        self.current_task = task
        task.status = "running"
        logger.info(f"Executing: {task.task_id} ({task.action})")

        try:
            if task.action == "train":
                result = self._do_train(task.params)
            elif task.action == "pull":
                result = self._do_pull(task.params)
            elif task.action == "shell":
                result = self._do_shell(task.params)
            elif task.action == "crawl":
                result = self._do_crawl(task.params)
            elif task.action == "report":
                result = self._do_report(task.params)
            elif task.action == "research":
                result = self._do_research(task.params)
            else:
                result = f"Unknown action: {task.action}"

            task.status = "completed"
            task.result = result
        except Exception as e:
            task.status = "failed"
            task.result = str(e)
            logger.error(f"Task failed: {task.task_id} — {e}")

        task.completed_at = datetime.now().isoformat()
        self._save_results(task)
        self.current_task = None
        logger.info(f"Done: {task.task_id} → {task.status}")

    def _do_train(self, params: dict) -> str:
        script = params.get("script", "scripts/overnight_train.py")
        env_vars = f"set PYTHONPATH=C:\\Users\\jwebb\\Desktop\\dvce\\src && "
        cmd = f"{env_vars}python {script}"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               cwd=str(BASE_DIR), timeout=3600)
        return result.stdout[-500:] if result.stdout else result.stderr[-500:]

    def _do_pull(self, params: dict) -> str:
        script = params.get("script", "scripts/us_weather_pull.py")
        result = subprocess.run(f"python {script}", shell=True, capture_output=True,
                               text=True, cwd=str(BASE_DIR), timeout=600)
        return result.stdout[-500:] if result.stdout else result.stderr[-500:]

    def _do_shell(self, params: dict) -> str:
        cmd = params.get("command", "echo no command")
        timeout = params.get("timeout", 300)
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               cwd=str(BASE_DIR), timeout=timeout)
        output = result.stdout + result.stderr
        return output[-1000:]

    def _do_crawl(self, params: dict) -> str:
        url = params.get("url", "")
        if not url:
            return "No URL provided"
        cmd = f'python -c "import httpx; r=httpx.get(\'{url}\', timeout=30); print(f\'Status: {{r.status_code}}, Size: {{len(r.content)}}\')"'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                               cwd=str(BASE_DIR), timeout=60)
        return result.stdout[-500:] if result.stdout else result.stderr[-500:]

    def _do_report(self, params: dict) -> str:
        import platform
        try:
            gpu_info = subprocess.run("nvidia-smi --query-gpu=name,memory.used,memory.total,temperature.gpu --format=csv,noheader",
                                     shell=True, capture_output=True, text=True, timeout=10)
            gpu = gpu_info.stdout.strip()
        except:
            gpu = "unavailable"

        report = {
            "timestamp": datetime.now().isoformat(),
            "hostname": platform.node(),
            "gpu": gpu,
            "queue_length": len(self.queue),
            "current_task": self.current_task.task_id if self.current_task else None,
            "tasks_completed_today": sum(1 for r in self.results
                                        if r.get("completed_at", "").startswith(datetime.now().strftime("%Y-%m-%d"))),
        }
        return json.dumps(report, indent=2)

    def _do_research(self, params: dict) -> str:
        topic = params.get("topic", "")
        # Simple: pull from a search-related API
        import httpx
        try:
            r = httpx.get(f"https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10)
            stories = r.json()[:5]
            details = []
            for story_id in stories:
                r2 = httpx.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=5)
                item = r2.json()
                details.append(f"- {item.get('title', '?')} ({item.get('url', 'no url')})")
            return f"Top HN stories:\n" + "\n".join(details)
        except Exception as e:
            return f"Research failed: {e}"

    def run(self):
        """Main agent loop."""
        logger.info("=" * 50)
        logger.info("TERRORNODE AGENT STARTED")
        logger.info(f"  Queue file: {TASK_FILE}")
        logger.info(f"  HTTP port: {AGENT_PORT}")
        logger.info("=" * 50)

        # Start HTTP server in background thread
        server_thread = threading.Thread(target=self._run_http_server, daemon=True)
        server_thread.start()

        while self.running:
            # Check for tasks
            self._load_queue()

            if self.queue:
                task = self.queue.pop(0)
                self._save_queue()
                self.execute_task(task)
            else:
                time.sleep(10)  # Check every 10 seconds

    def _run_http_server(self):
        """HTTP server for receiving tasks from Mac."""
        agent = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path == "/task":
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length))
                    task_id = agent.add_task(
                        action=body.get("action", "shell"),
                        params=body.get("params", {}),
                        priority=body.get("priority", 5),
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"task_id": task_id, "status": "queued"}).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_GET(self):
                if self.path == "/status":
                    status = {
                        "agent": "running",
                        "queue_length": len(agent.queue),
                        "current_task": agent.current_task.to_dict() if agent.current_task else None,
                        "timestamp": datetime.now().isoformat(),
                    }
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(status, indent=2).encode())
                elif self.path == "/results":
                    results = []
                    if RESULTS_FILE.exists():
                        results = json.loads(RESULTS_FILE.read_text())
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(results[-20:], indent=2).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass  # Suppress HTTP logs

        server = HTTPServer(("0.0.0.0", AGENT_PORT), Handler)
        logger.info(f"HTTP server listening on port {AGENT_PORT}")
        server.serve_forever()


if __name__ == "__main__":
    agent = AgentWorker()
    agent.run()
