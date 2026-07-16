"""
教會敬拜 PPT 產生器 — 網頁版後端 (FastAPI)。

啟動：
    python -m uvicorn webapp.server:app --port 8000
或直接跑專案根目錄的 run_web.py（會自動開瀏覽器）。
"""

import os
import datetime

from fastapi import FastAPI, UploadFile, File, Body, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from . import storage
from .pptx_builder import build_pptx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(title="Worship PPT Maker (Web)")

storage.ensure_dirs()

# 背景圖：瀏覽器用 /media/<檔名> 讀取
app.mount("/media", StaticFiles(directory=storage.uploads_dir()), name="media")
# 前端靜態檔
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ---------- 圖片上傳 ----------

@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(413, "圖片太大（上限 30MB）")
    filename = storage.save_upload_bytes(data, file.filename)
    return {"filename": filename, "url": f"/media/{filename}"}


# ---------- 匯出 PPT ----------

@app.post("/api/export")
def export(payload: dict = Body(...)):
    songs = payload.get("songs") or []
    if not songs:
        raise HTTPException(400, "沒有任何歌曲可以匯出")
    stream, warnings = build_pptx(payload, storage.uploads_dir())
    name = payload.get("name") or "敬拜歌單"
    stamp = datetime.date.today().isoformat()
    fname = f"{name}_{stamp}.pptx"
    # 用 RFC5987 讓中文檔名不會壞掉
    from urllib.parse import quote
    disp = f"attachment; filename*=UTF-8''{quote(fname)}"
    headers = {
        "Content-Disposition": disp,
        "X-PPT-Warnings": ",".join(warnings),
    }
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers=headers,
    )


# ---------- 專案存讀 ----------

@app.get("/api/projects")
def projects():
    return storage.list_projects()


@app.post("/api/projects/{name}")
def save_project(name: str, state: dict = Body(...)):
    safe = storage.save_project(name, state)
    return {"name": safe}


@app.get("/api/projects/{name}")
def load_project(name: str):
    state = storage.load_project(name)
    if state is None:
        raise HTTPException(404, "找不到專案")
    return state


@app.delete("/api/projects/{name}")
def delete_project(name: str):
    ok = storage.delete_project(name)
    if not ok:
        raise HTTPException(404, "找不到專案")
    return {"ok": True}


# ---------- 自動存檔 / 還原 ----------

@app.post("/api/session")
def save_session(state: dict = Body(...)):
    storage.save_session(state)
    return {"ok": True}


@app.get("/api/session")
def get_session():
    return storage.load_session() or {}


# ---------- 匯入舊版 songs.json ----------

@app.post("/api/import-legacy")
def import_legacy(body: dict = Body(...)):
    path = (body or {}).get("path", "")
    if not path or not os.path.exists(path):
        raise HTTPException(404, f"找不到檔案：{path}")
    try:
        state = storage.import_legacy(path)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"匯入失敗：{e}")
    return state
