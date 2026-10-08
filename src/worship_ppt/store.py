"""所有資料的讀寫都在這裡（網頁、指令列、測試共用同一套）。

資料的關係：

    詩歌庫 songs ── 每首歌最新的歌詞、預設歌序、上次用的背景和排版
        │  (song_id)
    歌單 services ── 一次聚會（日期、名稱、服事同工）
        └── service_items ── 這次唱的每一首：歌詞、歌序、背景、排版「當下的樣子」
    背景 themes ── 圖片（images）＋底色＋暗色遮罩
    排版 styles ── 字型、大小、顏色、位置
    匯出紀錄 exports ── 每一次產生的 PPT 檔 + 當時完整內容的快照

歌單裡的每首歌是「複製一份」而不是直接指向詩歌庫：改這週的歌詞不會動到以前的紀錄。
按「匯出 PPT」時，這週用的歌詞／歌序／背景／排版會回存到詩歌庫，下次選這首歌就直接是上次的樣子。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

from . import images as imagestore
from .db import Database, now_text
from .errors import AppError, Conflict, NotFound
from .lyrics import nfkc, plan_song
from .paths import Paths
from .styles import PRESETS, clean_color, clean_style, preset

SLIDE_SIZES = ("4:3", "16:9")

DEFAULT_SETTINGS: dict = {
    "gdoc_url": "",
    "slide_size": "4:3",
    "service_name": "主日敬拜",
    "default_theme_id": None,
    "default_style_id": None,
    "cloudflared_path": "",
}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def title_key(title: str) -> str:
    """比對歌名用：全半形統一、去空白和標點、英文小寫。「常常 喜樂！」和「常常喜樂」算同一首。"""
    s = nfkc(title).lower()
    return re.sub(r"[\W_]+", "", s)


def _row(conn: sqlite3.Connection, sql: str, params=()) -> dict | None:
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def _clean_text(value, limit: int = 20000) -> str:
    return str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n")[:limit]


def _clean_date(value) -> str:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        raise AppError("日期格式不對", "請用 2026-10-11 這種寫法。")


def _opt_id(value) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise AppError("編號不正確")


# ---------------------------------------------------------------------------
# 初始化、設定
# ---------------------------------------------------------------------------

def open_db(paths: Paths) -> Database:
    paths.ensure()
    db = Database(paths.db_file)
    db.migrate()
    seed(db)
    return db


def seed(db: Database) -> None:
    """第一次啟動：放幾個現成的排版和兩個純色背景，一打開就能用。"""
    with db.tx() as conn:
        if conn.execute("SELECT COUNT(*) FROM styles").fetchone()[0] == 0:
            stamp = now_text()
            for name, overrides in PRESETS:
                conn.execute("INSERT INTO styles(name, data, created_at, updated_at) VALUES(?,?,?,?)",
                             (name, json.dumps(preset(overrides), ensure_ascii=False), stamp, stamp))
            first = conn.execute("SELECT MIN(id) FROM styles").fetchone()[0]
            db.kv_set("default_style_id", first, conn)
        if conn.execute("SELECT COUNT(*) FROM themes").fetchone()[0] == 0:
            stamp = now_text()
            for name, color in (("純黑底", "#000000"), ("深藍底", "#0B1D3A")):
                conn.execute("INSERT INTO themes(name, bg_color, created_at, updated_at) VALUES(?,?,?,?)",
                             (name, color, stamp, stamp))
            first = conn.execute("SELECT MIN(id) FROM themes").fetchone()[0]
            db.kv_set("default_theme_id", first, conn)


def get_settings(db: Database) -> dict:
    out = dict(DEFAULT_SETTINGS)
    for row in db.all("SELECT key, value FROM kv"):
        if row["key"] in DEFAULT_SETTINGS:
            try:
                out[row["key"]] = json.loads(row["value"])
            except ValueError:
                pass
    return out


def save_settings(db: Database, changes: dict) -> dict:
    clean: dict = {}
    if "gdoc_url" in changes:
        url = str(changes["gdoc_url"] or "").strip()
        if url:
            from .gdoc import export_url
            export_url(url)  # 網址看不懂就在這裡擋下來
        clean["gdoc_url"] = url
    if "slide_size" in changes:
        if changes["slide_size"] not in SLIDE_SIZES:
            raise AppError("投影片比例只能是 4:3 或 16:9")
        clean["slide_size"] = changes["slide_size"]
    if "service_name" in changes:
        clean["service_name"] = str(changes["service_name"] or "").strip()[:40] or "主日敬拜"
    if "default_theme_id" in changes:
        tid = _opt_id(changes["default_theme_id"])
        if tid is not None:
            get_theme(db, tid)
        clean["default_theme_id"] = tid
    if "default_style_id" in changes:
        sid = _opt_id(changes["default_style_id"])
        if sid is not None:
            get_style(db, sid)
        clean["default_style_id"] = sid
    if "cloudflared_path" in changes:
        clean["cloudflared_path"] = str(changes["cloudflared_path"] or "").strip()[:260]
    with db.tx() as conn:
        for key, value in clean.items():
            db.kv_set(key, value, conn)
    return get_settings(db)


# ---------------------------------------------------------------------------
# 背景（themes）與圖片
# ---------------------------------------------------------------------------

THEME_SELECT = """
SELECT t.*, i.ext AS image_ext, i.width AS image_width, i.height AS image_height, i.name AS image_name,
       (SELECT COUNT(*) FROM songs s WHERE s.theme_id = t.id) AS song_count,
       (SELECT COUNT(DISTINCT si.service_id) FROM service_items si WHERE si.theme_id = t.id) AS service_count,
       (SELECT MAX(sv.date) FROM service_items si JOIN services sv ON sv.id = si.service_id
         WHERE si.theme_id = t.id) AS last_used
FROM themes t LEFT JOIN images i ON i.id = t.image_id
"""


def _theme_out(row: dict) -> dict:
    image = None
    if row.get("image_id"):
        image = {"id": row["image_id"], "ext": row["image_ext"], "width": row["image_width"],
                 "height": row["image_height"], "name": row["image_name"]}
    return {
        "id": row["id"], "name": row["name"], "image": image, "bgColor": row["bg_color"],
        "overlay": row["overlay"], "tags": row["tags"], "archived": bool(row["archived"]),
        "songCount": row.get("song_count", 0), "serviceCount": row.get("service_count", 0),
        "lastUsed": row.get("last_used"), "updatedAt": row["updated_at"],
    }


def list_themes(db: Database, include_archived: bool = False) -> list[dict]:
    where = "" if include_archived else "WHERE t.archived = 0"
    rows = db.all(THEME_SELECT + f" {where} ORDER BY t.archived, COALESCE(last_used, '') DESC, t.id DESC")
    return [_theme_out(r) for r in rows]


def get_theme(db: Database, theme_id: int) -> dict:
    row = db.one(THEME_SELECT + " WHERE t.id = ?", (theme_id,))
    if not row:
        raise NotFound("找不到這個背景")
    return _theme_out(row)


def _theme_fields(data: dict) -> dict:
    out: dict = {}
    if "name" in data:
        out["name"] = str(data["name"] or "").strip()[:60] or "未命名背景"
    if "bgColor" in data:
        out["bg_color"] = clean_color(data["bgColor"])
    if "overlay" in data:
        try:
            out["overlay"] = max(0.0, min(0.9, float(data["overlay"])))
        except (TypeError, ValueError):
            raise AppError("暗色遮罩要是 0～0.9 之間的數字")
    if "imageId" in data:
        image_id = data["imageId"] or None
        if image_id is not None and not imagestore.IMAGE_ID_RE.match(str(image_id)):
            raise AppError("圖片編號不正確")
        out["image_id"] = image_id
    if "tags" in data:
        out["tags"] = str(data["tags"] or "").strip()[:200]
    if "archived" in data:
        out["archived"] = 1 if data["archived"] else 0
    return out


def create_theme(db: Database, data: dict) -> dict:
    fields = _theme_fields({"name": "新背景", **data})
    stamp = now_text()
    with db.tx() as conn:
        if fields.get("image_id") and not _row(conn, "SELECT id FROM images WHERE id=?", (fields["image_id"],)):
            raise NotFound("找不到這張圖片")
        cols = ", ".join(fields) + ", created_at, updated_at"
        marks = ", ".join("?" for _ in fields) + ", ?, ?"
        cur = conn.execute(f"INSERT INTO themes({cols}) VALUES({marks})", (*fields.values(), stamp, stamp))
        new_id = cur.lastrowid
    return get_theme(db, new_id)


def update_theme(db: Database, theme_id: int, data: dict) -> dict:
    fields = _theme_fields(data)
    if fields:
        with db.tx() as conn:
            if not _row(conn, "SELECT id FROM themes WHERE id=?", (theme_id,)):
                raise NotFound("找不到這個背景")
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE themes SET {sets}, updated_at=? WHERE id=?", (*fields.values(), now_text(), theme_id))
    return get_theme(db, theme_id)


def delete_theme(db: Database, theme_id: int) -> str:
    """沒被用過就真的刪掉；用過的只收起來（舊歌單、舊紀錄還要能顯示）。回傳 'deleted' 或 'archived'。"""
    theme = get_theme(db, theme_id)
    with db.tx() as conn:
        used = conn.execute("SELECT (SELECT COUNT(*) FROM songs WHERE theme_id=?) + "
                            "(SELECT COUNT(*) FROM service_items WHERE theme_id=?)", (theme_id, theme_id)).fetchone()[0]
        if used:
            conn.execute("UPDATE themes SET archived=1, updated_at=? WHERE id=?", (now_text(), theme_id))
            return "archived"
        conn.execute("DELETE FROM themes WHERE id=?", (theme_id,))
        for key in ("default_theme_id",):
            if db.kv_get(key) == theme["id"]:
                db.kv_set(key, None, conn)
    return "deleted"


def add_image(db: Database, paths: Paths, data: bytes, filename: str, by: str = "",
              create_theme: bool = True) -> dict:
    """存一張上傳的圖，並自動做成一個背景（同一張圖已經有背景就直接回傳那個）。
    create_theme=False：只存圖（給「幫現有的背景換一張圖」用），回傳 {"image": {...}}。"""
    info = imagestore.store(paths.images_dir, data)
    name = Path(filename or "圖片").stem.strip()[:60] or "圖片"
    stamp = now_text()
    with db.tx() as conn:
        conn.execute("INSERT OR IGNORE INTO images(id, name, ext, width, height, bytes, created_at, created_by) "
                     "VALUES(?,?,?,?,?,?,?,?)",
                     (info["id"], name, info["ext"], info["width"], info["height"], info["bytes"], stamp, by))
        if not create_theme:
            return {"image": {"id": info["id"], "ext": info["ext"], "width": info["width"],
                              "height": info["height"], "name": name}}
        existing = _row(conn, "SELECT id FROM themes WHERE image_id=? ORDER BY archived, id LIMIT 1", (info["id"],))
        if existing:
            conn.execute("UPDATE themes SET archived=0 WHERE id=?", (existing["id"],))
            theme_id = existing["id"]
        else:
            cur = conn.execute("INSERT INTO themes(name, image_id, bg_color, overlay, created_at, updated_at) "
                               "VALUES(?,?,?,?,?,?)", (name, info["id"], "#000000", 0.0, stamp, stamp))
            theme_id = cur.lastrowid
    return get_theme(db, theme_id)


def get_image(db: Database, image_id: str) -> dict:
    if not imagestore.IMAGE_ID_RE.match(image_id or ""):
        raise NotFound("找不到這張圖片")
    row = db.one("SELECT * FROM images WHERE id=?", (image_id,))
    if not row:
        raise NotFound("找不到這張圖片")
    return row


# ---------------------------------------------------------------------------
# 排版（styles）
# ---------------------------------------------------------------------------

def _style_out(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "archived": bool(row["archived"]),
            "updatedAt": row["updated_at"], "songCount": row.get("song_count", 0),
            "serviceCount": row.get("service_count", 0), **clean_style(json.loads(row["data"]))}


STYLE_SELECT = """
SELECT st.*,
       (SELECT COUNT(*) FROM songs s WHERE s.style_id = st.id) AS song_count,
       (SELECT COUNT(DISTINCT si.service_id) FROM service_items si WHERE si.style_id = st.id) AS service_count
FROM styles st
"""


def list_styles(db: Database, include_archived: bool = False) -> list[dict]:
    where = "" if include_archived else "WHERE st.archived = 0"
    return [_style_out(r) for r in db.all(STYLE_SELECT + f" {where} ORDER BY st.archived, st.id")]


def get_style(db: Database, style_id: int) -> dict:
    row = db.one(STYLE_SELECT + " WHERE st.id=?", (style_id,))
    if not row:
        raise NotFound("找不到這個排版")
    return _style_out(row)


def create_style(db: Database, data: dict) -> dict:
    name = str(data.get("name") or "").strip()[:60] or "新排版"
    body = clean_style(data)
    stamp = now_text()
    with db.tx() as conn:
        cur = conn.execute("INSERT INTO styles(name, data, created_at, updated_at) VALUES(?,?,?,?)",
                           (name, json.dumps(body, ensure_ascii=False), stamp, stamp))
        new_id = cur.lastrowid
    return get_style(db, new_id)


def update_style(db: Database, style_id: int, data: dict) -> dict:
    current = get_style(db, style_id)
    name = str(data.get("name", current["name"]) or "").strip()[:60] or current["name"]
    body = clean_style(data, base=current)
    archived = 1 if data.get("archived", current["archived"]) else 0
    with db.tx() as conn:
        conn.execute("UPDATE styles SET name=?, data=?, archived=?, updated_at=? WHERE id=?",
                     (name, json.dumps(body, ensure_ascii=False), archived, now_text(), style_id))
    return get_style(db, style_id)


def duplicate_style(db: Database, style_id: int) -> dict:
    src = get_style(db, style_id)
    return create_style(db, {**src, "name": src["name"] + "（複製）"})


def delete_style(db: Database, style_id: int) -> str:
    get_style(db, style_id)
    with db.tx() as conn:
        used = conn.execute("SELECT (SELECT COUNT(*) FROM songs WHERE style_id=?) + "
                            "(SELECT COUNT(*) FROM service_items WHERE style_id=?)", (style_id, style_id)).fetchone()[0]
        if used:
            conn.execute("UPDATE styles SET archived=1, updated_at=? WHERE id=?", (now_text(), style_id))
            return "archived"
        if conn.execute("SELECT COUNT(*) FROM styles WHERE archived=0").fetchone()[0] <= 1:
            raise AppError("至少要留一個排版")
        conn.execute("DELETE FROM styles WHERE id=?", (style_id,))
        if db.kv_get("default_style_id") == style_id:
            db.kv_set("default_style_id", None, conn)
    return "deleted"


# ---------------------------------------------------------------------------
# 詩歌庫（songs）
# ---------------------------------------------------------------------------

SONG_SELECT = """
SELECT s.*,
       (SELECT COUNT(DISTINCT si.service_id) FROM service_items si WHERE si.song_id = s.id) AS use_count,
       (SELECT MAX(sv.date) FROM service_items si JOIN services sv ON sv.id = si.service_id
         WHERE si.song_id = s.id) AS last_used
FROM songs s
"""


def _song_out(row: dict) -> dict:
    return {
        "id": row["id"], "title": row["title"], "aliases": row["aliases"], "key": row["song_key"],
        "lyrics": row["lyrics"], "sequence": row["sequence"], "themeId": row["theme_id"],
        "styleId": row["style_id"], "notes": row["notes"], "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"], "useCount": row.get("use_count", 0), "lastUsed": row.get("last_used"),
    }


def list_songs(db: Database, q: str = "", limit: int = 500) -> list[dict]:
    rows = [_song_out(r) for r in db.all(SONG_SELECT + " ORDER BY COALESCE(last_used, '') DESC, s.title")]
    q = title_key(q)
    if q:
        def hit(song: dict) -> bool:
            keys = [title_key(song["title"])] + [title_key(a) for a in re.split(r"[,，、/]", song["aliases"])]
            return any(q in k for k in keys if k) or q in title_key(song["lyrics"][:4000])
        rows = [s for s in rows if hit(s)]
    return rows[:limit]


def get_song(db: Database, song_id: int) -> dict:
    row = db.one(SONG_SELECT + " WHERE s.id=?", (song_id,))
    if not row:
        raise NotFound("詩歌庫裡找不到這首歌")
    return _song_out(row)


def find_song(db: Database, title: str, conn: sqlite3.Connection | None = None) -> dict | None:
    """用歌名（或別名）找詩歌庫裡的歌。"""
    key = title_key(title)
    if not key:
        return None
    runner = conn.execute if conn is not None else None

    def query(sql, params=()):
        if runner:
            return [dict(r) for r in runner(sql, params).fetchall()]
        return db.all(sql, params)

    rows = query("SELECT * FROM songs WHERE title_key=?", (key,))
    if rows:
        return rows[0]
    for row in query("SELECT * FROM songs WHERE aliases != ''"):
        if key in {title_key(a) for a in re.split(r"[,，、/]", row["aliases"])}:
            return row
    return None


def song_history(db: Database, song_id: int) -> dict:
    uses = db.all("""
        SELECT sv.id AS service_id, sv.date, sv.name, si.sequence, si.theme_id, si.style_id,
               t.name AS theme_name, st.name AS style_name
        FROM service_items si JOIN services sv ON sv.id = si.service_id
        LEFT JOIN themes t ON t.id = si.theme_id LEFT JOIN styles st ON st.id = si.style_id
        WHERE si.song_id=? ORDER BY sv.date DESC, sv.id DESC LIMIT 100""", (song_id,))
    revisions = db.all("SELECT id, lyrics, sequence, reason, created_at, created_by FROM song_revisions "
                       "WHERE song_id=? ORDER BY id DESC LIMIT 50", (song_id,))
    return {"uses": uses, "revisions": revisions}


def _song_fields(data: dict) -> dict:
    out: dict = {}
    if "title" in data:
        title = str(data["title"] or "").strip()[:80]
        if not title:
            raise AppError("歌名不能是空的")
        out["title"] = title
        out["title_key"] = title_key(title) or title
    if "aliases" in data:
        out["aliases"] = str(data["aliases"] or "").strip()[:300]
    if "key" in data:
        out["song_key"] = str(data["key"] or "").strip()[:20]
    if "lyrics" in data:
        out["lyrics"] = _clean_text(data["lyrics"])
    if "sequence" in data:
        out["sequence"] = _clean_text(data["sequence"], 1000).strip()
    if "themeId" in data:
        out["theme_id"] = _opt_id(data["themeId"])
    if "styleId" in data:
        out["style_id"] = _opt_id(data["styleId"])
    if "notes" in data:
        out["notes"] = _clean_text(data["notes"], 2000)
    return out


def _insert_song(conn: sqlite3.Connection, fields: dict, by: str) -> int:
    if "title" not in fields:
        raise AppError("歌名不能是空的")
    if _row(conn, "SELECT id FROM songs WHERE title_key=?", (fields["title_key"],)):
        raise Conflict(f"詩歌庫裡已經有「{fields['title']}」了", "要改那首歌的話，請直接在詩歌庫打開它。")
    stamp = now_text()
    cols = ", ".join(fields) + ", created_at, updated_at, updated_by"
    marks = ", ".join("?" for _ in fields) + ", ?, ?, ?"
    return conn.execute(f"INSERT INTO songs({cols}) VALUES({marks})", (*fields.values(), stamp, stamp, by)).lastrowid


def _update_song(conn: sqlite3.Connection, song_id: int, fields: dict, by: str, reason: str) -> None:
    current = _row(conn, "SELECT * FROM songs WHERE id=?", (song_id,))
    if not current:
        raise NotFound("詩歌庫裡找不到這首歌")
    if "title_key" in fields and fields["title_key"] != current["title_key"]:
        clash = _row(conn, "SELECT id FROM songs WHERE title_key=? AND id != ?", (fields["title_key"], song_id))
        if clash:
            raise Conflict(f"詩歌庫裡已經有另一首「{fields['title']}」")
    changed = {k: v for k, v in fields.items() if current.get(k) != v}
    if not changed:
        return
    if ("lyrics" in changed or "sequence" in changed) and (current["lyrics"] or current["sequence"]):
        conn.execute("INSERT INTO song_revisions(song_id, lyrics, sequence, reason, created_at, created_by) "
                     "VALUES(?,?,?,?,?,?)", (song_id, current["lyrics"], current["sequence"], reason, now_text(), by))
    sets = ", ".join(f"{k}=?" for k in changed)
    conn.execute(f"UPDATE songs SET {sets}, updated_at=?, updated_by=? WHERE id=?",
                 (*changed.values(), now_text(), by, song_id))


def create_song(db: Database, data: dict, by: str = "") -> dict:
    fields = _song_fields(data)
    with db.tx() as conn:
        song_id = _insert_song(conn, fields, by)
    return get_song(db, song_id)


def update_song(db: Database, song_id: int, data: dict, by: str = "", reason: str = "在詩歌庫修改") -> dict:
    fields = _song_fields(data)
    with db.tx() as conn:
        _update_song(conn, song_id, fields, by, reason)
    return get_song(db, song_id)


def delete_song(db: Database, song_id: int) -> None:
    get_song(db, song_id)
    with db.tx() as conn:
        conn.execute("DELETE FROM songs WHERE id=?", (song_id,))


def restore_revision(db: Database, song_id: int, revision_id: int, by: str = "") -> dict:
    rev = db.one("SELECT * FROM song_revisions WHERE id=? AND song_id=?", (revision_id, song_id))
    if not rev:
        raise NotFound("找不到這個舊版本")
    return update_song(db, song_id, {"lyrics": rev["lyrics"], "sequence": rev["sequence"]}, by,
                       reason=f"還原 {rev['created_at']} 的版本")


# ---------------------------------------------------------------------------
# 歌單（services）與歌單裡的歌（items）
# ---------------------------------------------------------------------------

def _item_out(row: dict) -> dict:
    return {
        "id": row["id"], "position": row["position"], "songId": row["song_id"], "title": row["title"],
        "key": row["song_key"], "lyrics": row["lyrics"], "sequence": row["sequence"],
        "themeId": row["theme_id"], "styleId": row["style_id"], "version": row["version"],
        "updatedAt": row["updated_at"], "updatedBy": row["updated_by"],
    }


def _service_out(row: dict) -> dict:
    return {
        "id": row["id"], "date": row["date"], "name": row["name"], "team": row["team"],
        "slideSize": row["slide_size"], "followSequence": bool(row["follow_sequence"]),
        "sourceUrl": row["source_url"], "notes": row["notes"], "version": row["version"],
        "updatedAt": row["updated_at"], "updatedBy": row["updated_by"],
        "itemCount": row.get("item_count"), "exportCount": row.get("export_count"),
        "lastExport": row.get("last_export"), "titles": row.get("titles"),
    }


def list_services(db: Database, limit: int = 300) -> list[dict]:
    rows = db.all("""
        SELECT sv.*,
               (SELECT COUNT(*) FROM service_items si WHERE si.service_id = sv.id) AS item_count,
               (SELECT COUNT(*) FROM exports e WHERE e.service_id = sv.id) AS export_count,
               (SELECT MAX(e.created_at) FROM exports e WHERE e.service_id = sv.id) AS last_export,
               (SELECT GROUP_CONCAT(title, '、') FROM
                   (SELECT title FROM service_items si WHERE si.service_id = sv.id ORDER BY position)) AS titles
        FROM services sv ORDER BY sv.date DESC, sv.id DESC LIMIT ?""", (limit,))
    return [_service_out(r) for r in rows]


def get_service(db: Database, service_id: int) -> dict:
    with db.read() as conn:
        row = _row(conn, "SELECT * FROM services WHERE id=?", (service_id,))
        if not row:
            raise NotFound("找不到這份歌單")
        items = [dict(r) for r in conn.execute(
            "SELECT * FROM service_items WHERE service_id=? ORDER BY position, id", (service_id,)).fetchall()]
        last = _row(conn, "SELECT id, created_at, created_by, filename, slides FROM exports "
                          "WHERE service_id=? ORDER BY id DESC LIMIT 1", (service_id,))
    out = _service_out(row)
    out["items"] = [_item_out(i) for i in items]
    out["lastExport"] = last
    out["stamp"] = service_stamp(out)
    return out


def service_stamp(service: dict) -> str:
    """整份歌單的「版本指紋」：任何人改了任何一首歌，這個字串就會變（網頁用它發現別人的修改）。"""
    parts = [str(service["version"])] + [f"{i['id']}.{i['version']}" for i in service["items"]]
    return "-".join(parts)


def _default_look(db: Database, conn: sqlite3.Connection, service_id: int | None) -> tuple[int | None, int | None]:
    """新加進來的歌先用什麼背景和排版：同一份歌單最後一首的 → 設定裡的預設。"""
    if service_id is not None:
        last = _row(conn, "SELECT theme_id, style_id FROM service_items WHERE service_id=? "
                          "ORDER BY position DESC, id DESC LIMIT 1", (service_id,))
        if last and (last["theme_id"] or last["style_id"]):
            return last["theme_id"], last["style_id"]
    settings = get_settings(db)
    return settings.get("default_theme_id"), settings.get("default_style_id")


def create_service(db: Database, data: dict, by: str = "") -> dict:
    settings = get_settings(db)
    svc_date = _clean_date(data.get("date") or date.today().isoformat())
    name = str(data.get("name") or "").strip()[:60] or settings["service_name"]
    size = data.get("slideSize") or settings["slide_size"]
    if size not in SLIDE_SIZES:
        size = "4:3"
    stamp = now_text()
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO services(date, name, team, slide_size, follow_sequence, source_url, notes, "
            "created_at, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (svc_date, name, str(data.get("team") or "")[:300], size, 1 if data.get("followSequence", True) else 0,
             str(data.get("sourceUrl") or "")[:500], _clean_text(data.get("notes"), 2000), stamp, stamp, by))
        service_id = cur.lastrowid
    return get_service(db, service_id)


def update_service(db: Database, service_id: int, data: dict, version: int | None, by: str = "") -> dict:
    fields: dict = {}
    if "date" in data:
        fields["date"] = _clean_date(data["date"])
    if "name" in data:
        fields["name"] = str(data["name"] or "").strip()[:60] or "主日敬拜"
    if "team" in data:
        fields["team"] = str(data["team"] or "")[:300]
    if "slideSize" in data:
        if data["slideSize"] not in SLIDE_SIZES:
            raise AppError("投影片比例只能是 4:3 或 16:9")
        fields["slide_size"] = data["slideSize"]
    if "followSequence" in data:
        fields["follow_sequence"] = 1 if data["followSequence"] else 0
    if "notes" in data:
        fields["notes"] = _clean_text(data["notes"], 2000)
    with db.tx() as conn:
        row = _row(conn, "SELECT version FROM services WHERE id=?", (service_id,))
        if not row:
            raise NotFound("找不到這份歌單")
        if version is not None and int(version) != row["version"]:
            raise Conflict("別人剛剛也改了這份歌單", "畫面已經換成最新的內容，請再改一次。")
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE services SET {sets}, version=version+1, updated_at=?, updated_by=? WHERE id=?",
                         (*fields.values(), now_text(), by, service_id))
    return get_service(db, service_id)


def _bump_service(conn: sqlite3.Connection, service_id: int, by: str) -> None:
    conn.execute("UPDATE services SET version=version+1, updated_at=?, updated_by=? WHERE id=?",
                 (now_text(), by, service_id))


def delete_service(db: Database, service_id: int) -> None:
    with db.tx() as conn:
        if not _row(conn, "SELECT id FROM services WHERE id=?", (service_id,)):
            raise NotFound("找不到這份歌單")
        conn.execute("DELETE FROM services WHERE id=?", (service_id,))


def duplicate_service(db: Database, service_id: int, new_date: str, by: str = "") -> dict:
    """複製成新的一週：歌、歌序、背景、排版都一樣，日期換掉。"""
    src = get_service(db, service_id)
    new = create_service(db, {"date": new_date, "name": src["name"], "team": "", "slideSize": src["slideSize"],
                              "followSequence": src["followSequence"]}, by)
    stamp = now_text()
    with db.tx() as conn:
        for pos, it in enumerate(src["items"]):
            conn.execute("INSERT INTO service_items(service_id, position, song_id, title, song_key, lyrics, sequence, "
                         "theme_id, style_id, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (new["id"], pos, it["songId"], it["title"], it["key"], it["lyrics"], it["sequence"],
                          it["themeId"], it["styleId"], stamp, by))
    return get_service(db, new["id"])


def add_item(db: Database, service_id: int, data: dict, by: str = "") -> dict:
    """在歌單最後加一首歌。有 songId 就從詩歌庫複製歌詞、歌序、背景、排版。"""
    stamp = now_text()
    with db.tx() as conn:
        if not _row(conn, "SELECT id FROM services WHERE id=?", (service_id,)):
            raise NotFound("找不到這份歌單")
        song_id = _opt_id(data.get("songId"))
        theme_id, style_id = _default_look(db, conn, service_id)
        title, key, lyrics, sequence = str(data.get("title") or "").strip()[:80], "", "", ""
        if song_id is not None:
            song = _row(conn, "SELECT * FROM songs WHERE id=?", (song_id,))
            if not song:
                raise NotFound("詩歌庫裡找不到這首歌")
            title, key, lyrics, sequence = song["title"], song["song_key"], song["lyrics"], song["sequence"]
            theme_id = song["theme_id"] or theme_id
            style_id = song["style_id"] or style_id
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM service_items WHERE service_id=?",
                           (service_id,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO service_items(service_id, position, song_id, title, song_key, lyrics, sequence, theme_id, "
            "style_id, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (service_id, pos, song_id, title, key, lyrics, sequence, theme_id, style_id, stamp, by))
        item_id = cur.lastrowid
        _bump_service(conn, service_id, by)
        return _item_out(_row(conn, "SELECT * FROM service_items WHERE id=?", (item_id,)))


def get_item(db: Database, item_id: int) -> dict:
    row = db.one("SELECT * FROM service_items WHERE id=?", (item_id,))
    if not row:
        raise NotFound("這首歌已經被移出歌單了")
    return {**_item_out(row), "serviceId": row["service_id"]}


def update_item(db: Database, item_id: int, data: dict, version: int | None, by: str = "") -> dict:
    fields: dict = {}
    if "title" in data:
        fields["title"] = str(data["title"] or "").strip()[:80]
    if "key" in data:
        fields["song_key"] = str(data["key"] or "").strip()[:20]
    if "lyrics" in data:
        fields["lyrics"] = _clean_text(data["lyrics"])
    if "sequence" in data:
        fields["sequence"] = _clean_text(data["sequence"], 1000)
    if "themeId" in data:
        fields["theme_id"] = _opt_id(data["themeId"])
    if "styleId" in data:
        fields["style_id"] = _opt_id(data["styleId"])
    if "songId" in data:
        fields["song_id"] = _opt_id(data["songId"])
    with db.tx() as conn:
        row = _row(conn, "SELECT * FROM service_items WHERE id=?", (item_id,))
        if not row:
            raise NotFound("這首歌已經被別人移出歌單了", "重新整理頁面看看最新的歌單。")
        if version is not None and int(version) != row["version"]:
            who = row["updated_by"] or "別人"
            raise Conflict(f"{who} 剛剛也改了「{row['title'] or '這首歌'}」", "畫面已經換成最新的內容，請再改一次。")
        if fields.get("theme_id") and not _row(conn, "SELECT id FROM themes WHERE id=?", (fields["theme_id"],)):
            raise NotFound("找不到這個背景")
        if fields.get("style_id") and not _row(conn, "SELECT id FROM styles WHERE id=?", (fields["style_id"],)):
            raise NotFound("找不到這個排版")
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE service_items SET {sets}, version=version+1, updated_at=?, updated_by=? WHERE id=?",
                         (*fields.values(), now_text(), by, item_id))
        return _item_out(_row(conn, "SELECT * FROM service_items WHERE id=?", (item_id,)))


def delete_item(db: Database, item_id: int, by: str = "") -> None:
    with db.tx() as conn:
        row = _row(conn, "SELECT service_id FROM service_items WHERE id=?", (item_id,))
        if not row:
            return
        conn.execute("DELETE FROM service_items WHERE id=?", (item_id,))
        _bump_service(conn, row["service_id"], by)


def reorder_items(db: Database, service_id: int, item_ids: list[int], by: str = "") -> dict:
    with db.tx() as conn:
        existing = [r[0] for r in conn.execute("SELECT id FROM service_items WHERE service_id=? ORDER BY position, id",
                                               (service_id,)).fetchall()]
        wanted = [int(i) for i in item_ids if int(i) in existing]
        order = wanted + [i for i in existing if i not in wanted]
        for pos, item_id in enumerate(order):
            conn.execute("UPDATE service_items SET position=? WHERE id=?", (pos, item_id))
        _bump_service(conn, service_id, by)
    return get_service(db, service_id)


def apply_look(db: Database, service_id: int, data: dict, by: str = "") -> dict:
    """整份歌單一次換背景或排版。"""
    fields: dict = {}
    if data.get("themeId"):
        fields["theme_id"] = _opt_id(data["themeId"])
        get_theme(db, fields["theme_id"])
    if data.get("styleId"):
        fields["style_id"] = _opt_id(data["styleId"])
        get_style(db, fields["style_id"])
    if fields:
        with db.tx() as conn:
            sets = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE service_items SET {sets}, version=version+1, updated_at=?, updated_by=? "
                         f"WHERE service_id=?", (*fields.values(), now_text(), by, service_id))
            _bump_service(conn, service_id, by)
    return get_service(db, service_id)


# ---------------------------------------------------------------------------
# Google 文件匯入
# ---------------------------------------------------------------------------

def import_doc(db: Database, sheet, service_id: int | None = None, by: str = "") -> dict:
    """把讀到的 Google 文件變成一份歌單。

    - 歌詞、歌序、調性用文件上的（這週的安排）。
    - 背景和排版：詩歌庫有這首歌 → 用它上次的樣子；新歌 → 用前一首的。
    - service_id 有給：更新那份歌單（同名的歌保留原本的背景和排版，文件裡沒有的歌移除）。
    """
    if not sheet.songs:
        raise AppError("文件裡沒有讀到任何歌", "請確認文件裡有表格，而且表格第一列有「歌名」「歌詞」這些欄名。")
    if service_id is None:
        service = create_service(db, {"date": sheet.date or date.today().isoformat(), "team": sheet.team,
                                      "sourceUrl": sheet.source_url}, by)
        service_id = service["id"]
    else:
        service = get_service(db, service_id)
        update_service(db, service_id, {"team": sheet.team or service["team"]}, None, by)
    old_items = {title_key(i["title"]): i for i in get_service(db, service_id)["items"]}
    settings = get_settings(db)
    stamp = now_text()
    matched = []
    with db.tx() as conn:
        prev_theme, prev_style = settings.get("default_theme_id"), settings.get("default_style_id")
        keep_ids: list[int] = []
        for pos, song in enumerate(sheet.songs):
            lib = find_song(db, song.title, conn)
            old = old_items.get(title_key(song.title))
            if old:
                theme_id, style_id = old["themeId"], old["styleId"]
            elif lib and (lib["theme_id"] or lib["style_id"]):
                theme_id, style_id = lib["theme_id"] or prev_theme, lib["style_id"] or prev_style
            else:
                theme_id, style_id = prev_theme, prev_style
            prev_theme, prev_style = theme_id or prev_theme, style_id or prev_style
            song_id = lib["id"] if lib else (old["songId"] if old else None)
            if old:
                conn.execute("UPDATE service_items SET position=?, song_id=?, title=?, song_key=?, lyrics=?, "
                             "sequence=?, version=version+1, updated_at=?, updated_by=? WHERE id=?",
                             (pos, song_id, song.title, song.key, song.lyrics, song.sequence, stamp, by, old["id"]))
                keep_ids.append(old["id"])
            else:
                cur = conn.execute(
                    "INSERT INTO service_items(service_id, position, song_id, title, song_key, lyrics, sequence, "
                    "theme_id, style_id, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (service_id, pos, song_id, song.title, song.key, song.lyrics, song.sequence,
                     theme_id, style_id, stamp, by))
                keep_ids.append(cur.lastrowid)
            matched.append({"title": song.title, "inLibrary": bool(lib),
                            "lyricsChanged": bool(lib and lib["lyrics"].strip() != song.lyrics.strip())})
        for old in old_items.values():
            if old["id"] not in keep_ids:
                conn.execute("DELETE FROM service_items WHERE id=?", (old["id"],))
        _bump_service(conn, service_id, by)
    result = get_service(db, service_id)
    result["importReport"] = matched
    return result


# ---------------------------------------------------------------------------
# 匯出：把一份歌單整理成「要做成 PPT 的完整內容」
# ---------------------------------------------------------------------------

FALLBACK_THEME = {"id": None, "name": "純黑底", "image": None, "bgColor": "#000000", "overlay": 0.0}


def resolve_service(db: Database, service_id: int) -> dict:
    service = get_service(db, service_id)
    themes = {t["id"]: t for t in list_themes(db, include_archived=True)}
    styles = {s["id"]: s for s in list_styles(db, include_archived=True)}
    settings = get_settings(db)
    fallback_style = styles.get(settings.get("default_style_id")) or next(iter(styles.values()), None) or \
        {"id": None, "name": "預設", **clean_style({})}
    fallback_theme = themes.get(settings.get("default_theme_id")) or FALLBACK_THEME
    songs = []
    for item in service["items"]:
        theme = themes.get(item["themeId"]) or fallback_theme
        style = styles.get(item["styleId"]) or fallback_style
        plan = plan_song(item["lyrics"], item["sequence"], follow_sequence=service["followSequence"],
                         max_lines=style["maxLines"], title_slide=style["titleSlide"])
        songs.append({
            "itemId": item["id"], "songId": item["songId"], "title": item["title"], "key": item["key"],
            "lyrics": item["lyrics"], "sequence": item["sequence"],
            "theme": {k: theme[k] for k in ("id", "name", "image", "bgColor", "overlay")},
            "style": {k: v for k, v in style.items() if k not in ("songCount", "serviceCount", "updatedAt", "archived")},
            "slides": plan["slides"], "warnings": plan["warnings"],
        })
    return {"service": {k: service[k] for k in ("id", "date", "name", "team", "slideSize", "followSequence")},
            "songs": songs}


def sync_library(db: Database, service_id: int, by: str = "", item_ids: list[int] | None = None) -> list[dict]:
    """匯出後：把這份歌單每首歌「這次的樣子」回存到詩歌庫。回傳每首歌做了什麼。
    item_ids 有給就只存那幾首（編輯畫面的「存到詩歌庫」）。"""
    service = get_service(db, service_id)
    report = []
    with db.tx() as conn:
        for item in service["items"]:
            if item_ids is not None and item["id"] not in item_ids:
                continue
            if not item["title"].strip():
                continue
            fields = {"title": item["title"], "title_key": title_key(item["title"]) or item["title"],
                      "song_key": item["key"], "lyrics": item["lyrics"], "sequence": item["sequence"],
                      "theme_id": item["themeId"], "style_id": item["styleId"]}
            song = None
            if item["songId"]:
                song = _row(conn, "SELECT * FROM songs WHERE id=?", (item["songId"],))
            if song is None:
                song = find_song(db, item["title"], conn)
            if song is None:
                song_id = _insert_song(conn, fields, by)
                report.append({"title": item["title"], "action": "added"})
            else:
                song_id = song["id"]
                alias_keys = {title_key(a) for a in re.split(r"[,，、/]", song["aliases"]) if a.strip()}
                if fields["title_key"] in alias_keys:  # 文件用的是別名：詩歌庫的正式歌名不動
                    fields.pop("title"); fields.pop("title_key")
                elif fields["title_key"] != song["title_key"]:
                    clash = _row(conn, "SELECT id FROM songs WHERE title_key=? AND id != ?",
                                 (fields["title_key"], song_id))
                    if clash:  # 改了歌名剛好撞到另一首：歌名留著詩歌庫原本的
                        fields.pop("title"); fields.pop("title_key")
                    else:
                        # 歌名改了：舊名字留作別名，下次文件寫舊名字也找得到
                        aliases = [a for a in re.split(r"[,，、/]", song["aliases"]) if a.strip()]
                        if song["title"] not in aliases:
                            fields["aliases"] = "、".join(aliases + [song["title"]])
                before = song["lyrics"]
                _update_song(conn, song_id, fields, by, reason=f"{service['date']} {service['name']} 匯出")
                report.append({"title": item["title"], "action": "updated" if before != item["lyrics"] else "same"})
            if item["songId"] != song_id:
                conn.execute("UPDATE service_items SET song_id=? WHERE id=?", (song_id, item["id"]))
    return report


def record_export(db: Database, service: dict, filename: str, rel_file: str, slides: int, size: int,
                  snapshot: dict, warnings: list[str], by: str = "") -> dict:
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO exports(service_id, service_name, service_date, filename, file, slides, bytes, snapshot, "
            "warnings, created_at, created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (service["id"], service["name"], service["date"], filename, rel_file, slides, size,
             json.dumps(snapshot, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False), now_text(), by))
        export_id = cur.lastrowid
    return get_export(db, export_id)


def _export_out(row: dict) -> dict:
    return {"id": row["id"], "serviceId": row["service_id"], "serviceName": row["service_name"],
            "serviceDate": row["service_date"], "filename": row["filename"], "file": row["file"],
            "slides": row["slides"], "bytes": row["bytes"], "warnings": json.loads(row["warnings"] or "[]"),
            "createdAt": row["created_at"], "createdBy": row["created_by"]}


def list_exports(db: Database, limit: int = 300) -> list[dict]:
    return [_export_out(r) for r in db.all(
        "SELECT id, service_id, service_name, service_date, filename, file, slides, bytes, warnings, created_at, "
        "created_by FROM exports ORDER BY id DESC LIMIT ?", (limit,))]


def get_export(db: Database, export_id: int, with_snapshot: bool = False) -> dict:
    row = db.one("SELECT * FROM exports WHERE id=?", (export_id,))
    if not row:
        raise NotFound("找不到這個匯出紀錄")
    out = _export_out(row)
    if with_snapshot:
        out["snapshot"] = json.loads(row["snapshot"])
    return out


def dashboard(db: Database) -> dict:
    today = date.today().isoformat()
    upcoming = db.one("SELECT id FROM services WHERE date >= ? ORDER BY date, id LIMIT 1", (today,))
    counts = db.one("""SELECT (SELECT COUNT(*) FROM songs) AS songs,
                              (SELECT COUNT(*) FROM themes WHERE archived=0) AS themes,
                              (SELECT COUNT(*) FROM styles WHERE archived=0) AS styles,
                              (SELECT COUNT(*) FROM services) AS services,
                              (SELECT COUNT(*) FROM exports) AS exports""")
    return {"upcoming": get_service(db, upcoming["id"]) if upcoming else None, "counts": counts,
            "recent": list_services(db, limit=6), "recentExports": list_exports(db, limit=5)}


def export_filename(service: dict) -> str:
    safe = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", f"{service['date']} {service['name']}").strip() or "敬拜歌單"
    return safe[:80] + ".pptx"


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")
