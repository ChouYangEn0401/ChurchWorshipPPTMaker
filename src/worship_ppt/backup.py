"""備份：把資料庫、背景圖、匯出過的 PPT 打包成一個 zip，放在專案旁邊的 backups/ 資料夾。

資料庫用 SQLite 的線上備份（伺服器開著也能安全備份）。還原方式寫在 zip 裡的「還原說明.txt」。
"""

from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .paths import Paths

RESTORE_NOTE = """還原方式：
1. 先關掉敬拜 PPT 產生器（關掉黑色視窗）。
2. 把專案資料夾裡的 data 資料夾改名（例如 data.old），留著以防萬一。
3. 把這個 zip 裡的 data 資料夾整個解壓縮到專案資料夾。
4. 重新開啟（雙擊 scripts\\windows\\2-start.bat）。
"""


def run_backup(paths: Paths) -> Path:
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = paths.backups_dir / f"worship-ppt-{stamp}.zip"
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "worship.db"
        src = sqlite3.connect(paths.db_file)
        try:
            dst = sqlite3.connect(db_copy)
            try:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
            finally:
                dst.close()
        finally:
            src.close()
        partial = dest.with_suffix(".zip.part")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("還原說明.txt", RESTORE_NOTE)
            zf.write(db_copy, "data/worship.db")
            for folder in (paths.images_dir, paths.exports_dir):
                for file in sorted(folder.rglob("*")):
                    if file.is_file() and "thumbs" not in file.parts and not file.name.endswith(".tmp"):
                        zf.write(file, file.relative_to(paths.root).as_posix(), compress_type=zipfile.ZIP_STORED)
        partial.replace(dest)
    return dest
