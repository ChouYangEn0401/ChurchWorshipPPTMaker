"""
啟動網頁版：跑起本機伺服器並自動打開瀏覽器。

    python run_web.py

預設在 http://127.0.0.1:8000 ，只綁在本機，不會對外開放。
"""

import threading
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 8000


def _open_browser():
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    threading.Timer(1.2, _open_browser).start()
    uvicorn.run("webapp.server:app", host=HOST, port=PORT, reload=False)
