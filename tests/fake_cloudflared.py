"""假的 cloudflared：像真的一樣在 --metrics 的埠回答 /quicktunnel（網址）和 /ready（連上了），也把網址印到 stderr，
然後一直等到被關掉。對外連結現在是 CloudServicesPlatform 的 SDK（isdcsp.tunnel）在開，它跟真的 cloudflared 一樣看
metrics，所以這個假的也要回答 metrics。

FAKE_CF_MODE=die  → 連上之後 FAKE_CF_DIE_AFTER 秒（預設 1）就結束（模擬斷線）
FAKE_CF_MODE=exit → 一開始就失敗
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOSTNAME = "tidy-bird-sings-loud.trycloudflare.com"
mode = os.environ.get("FAKE_CF_MODE", "ok")
args = sys.argv[1:]
host, port = args[args.index("--metrics") + 1].rsplit(":", 1)

if mode == "exit":
    sys.stderr.write("2026-10-01T00:00:00Z ERR failed to request quick Tunnel: fake failure\n")
    sys.exit(1)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = {"/quicktunnel": {"hostname": HOSTNAME}, "/ready": {"readyConnections": 1}}.get(self.path)
        data = json.dumps(body or {}).encode()
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer((host, int(port)), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
sys.stderr.write("2026-10-01T00:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...\n")
sys.stderr.write(f"2026-10-01T00:00:01Z INF |  https://{HOSTNAME}  |\n")
sys.stderr.write("2026-10-01T00:00:02Z INF Registered tunnel connection connIndex=0 location=tpe01\n")
sys.stderr.flush()
if mode == "die":
    time.sleep(float(os.environ.get("FAKE_CF_DIE_AFTER", "1")))
    sys.exit(1)
while True:
    time.sleep(1)
