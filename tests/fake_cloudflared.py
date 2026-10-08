"""假的 cloudflared：像真的一樣把網址和「連上了」印到 stderr，然後一直等到被關掉。
FAKE_CF_MODE=die → 印完網址就結束（模擬斷線）。"""

import os
import sys
import time

sys.stderr.write("2026-10-01T00:00:00Z INF Requesting new quick Tunnel on trycloudflare.com...\n")
sys.stderr.write("2026-10-01T00:00:01Z INF |  https://tidy-bird-sings-loud.trycloudflare.com  |\n")
sys.stderr.flush()
if os.environ.get("FAKE_CF_MODE") == "die":
    sys.exit(1)
time.sleep(0.2)
sys.stderr.write("2026-10-01T00:00:02Z INF Registered tunnel connection connIndex=0 location=tpe01\n")
sys.stderr.flush()
while True:
    time.sleep(1)
