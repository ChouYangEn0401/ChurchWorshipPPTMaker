"""敬拜 PPT 產生器（網頁版）的入口。

    雙擊 run.bat                  打開網頁（第一次會自動安裝）
    雙擊 run_public.bat           打開網頁 ＋ Cloudflare 對外連結

    python main.py                打開網頁（http://127.0.0.1:8788）
    python main.py web --public   打開網頁，同時開 Cloudflare 對外連結
    python main.py import-gdoc    從 Google 文件匯入這週歌單
    python main.py --help         其他指令

用哪個 Python 跑都可以：缺套件時會自動改用專案裡的 .venv；還沒安裝的話會告訴你怎麼裝。
程式本體在 src/worship_ppt/。
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REQUIRED = ("fastapi", "uvicorn", "jinja2", "multipart", "httpx", "pptx", "PIL", "lxml", "qrcode", "isdcsp")


def _venv_python() -> Path:
    return ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _missing() -> list[str]:
    return [name for name in REQUIRED if importlib.util.find_spec(name) is None]


if __name__ == "__main__":
    if _missing():
        venv = _venv_python()
        if venv.exists() and Path(sys.executable).resolve() != venv.resolve():
            # 這個 Python 沒裝套件，改用專案的 .venv 重跑一次
            raise SystemExit(subprocess.call([str(venv), str(Path(__file__).resolve()), *sys.argv[1:]]))
        print("還沒安裝需要的套件：" + "、".join(_missing()))
        print("請先雙擊 run.bat（會自動安裝），或 scripts\\windows\\1-install.bat。")
        raise SystemExit(1)
    sys.path.insert(0, str(ROOT / "src"))
    os.environ.setdefault("PYTHONUTF8", "1")
    from worship_ppt.cli import main

    raise SystemExit(main())
