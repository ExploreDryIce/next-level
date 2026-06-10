"""TerrorNode Web UI — Control TerrorNode from your browser.

Open: http://localhost:7778

Provides a simple web interface to:
- See TerrorNode status
- Send tasks (train, pull, shell, crawl)
- View results
- One-click common actions
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import httpx
import urllib.parse

TERRORNODE = "http://100.99.237.66:7777"
PORT = 7778

HTML = """<!DOCTYPE html>
<html>
<head>
    <title>TerrorNode Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, sans-serif; background: #0a0a0a; color: #e0e0e0; padding: 20px; }
        h1 { color: #00ff88; margin-bottom: 20px; font-size: 24px; }
        .status { background: #1a1a2e; padding: 15px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #333; }
        .status.online { border-color: #00ff88; }
        .status.offline { border-color: #ff4444; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 20px; }
        button { background: #1a1a2e; color: #00ff88; border: 1px solid #00ff88; padding: 12px 16px; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; }
        button:hover { background: #00ff88; color: #0a0a0a; }
        button.danger { border-color: #ff4444; color: #ff4444; }
        button.danger:hover { background: #ff4444; color: white; }
        input, textarea { background: #1a1a2e; color: #e0e0e0; border: 1px solid #333; padding: 10px; border-radius: 6px; width: 100%; font-family: monospace; margin-bottom: 10px; }
        textarea { height: 80px; resize: vertical; }
        .results { background: #0d0d1a; padding: 15px; border-radius: 8px; max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 12px; white-space: pre-wrap; border: 1px solid #222; }
        .result-item { padding: 8px; margin-bottom: 5px; border-left: 3px solid #333; }
        .result-item.completed { border-color: #00ff88; }
        .result-item.failed { border-color: #ff4444; }
        .section { margin-bottom: 25px; }
        .section h2 { color: #888; font-size: 14px; text-transform: uppercase; margin-bottom: 10px; }
        .inline { display: flex; gap: 10px; align-items: center; }
        #output { margin-top: 15px; }
    </style>
</head>
<body>
    <h1>🖥️ TerrorNode Control</h1>
    
    <div class="status" id="status-box">
        <strong>Status:</strong> <span id="status-text">Checking...</span><br>
        <strong>Queue:</strong> <span id="queue-text">-</span> | 
        <strong>Current:</strong> <span id="current-text">-</span>
    </div>

    <div class="section">
        <h2>Quick Actions</h2>
        <div class="grid">
            <button onclick="sendTask('report')">📊 Report</button>
            <button onclick="sendTask('pull')">🌐 Pull Data</button>
            <button onclick="sendTask('train', {script:'scripts/overnight_train.py'})">🧠 Train All</button>
            <button onclick="sendTask('train', {script:'scripts/terrornode_title_train.py'})">🏠 Train Title</button>
            <button onclick="sendTask('shell', {command:'nvidia-smi'})">🎮 GPU Status</button>
            <button onclick="sendTask('shell', {command:'dir E:\\\\unreal-projects\\\\dvce-visualizer'})">🎬 UE5 Check</button>
            <button onclick="sendTask('research')">🔍 Research</button>
            <button onclick="loadResults()">📋 Refresh Results</button>
        </div>
    </div>

    <div class="section">
        <h2>Shell Command</h2>
        <div class="inline">
            <input type="text" id="shell-cmd" placeholder="Enter command (e.g. nvidia-smi, dir, python -c ...)" onkeypress="if(event.key==='Enter')runShell()">
            <button onclick="runShell()">Run</button>
        </div>
    </div>

    <div class="section">
        <h2>Crawl URL</h2>
        <div class="inline">
            <input type="text" id="crawl-url" placeholder="https://..." onkeypress="if(event.key==='Enter')runCrawl()">
            <button onclick="runCrawl()">Crawl</button>
        </div>
    </div>

    <div class="section">
        <h2>Results</h2>
        <div class="results" id="results">Loading...</div>
    </div>

    <script>
        const API = '/api';
        
        async function checkStatus() {
            try {
                const r = await fetch(API + '/status');
                const d = await r.json();
                document.getElementById('status-text').textContent = d.agent || 'unknown';
                document.getElementById('queue-text').textContent = d.queue_length || 0;
                document.getElementById('current-text').textContent = d.current_task ? d.current_task.task_id : 'Idle';
                document.getElementById('status-box').className = 'status online';
            } catch(e) {
                document.getElementById('status-text').textContent = 'OFFLINE';
                document.getElementById('status-box').className = 'status offline';
            }
        }

        async function sendTask(action, params={}) {
            try {
                const r = await fetch(API + '/task', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action, params})
                });
                const d = await r.json();
                alert('Task queued: ' + d.task_id);
                setTimeout(loadResults, 3000);
            } catch(e) {
                alert('Error: ' + e.message);
            }
        }

        function runShell() {
            const cmd = document.getElementById('shell-cmd').value;
            if (cmd) sendTask('shell', {command: cmd});
        }

        function runCrawl() {
            const url = document.getElementById('crawl-url').value;
            if (url) sendTask('crawl', {url: url});
        }

        async function loadResults() {
            try {
                const r = await fetch(API + '/results');
                const results = await r.json();
                const el = document.getElementById('results');
                if (!results.length) { el.textContent = 'No results yet.'; return; }
                el.innerHTML = results.reverse().map(r => {
                    const cls = r.status === 'completed' ? 'completed' : 'failed';
                    const icon = r.status === 'completed' ? '✅' : '❌';
                    const result = (r.result || '').substring(0, 200);
                    return `<div class="result-item ${cls}">${icon} <b>${r.task_id}</b> (${r.completed_at || ''})<br>${result}</div>`;
                }).join('');
            } catch(e) {
                document.getElementById('results').textContent = 'Error loading results';
            }
        }

        checkStatus();
        loadResults();
        setInterval(checkStatus, 10000);
        setInterval(loadResults, 15000);
    </script>
</body>
</html>"""


class ProxyHandler(BaseHTTPRequestHandler):
    """Serves the UI and proxies API calls to TerrorNode."""

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path.startswith("/api/"):
            # Proxy to TerrorNode
            target = TERRORNODE + self.path[4:]  # Strip /api prefix
            try:
                r = httpx.get(target, timeout=10)
                self.send_response(r.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(r.content)
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/"):
            target = TERRORNODE + self.path[4:]
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                r = httpx.post(target, content=body, headers={"Content-Type": "application/json"}, timeout=10)
                self.send_response(r.status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(r.content)
            except Exception as e:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(f"🖥️  TerrorNode Control UI")
    print(f"   Open: http://localhost:{PORT}")
    print(f"   Proxying to: {TERRORNODE}")
    print()
    server = HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    server.serve_forever()
