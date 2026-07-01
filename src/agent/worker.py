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
        """Crawl a URL with playwright (JS-rendered) or httpx (simple).

        Params:
            url: Target URL (required)
            mode: "full" (playwright, default) | "simple" (httpx only)
            wait_for: CSS selector to wait for before extracting (optional)
            extract: "text" (default) | "html" | "links" | "tables"
            screenshot: True/False — save screenshot to data/crawl_screenshots/
            timeout: Page load timeout in ms (default 30000)
        """
        url = params.get("url", "")
        if not url:
            return "No URL provided"

        mode = params.get("mode", "full")
        extract = params.get("extract", "text")
        wait_for = params.get("wait_for", "")
        take_screenshot = params.get("screenshot", False)
        timeout = params.get("timeout", 30000)

        if mode == "simple":
            # Fast path — no browser needed
            import httpx
            try:
                r = httpx.get(url, timeout=30, follow_redirects=True,
                              headers={"User-Agent": "DVCE-Swarm/1.0"})
                return f"Status: {r.status_code}, Size: {len(r.content)}\n\n{r.text[:2000]}"
            except Exception as e:
                return f"Simple crawl failed: {e}"

        # Full playwright crawl
        script = f'''
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def crawl():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            await page.goto("{url}", wait_until="networkidle", timeout={timeout})
        except Exception as e:
            await page.goto("{url}", wait_until="domcontentloaded", timeout={timeout})

        if "{wait_for}":
            try:
                await page.wait_for_selector("{wait_for}", timeout=10000)
            except:
                pass

        result = {{}}
        result["url"] = page.url
        result["title"] = await page.title()

        extract_mode = "{extract}"
        if extract_mode == "text":
            result["content"] = (await page.inner_text("body"))[:5000]
        elif extract_mode == "html":
            result["content"] = (await page.content())[:10000]
        elif extract_mode == "links":
            links = await page.eval_on_selector_all("a[href]",
                "els => els.map(e => ({{text: e.innerText.trim().slice(0,80), href: e.href}})).filter(l => l.text && l.href.startsWith('http')).slice(0, 50)")
            result["content"] = json.dumps(links, indent=2)
        elif extract_mode == "tables":
            tables = await page.eval_on_selector_all("table",
                "els => els.map(t => ({{rows: t.rows.length, headers: Array.from(t.querySelectorAll('th')).map(h => h.innerText.trim())}})).slice(0, 10)")
            result["content"] = json.dumps(tables, indent=2)

        screenshot_taken = False
        if {take_screenshot}:
            ss_dir = Path("data/crawl_screenshots")
            ss_dir.mkdir(parents=True, exist_ok=True)
            import time
            ss_path = ss_dir / f"crawl_{{int(time.time())}}.png"
            await page.screenshot(path=str(ss_path), full_page=True)
            result["screenshot"] = str(ss_path)
            screenshot_taken = True

        await browser.close()
        print(json.dumps(result))

asyncio.run(crawl())
'''
        result = subprocess.run(
            ["python", "-c", script],
            capture_output=True, text=True,
            cwd=str(BASE_DIR), timeout=90
        )

        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout.strip())
                output = f"Title: {data.get('title', '?')}\nURL: {data.get('url', url)}\n"
                if data.get("screenshot"):
                    output += f"Screenshot: {data['screenshot']}\n"
                output += f"\n{data.get('content', '')[:3000]}"
                return output
            except json.JSONDecodeError:
                return result.stdout[:2000]
        else:
            error = result.stderr[-500:] if result.stderr else "Unknown error"
            # Fallback to simple httpx if playwright fails
            import httpx
            try:
                r = httpx.get(url, timeout=30, follow_redirects=True)
                return f"[Playwright failed, httpx fallback] Status: {r.status_code}\n{r.text[:1500]}\n\nPlaywright error: {error[:200]}"
            except:
                return f"Crawl failed completely. Playwright error: {error}"

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
        """Deep research on a topic using playwright + multiple sources.

        Params:
            topic: What to research (required)
            sources: List of URLs to check (optional, defaults to news/search)
            depth: "shallow" (headlines only) | "deep" (follow links, extract content)
            max_pages: Max pages to visit (default 5)
        """
        topic = params.get("topic", "")
        if not topic:
            return "No topic provided"

        sources = params.get("sources", [])
        depth = params.get("depth", "shallow")
        max_pages = params.get("max_pages", 5)

        # Default sources if none provided
        if not sources:
            safe_topic = topic.replace('"', '').replace("'", "")
            sources = [
                f"https://news.google.com/search?q={safe_topic.replace(' ', '%20')}&hl=en-US",
                f"https://www.reuters.com/search/news?query={safe_topic.replace(' ', '+')}",
                f"https://hacker-news.firebaseio.com/v0/topstories.json",
            ]

        script = f'''
import asyncio
import json
from playwright.async_api import async_playwright

async def research():
    findings = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        sources = {json.dumps(sources)}
        max_pages = {max_pages}
        visited = 0

        for url in sources:
            if visited >= max_pages:
                break

            # Skip HN API (handle separately)
            if "firebaseio" in url:
                import httpx
                try:
                    r = httpx.get(url, timeout=10)
                    story_ids = r.json()[:5]
                    for sid in story_ids:
                        r2 = httpx.get(f"https://hacker-news.firebaseio.com/v0/item/{{sid}}.json", timeout=5)
                        item = r2.json()
                        findings.append({{
                            "source": "hackernews",
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "score": item.get("score", 0),
                        }})
                except:
                    pass
                visited += 1
                continue

            try:
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(2)

                # Extract headlines and links
                items = await page.eval_on_selector_all(
                    "article a, h2 a, h3 a, .story a, .article-title a, [data-testid] a",
                    "els => els.map(e => ({{title: e.innerText.trim(), href: e.href}})).filter(l => l.title.length > 10 && l.href.startsWith('http')).slice(0, 10)"
                )

                if not items:
                    # Fallback: get all meaningful links
                    items = await page.eval_on_selector_all(
                        "a[href]",
                        "els => els.map(e => ({{title: e.innerText.trim(), href: e.href}})).filter(l => l.title.length > 20 && l.href.startsWith('http') && !l.href.includes('login') && !l.href.includes('sign')).slice(0, 10)"
                    )

                for item in items:
                    findings.append({{
                        "source": url.split("/")[2],
                        "title": item["title"][:120],
                        "url": item["href"],
                    }})

                await page.close()
                visited += 1

            except Exception as e:
                findings.append({{"source": url, "error": str(e)[:100]}})
                visited += 1

        # Deep mode: follow top links and extract content
        if "{depth}" == "deep" and findings:
            deep_results = []
            for item in findings[:3]:  # Follow top 3
                if "url" not in item or "error" in item:
                    continue
                try:
                    page = await context.new_page()
                    await page.goto(item["url"], wait_until="domcontentloaded", timeout=15000)
                    text = (await page.inner_text("article")) if await page.query_selector("article") else (await page.inner_text("body"))
                    item["content_preview"] = text[:500]
                    deep_results.append(item)
                    await page.close()
                except:
                    pass

            if deep_results:
                findings = deep_results + [f for f in findings if f not in deep_results]

        await browser.close()

    print(json.dumps(findings, indent=2))

asyncio.run(research())
'''
        result = subprocess.run(
            ["python", "-c", script],
            capture_output=True, text=True,
            cwd=str(BASE_DIR), timeout=120
        )

        if result.returncode == 0 and result.stdout.strip():
            try:
                findings = json.loads(result.stdout.strip())
                output = f"Research: {topic}\nSources checked: {len(sources)}\nFindings: {len(findings)}\n\n"
                for i, f in enumerate(findings[:15], 1):
                    if "error" in f:
                        output += f"  {i}. [ERROR] {f['source']}: {f['error']}\n"
                    else:
                        output += f"  {i}. [{f.get('source', '?')}] {f.get('title', '?')}\n"
                        if f.get("url"):
                            output += f"     {f['url']}\n"
                        if f.get("content_preview"):
                            output += f"     Preview: {f['content_preview'][:150]}...\n"
                return output
            except json.JSONDecodeError:
                return result.stdout[:2000]
        else:
            # Fallback to simple HN research
            import httpx
            try:
                r = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10)
                stories = r.json()[:5]
                details = []
                for story_id in stories:
                    r2 = httpx.get(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=5)
                    item = r2.json()
                    details.append(f"- {item.get('title', '?')} ({item.get('url', 'no url')})")
                return f"[Playwright failed, HN fallback]\nTop stories:\n" + "\n".join(details)
            except Exception as e:
                return f"Research failed: {e}\nPlaywright stderr: {result.stderr[-300:]}"

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
