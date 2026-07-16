"""
檔案系統存取層：資料都放在 webapp/data/ 底下。

  data/
    uploads/        背景圖（上傳後改成 <hash>.<ext>）
    projects/       使用者存的專案（<名稱>.json）
    session.json    自動存檔（最後一次的完整狀態，重開瀏覽器會還原）
"""

import os
import re
import json
import shutil
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
SESSION_PATH = os.path.join(DATA_DIR, "session.json")

_ALLOWED_IMG = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def ensure_dirs():
    for d in (DATA_DIR, UPLOADS_DIR, PROJECTS_DIR):
        os.makedirs(d, exist_ok=True)


def _safe_name(name):
    """把使用者輸入的專案名轉成安全檔名。"""
    name = (name or "").strip() or "未命名專案"
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name[:100]


def save_upload_bytes(data, original_name):
    """把上傳的圖片位元組存起來，回傳可供瀏覽器讀取的檔名。
    以內容 hash 命名，同一張圖不會重複存。"""
    ensure_dirs()
    ext = os.path.splitext(original_name or "")[1].lower()
    if ext not in _ALLOWED_IMG:
        ext = ".png"
    digest = hashlib.md5(data).hexdigest()[:16]
    filename = f"{digest}{ext}"
    path = os.path.join(UPLOADS_DIR, filename)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return filename


def copy_local_image(src_path):
    """把磁碟上既有的圖片（例如舊專案的絕對路徑）複製進 uploads，回傳檔名。
    失敗回傳 None。"""
    try:
        with open(src_path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    return save_upload_bytes(data, os.path.basename(src_path))


def uploads_dir():
    ensure_dirs()
    return UPLOADS_DIR


# ---------- 專案存讀 ----------

def list_projects():
    ensure_dirs()
    items = []
    for fn in os.listdir(PROJECTS_DIR):
        if fn.endswith(".json"):
            path = os.path.join(PROJECTS_DIR, fn)
            items.append({"name": fn[:-5], "mtime": os.path.getmtime(path)})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def save_project(name, state):
    ensure_dirs()
    safe = _safe_name(name)
    path = os.path.join(PROJECTS_DIR, safe + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return safe


def load_project(name):
    path = os.path.join(PROJECTS_DIR, _safe_name(name) + ".json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def delete_project(name):
    path = os.path.join(PROJECTS_DIR, _safe_name(name) + ".json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ---------- 自動存檔（最後狀態） ----------

def save_session(state):
    ensure_dirs()
    with open(SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def load_session():
    if not os.path.exists(SESSION_PATH):
        return None
    try:
        with open(SESSION_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------- 匯入舊版存檔 ----------
#
# 支援兩種舊格式：
#   Format A（main.py / ppt_settings.json，目前主要在用）：
#       {"songs":[{title, lyrics:"[Verse]\n...", background, lyrics_left, lyrics_top,
#                  styles:{Title,Segment,Lyrics}}]}
#   Format B（更舊的 songs.json）：
#       {"slidesize":"16:9","songs":[{title, background, font:{name,size,color},
#                  lyrics:[ "第一頁\n第二行", "第二頁...", ... ]}]}


class _Library:
    """匯入時共用的積木去重工具。"""

    def __init__(self, base_dir):
        self.base = base_dir
        self.themes = {}      # 去重 key -> theme
        self.textstyles = {}  # 去重 key -> textStyle
        self._tid = 0
        self._sid = 0

    def theme_for(self, bg, name_hint=None):
        if not bg:
            key = "__none__"
        else:
            src = bg if os.path.isabs(bg) else os.path.join(self.base, bg)
            copied = copy_local_image(src)
            key = copied or "__none__"
        if key not in self.themes:
            self._tid += 1
            self.themes[key] = {
                "id": f"t{self._tid}",
                "name": name_hint or (os.path.splitext(os.path.basename(bg))[0] if bg else "純黑底"),
                "image": None if key == "__none__" else key,
                "bgColor": "#000000",
                "overlay": 0.0,
            }
        return self.themes[key]["id"]

    def style_for(self, ts):
        # ts 已含 title/segment/lyrics/lyricsLeft/... （尚未含 id/name）
        key = json.dumps(ts, sort_keys=True, ensure_ascii=False)
        if key not in self.textstyles:
            self._sid += 1
            ts = dict(ts)
            ts["id"] = f"s{self._sid}"
            ts["name"] = f"樣式 {self._sid}"
            self.textstyles[key] = ts
        return self.textstyles[key]["id"]

    def dump(self):
        return {"themes": list(self.themes.values()),
                "textStyles": list(self.textstyles.values())}


def _part(src, dfont="Arial", dsize=40, dcolor="#FFFFFF", dbold=False):
    src = src or {}
    return {
        "font": src.get("font", dfont),
        "size": src.get("size", dsize),
        "color": src.get("color", dcolor),
        "bold": bool(src.get("bold", dbold)),
    }


def _is_format_b(data):
    if "slidesize" in data or "output" in data:
        return True
    for s in data.get("songs", []):
        if isinstance(s.get("lyrics"), list) or isinstance(s.get("font"), dict):
            return True
    return False


def _import_format_a(data, lib):
    songs = []
    for i, song in enumerate(data.get("songs", [])):
        styles = song.get("styles", {})
        ts = {
            "title": _part(styles.get("Title"), dsize=60, dcolor="#FFD700", dbold=True),
            "segment": _part(styles.get("Segment"), dsize=30, dcolor="#FF4500"),
            "lyrics": _part(styles.get("Lyrics"), dsize=52, dcolor="#FFFFFF"),
            "lyricsLeft": song.get("lyrics_left", 0.05),
            "lyricsTop": song.get("lyrics_top", 1.8),
            "lyricsAlign": "center",
            "showHeader": True,
        }
        songs.append({
            "id": f"song{i+1}",
            "title": song.get("title", ""),
            "lyrics": song.get("lyrics", ""),
            "themeId": lib.theme_for(song.get("background", "")),
            "textStyleId": lib.style_for(ts),
        })
    return songs, "4:3"


def _import_format_b(data, lib):
    songs = []
    slide_size = data.get("slidesize", "4:3")
    if slide_size not in ("4:3", "16:9"):
        slide_size = "4:3"
    for i, song in enumerate(data.get("songs", [])):
        font = song.get("font", {}) or {}
        fname = font.get("name", "Microsoft JhengHei")
        fsize = font.get("size", 60)
        fcolor = font.get("color", "#FFFFFF")
        ts = {
            "title": {"font": fname, "size": 60, "color": "#FFD700", "bold": True},
            "segment": {"font": fname, "size": 30, "color": "#FF4500", "bold": False},
            "lyrics": {"font": fname, "size": fsize, "color": fcolor, "bold": False},
            "lyricsLeft": 0.05,
            "lyricsTop": 1.8,
            "lyricsAlign": "center",
            "showHeader": False,  # 這種舊檔是純歌詞逐頁，沒有標題列
        }
        # 陣列每一項都是一頁 → 用隱形段落標籤 [·] 分頁（showHeader=False 不會顯示）
        lyric_items = song.get("lyrics", [])
        if isinstance(lyric_items, str):
            lyrics_text = lyric_items
        else:
            lyrics_text = "\n".join(f"[·]\n{item}" for item in lyric_items)
        songs.append({
            "id": f"song{i+1}",
            "title": song.get("title", ""),
            "lyrics": lyrics_text,
            "themeId": lib.theme_for(song.get("background", "")),
            "textStyleId": lib.style_for(ts),
        })
    return songs, slide_size


def import_legacy(legacy_path):
    """讀舊版存檔（Format A 或 B），轉成新版狀態（library + project）。
    背景圖會一併複製進 uploads。"""
    with open(legacy_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    base = os.path.dirname(os.path.abspath(legacy_path))
    lib = _Library(base)

    if _is_format_b(data):
        songs, slide_size = _import_format_b(data, lib)
    else:
        songs, slide_size = _import_format_a(data, lib)

    return {
        "library": lib.dump(),
        "project": {
            "name": "匯入的舊專案",
            "slideSize": slide_size,
            "songs": songs,
        },
    }
