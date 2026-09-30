"""資料放在哪裡。

預設是專案根目錄底下的 data/；設定環境變數 WORSHIP_PPT_HOME 可以整個搬到別處（測試也用這個）。

    data/
      worship.db        歌詞庫、歌單、背景、排版、匯出紀錄（SQLite）
      images/           背景圖（依內容 hash 命名，同一張圖只存一份）
      images/thumbs/    縮圖（刪掉會自動重做）
      exports/          每一次匯出的 .pptx（紀錄頁可以再下載）
      logs/             執行紀錄
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HOME_ENV = "WORSHIP_PPT_HOME"


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def discover(cls) -> "Paths":
        env = os.environ.get(HOME_ENV, "").strip()
        return cls(Path(env).resolve() if env else _repo_root())

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def db_file(self) -> Path:
        return self.data_dir / "worship.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def thumbs_dir(self) -> Path:
        return self.images_dir / "thumbs"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def legacy_file(self) -> Path:
        """桌面版（legacy/desktop/main.py）的存檔：「匯入桌面版存檔」預設讀這個。"""
        return self.root / "legacy" / "desktop" / "ppt_settings.json"

    def ensure(self) -> None:
        for d in (self.data_dir, self.images_dir, self.thumbs_dir, self.exports_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
