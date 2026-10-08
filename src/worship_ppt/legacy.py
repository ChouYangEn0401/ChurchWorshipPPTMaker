"""匯入桌面版（legacy/desktop/main.py）的存檔，背景圖也一起搬進背景庫。

支援兩種舊格式：
  A. 桌面版「儲存專案」的 ppt_settings.json：
     {"songs":[{title, lyrics:"[Verse]\\n...", background, lyrics_left, lyrics_top, styles:{Title,Segment,Lyrics}}]}
  B. 更舊的 songs.json：
     {"slidesize":"16:9","songs":[{title, background, font:{name,size,color}, lyrics:["第一頁\\n第二行", ...]}]}

匯入後：每首歌進詩歌庫（同名的會更新）、每張背景圖變成一個背景、
字型設定整理成排版（一樣的設定只做一個），再建一份「桌面版匯入」的歌單，可以直接匯出看看。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import store
from .db import Database
from .errors import AppError
from .paths import Paths
from .styles import DEFAULT_FONT, clean_style


def _part(src: dict | None, size: float, color: str, bold: bool = False) -> dict:
    src = src or {}
    return {"font": src.get("font") or DEFAULT_FONT, "size": src.get("size", size),
            "color": src.get("color", color), "bold": bool(src.get("bold", bold)), "shadow": False}


def _is_format_b(data: dict) -> bool:
    if "slidesize" in data or "output" in data:
        return True
    return any(isinstance(s.get("lyrics"), list) or isinstance(s.get("font"), dict) for s in data.get("songs", []))


def import_file(db: Database, paths: Paths, legacy_path: str | Path, by: str = "") -> dict:
    legacy_path = Path(legacy_path)
    try:
        data = json.loads(legacy_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise AppError(f"找不到檔案：{legacy_path}", "請確認路徑。桌面版的範例存檔在專案資料夾的 legacy/desktop/ppt_settings.json。", status=404)
    except (OSError, ValueError) as exc:
        raise AppError(f"讀不懂這個檔案：{exc}", "要選桌面版「儲存專案」存出來的 .json 檔。")
    if not isinstance(data, dict) or not isinstance(data.get("songs"), list):
        raise AppError("這不是桌面版的存檔（裡面沒有 songs）")

    base_dir = legacy_path.resolve().parent
    fmt_b = _is_format_b(data)
    slide_size = data.get("slidesize", "4:3") if fmt_b else "4:3"
    if slide_size not in store.SLIDE_SIZES:
        slide_size = "4:3"

    theme_cache: dict[str, int | None] = {}
    style_cache: dict[str, int] = {}
    missing_images: list[str] = []

    def theme_for(background: str) -> int | None:
        if not background:
            return None
        if background in theme_cache:
            return theme_cache[background]
        src = Path(background)
        candidates = [src] if src.is_absolute() else []
        candidates += [base_dir / src.name, base_dir / background]
        for cand in candidates:
            if cand.exists():
                theme = store.add_image(db, paths, cand.read_bytes(), cand.name, by)
                theme_cache[background] = theme["id"]
                return theme["id"]
        missing_images.append(src.name)
        theme_cache[background] = None
        return None

    def style_for(style: dict) -> int:
        body = clean_style(style)
        key = json.dumps(body, sort_keys=True, ensure_ascii=False)
        if key not in style_cache:
            created = store.create_style(db, {**body, "name": f"桌面版樣式 {len(style_cache) + 1}"})
            style_cache[key] = created["id"]
        return style_cache[key]

    service = store.create_service(db, {"date": date.today().isoformat(), "name": "桌面版匯入",
                                        "slideSize": slide_size, "followSequence": False}, by)
    report = []
    for song in data["songs"]:
        title = str(song.get("title") or "").strip() or "未命名"
        if fmt_b:
            font = song.get("font") or {}
            fname = font.get("name") or DEFAULT_FONT
            style = {
                "title": {"font": fname, "size": 60, "color": "#FFD700", "bold": True, "shadow": False},
                "segment": {"font": fname, "size": 30, "color": "#FF4500", "bold": False, "shadow": False},
                "lyrics": {"font": fname, "size": font.get("size", 60), "color": font.get("color", "#FFFFFF"),
                           "bold": False, "shadow": False},
                "showHeader": False, "lyricsLeft": 0.05, "lyricsTop": 1.8,
            }
            pages = song.get("lyrics") or []
            lyrics = pages if isinstance(pages, str) else "\n\n".join(str(p) for p in pages)
        else:
            styles = song.get("styles") or {}
            style = {
                "title": _part(styles.get("Title"), 60, "#FFD700", True),
                "segment": _part(styles.get("Segment"), 30, "#FF4500"),
                "lyrics": _part(styles.get("Lyrics"), 52, "#FFFFFF"),
                "showHeader": True, "headerTop": 0.4,
                "lyricsLeft": song.get("lyrics_left", 0.05), "lyricsTop": song.get("lyrics_top", 1.8),
            }
            lyrics = str(song.get("lyrics") or "")
        theme_id = theme_for(str(song.get("background") or ""))
        style_id = style_for(style)
        existing = store.find_song(db, title)
        fields = {"title": title, "lyrics": lyrics, "themeId": theme_id, "styleId": style_id}
        if existing:
            store.update_song(db, existing["id"], fields, by, reason="從桌面版存檔匯入")
            song_id = existing["id"]
        else:
            song_id = store.create_song(db, fields, by)["id"]
        store.add_item(db, service["id"], {"songId": song_id}, by)
        report.append(title)

    return {"serviceId": service["id"], "songs": report, "missingImages": missing_images}
