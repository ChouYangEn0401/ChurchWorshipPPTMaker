"""網頁：頁面 + JSON API。create_app() 回傳一個 FastAPI app（測試也用它）。

所有請求先經過門口（CloudServicesPlatform 的 SDK：isdcsp.web.Site）：分辨本機／遠端、檢查 Host、遠端要登入、
改資料要同源（遠端再加 CSRF token）、加上安全標頭。這裡只決定規則（哪些路徑公開、哪些只限本機）和頁面長相。
頁面用 Jinja2 在伺服器畫好外框，編輯畫面的互動（即時預覽、自動存檔）交給 static/js/ 底下的程式。
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import mimetypes
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

import isdcsp
from fastapi import APIRouter, Body, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from isdcsp import passwords, web
from isdcsp.tunnel import PublicTunnel, TunnelDriverError

from .. import __version__, backup, images as imagestore, legacy, pptx_builder, store
from ..errors import AppError, Forbidden, NotFound
from ..gdoc import fetch_sheet, label_mismatches
from ..paths import Paths

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
TEMPLATES = HERE / "templates"
log = logging.getLogger("worship_ppt.web")

# Windows 的登錄檔有時把 .js 標成 text/plain，瀏覽器就不肯當成程式執行
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

PUBLIC_PATHS = ("/healthz", "/favicon.ico", "/static/")   # 不用登入就能看的（/login 由門口自己處理）
LOCAL_ONLY_PREFIXES = ("/api/tunnel", "/api/settings/password", "/api/legacy", "/api/backup", "/api/sessions")
IN_APP_MARKERS = ("Line/", "FBAN", "FBAV", "Instagram", "MicroMessenger", "Telegram")
# 擋下來時給同工看的頁面與用字（原因代碼是 isdcsp.web.DENIALS 的）
DENY_PAGES = {
    "not_open": ("blocked.html", "這個網站還沒開放從外面使用", "請負責的同工在主機電腦上到「設定」設定團隊密碼。"),
    "host": ("error.html", "這個網址已經失效了", "請跟負責的同工要新的網址。"),
    "local_only": ("error.html", "這個功能只能在主機電腦上使用", ""),
    "origin": ("error.html", "請求來源不對，已經擋下來了", "請直接從這個網站的頁面操作。"),
    "csrf": ("error.html", "頁面放太久了，請重新整理後再試一次", ""),
}
# 在 SDK 的基本 CSP 上放寬兩項：頁面用到 style 屬性；其他都只准這個網站自己的東西
CSP = {"default-src": "'self'", "style-src": "'self' 'unsafe-inline'"}
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
INSTALL_HINT = ("要讓同工從外面一起編輯，請先安裝 cloudflared：打開「命令提示字元」輸入 "
                "winget install --id Cloudflare.cloudflared ，裝好後再按一次。")


def _asset_version() -> str:
    h = hashlib.sha1()
    for file in sorted(STATIC.rglob("*")):
        if file.is_file():
            h.update(file.name.encode())
            h.update(file.read_bytes())
    return h.hexdigest()[:10]


def open_sessions(paths: Paths) -> web.SessionStore:
    """遠端登入的同工（SDK 的 session：只存摘要、閒置 14 天、最長 60 天）。網頁與指令列用同一個檔案。"""
    return web.SessionStore(paths.data_dir / "sessions.sqlite3")


def create_app(paths: Paths | None = None, *, port: int = 8788, tunnel_command: list[str] | None = None,
               autostart_tunnel: bool = False) -> FastAPI:
    paths = paths or Paths.discover()
    db = store.open_db(paths)
    templates = Jinja2Templates(directory=str(TEMPLATES))
    asset_v = _asset_version()
    templates.env.globals.update(version=__version__, asset_v=asset_v)
    extra_hosts = {h.strip().lower() for h in os.environ.get("WORSHIP_PPT_ALLOWED_HOSTS", "").split(",") if h.strip()}
    # 對外連結：CloudServicesPlatform 的 SDK（isdcsp.tunnel）。cloudflared 跑在 Job Object 裡：這個程式當掉，連結一起關。
    tunnel = PublicTunnel(port, cloudflared_path=lambda: store.get_settings(db).get("cloudflared_path", ""),
                          command=tunnel_command, log_file=paths.logs_dir / "cloudflared.log")
    # 門口：本機／遠端、Host、登入、CSRF、回應標頭——都是 SDK 的 isdcsp.web.Site；這裡只決定規則與長相。
    site = web.Site(
        password=lambda: db.kv_get("password_hash"), public=PUBLIC_PATHS, local_only=LOCAL_ONLY_PREFIXES,
        allowed_hosts=lambda: tunnel.hosts() | extra_hosts, port=port,
        store=open_sessions(paths), csp=CSP, cookie="wppt_session",
        title="敬拜 PPT 產生器", default_name="同工",
        page=lambda view: _login_html(view), deny=lambda denial: _deny_html(denial))
    tunnel.on_stop = site.logout_everyone      # 對外連結關掉或斷掉：遠端登入的人全部登出

    @asynccontextmanager
    async def lifespan(_app):
        if autostart_tunnel:
            try:
                tunnel.start()
            except TunnelDriverError as exc:
                log.warning("tunnel autostart failed: %s", exc)
        yield
        tunnel.stop()

    app = FastAPI(title="敬拜 PPT 產生器", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.db, app.state.paths, app.state.tunnel, app.state.site = db, paths, tunnel, site
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.middleware("http")
    async def caching(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        elif path.startswith("/media/"):
            response.headers["Cache-Control"] = "private, max-age=86400"
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.add_middleware(web.Middleware, site=site)      # 最後加的最先跑：每個請求都先經過門口

    def _is_api(path: str) -> bool:
        return path.startswith("/api/")

    # ------------------------------------------------------------------
    # 錯誤
    # ------------------------------------------------------------------
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        if _is_api(request.url.path):
            return JSONResponse({"error": exc.__class__.__name__, "message": exc.message, "hint": exc.hint},
                                status_code=exc.status)
        return templates.TemplateResponse(request, "error.html", _base_ctx(request, message=exc.message, hint=exc.hint),
                                          status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": "validation", "message": "送出的資料格式不對", "hint": str(exc.errors()[:2])},
                            status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("unhandled error on %s", request.url.path)
        message = "程式出了點問題"
        hint = "請把這個畫面截圖給維護的同工。如果剛更新過程式，請關掉黑色視窗重新開一次。"
        if _is_api(request.url.path):
            return JSONResponse({"error": "internal", "message": message, "hint": hint}, status_code=500)
        return templates.TemplateResponse(request, "error.html", _base_ctx(request, message=message, hint=hint),
                                          status_code=500)

    # ------------------------------------------------------------------
    # 頁面共用
    # ------------------------------------------------------------------
    def _is_local(request: Request) -> bool:
        client = web.client(request)
        return bool(client and client.is_local)

    def _actor(request: Request) -> dict | None:
        who = isdcsp.principal(request)
        if who is None or who.kind == "anonymous":
            return None
        if who.kind == "owner":
            return {"name": "本機", "local": True}
        return {"name": who.name or "同工", "local": False}

    def _actor_name(request: Request) -> str:
        return (_actor(request) or {}).get("name", "")

    def _base_ctx(request: Request, **ctx) -> dict:
        local = _is_local(request)
        ua = request.headers.get("user-agent", "")
        return {
            "actor": _actor(request), "is_local": local, "csrf_token": web.csrf_token(request),
            "tunnel": tunnel.status() if local else None,
            "flash": request.query_params.get("msg"), "flash_level": request.query_params.get("level", "ok"),
            "in_app_browser": any(m in ua for m in IN_APP_MARKERS), "nav": ctx.pop("nav", ""), **ctx,
        }

    def page(request: Request, name: str, nav: str, **ctx) -> HTMLResponse:
        return templates.TemplateResponse(request, name, _base_ctx(request, nav=nav, **ctx))

    # ------------------------------------------------------------------
    # 登入頁與擋下來的頁面：邏輯是 SDK 的（isdcsp.web.Site），長相與用字是這裡的
    # ------------------------------------------------------------------
    def _render(template: str, scope: dict, **ctx) -> str:
        request = Request(scope)
        return templates.get_template(template).render({**_base_ctx(request, **ctx), "request": request})

    def _login_html(view: web.LoginView) -> str:
        if view.error == "wrong":
            error = "密碼不對，再試一次。"
        elif view.error == "throttled":
            error = f"密碼錯太多次了，請 {max(1, view.wait_seconds // 60)} 分鐘後再試。"
        else:
            error = view.message
        return _render("login.html", view.scope, next=view.next, error=error, name=view.name)

    def _deny_html(denial: web.Denial) -> str:
        template, message, hint = DENY_PAGES.get(denial.reason, ("error.html", denial.message, denial.hint))
        return _render(template, denial.scope, message=message, hint=hint)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__}

    # ------------------------------------------------------------------
    # 頁面
    # ------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        settings = store.get_settings(db)
        legacy_file = paths.legacy_file
        return page(request, "index.html", "index", dash=store.dashboard(db), settings=settings,
                    legacy_available=legacy_file.exists(), today=date.today().isoformat())

    @app.get("/services", response_class=HTMLResponse)
    def services_page(request: Request):
        return page(request, "services.html", "services", services=store.list_services(db),
                    today=date.today().isoformat(), next_sunday=_next_sunday().isoformat())

    @app.get("/services/{service_id}", response_class=HTMLResponse)
    def service_page(request: Request, service_id: int):
        service = store.get_service(db, service_id)
        data = {"service": service, **_library_payload()}
        return page(request, "service.html", "services", service=service, data=data)

    @app.get("/import", response_class=HTMLResponse)
    def import_page(request: Request, service: int | None = None):
        target = store.get_service(db, service) if service else None
        return page(request, "import.html", "import", settings=store.get_settings(db), target=target)

    @app.get("/songs", response_class=HTMLResponse)
    def songs_page(request: Request):
        return page(request, "songs.html", "songs", songs=store.list_songs(db, limit=5000))

    @app.get("/songs/{song_id}", response_class=HTMLResponse)
    def song_page(request: Request, song_id: int):
        song = store.get_song(db, song_id)
        history = store.song_history(db, song_id)
        return page(request, "song.html", "songs", song=song, history=history,
                    data={"song": song, **_library_payload()})

    @app.get("/backgrounds", response_class=HTMLResponse)
    def backgrounds_page(request: Request):
        return page(request, "backgrounds.html", "backgrounds", data=_library_payload(include_archived=True))

    @app.get("/styles", response_class=HTMLResponse)
    def styles_page(request: Request):
        return page(request, "styles.html", "styles", data=_library_payload(include_archived=True))

    @app.get("/exports", response_class=HTMLResponse)
    def exports_page(request: Request):
        return page(request, "exports.html", "exports", exports=store.list_exports(db))

    @app.get("/exports/{export_id}/download")
    def export_download(export_id: int):
        rec = store.get_export(db, export_id)
        file = (paths.exports_dir / rec["file"]).resolve()
        if paths.exports_dir.resolve() not in file.parents or not file.is_file():
            raise NotFound("這個 PPT 檔已經不在了", "可以回到歌單重新匯出一次。")
        return FileResponse(file, media_type=PPTX_TYPE, filename=rec["filename"])

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request):
        local = _is_local(request)
        return page(request, "settings.html", "settings", settings=store.get_settings(db),
                    has_password=bool(db.kv_get("password_hash")),
                    sessions=[s.public() for s in site.sessions.active()] if local else [],
                    themes=store.list_themes(db), styles=store.list_styles(db),
                    legacy_path=str(paths.legacy_file), data_dir=str(paths.data_dir), port=port)

    @app.get("/help", response_class=HTMLResponse)
    def help_page(request: Request):
        return page(request, "help.html", "help")

    @app.get("/media/{image_id}")
    def media(image_id: str, w: int = 0):
        image = store.get_image(db, image_id)
        if w:
            path = imagestore.thumbnail(paths.images_dir, paths.thumbs_dir, image["id"], image["ext"], w)
        else:
            path = imagestore.image_path(paths.images_dir, image["id"], image["ext"])
        if not path.is_file():
            raise NotFound("圖片檔不見了")
        media_type = "image/jpeg" if path.suffix == ".jpg" else "image/png"
        return FileResponse(path, media_type=media_type, headers={"Content-Disposition": "inline"})

    def _library_payload(include_archived: bool = False) -> dict:
        return {"themes": store.list_themes(db, include_archived), "styles": store.list_styles(db, include_archived),
                "settings": {k: v for k, v in store.get_settings(db).items() if k != "cloudflared_path"}}

    # ------------------------------------------------------------------
    # JSON API
    # ------------------------------------------------------------------
    api = APIRouter(prefix="/api")

    @api.get("/nav")
    def nav_status(request: Request):
        dash = store.dashboard(db)
        counts = dash["counts"] or {}
        up = dash["upcoming"]
        out = {
            "index": {"sub": f"下一場：{up['date'][5:].replace('-', '/')} {up['name']}" if up else "還沒有接下來的歌單"},
            "services": {"count": counts.get("services") or ""},
            "songs": {"count": counts.get("songs") or ""},
            "backgrounds": {"count": counts.get("themes") or ""},
            "styles": {"count": counts.get("styles") or ""},
            "exports": {"count": counts.get("exports") or ""},
        }
        if not store.get_settings(db)["gdoc_url"]:
            out["import"] = {"sub": "還沒設定文件網址", "tone": "warn"}
        if _is_local(request):
            st = tunnel.status()
            if st["state"] == "running":
                out["settings"] = {"sub": "對外連結開著", "tone": "ok"}
            elif st["state"] == "error":
                out["settings"] = {"sub": "對外連結中斷了", "tone": "bad"}
        return out

    @api.get("/library")
    def library():
        return _library_payload()

    # ---------- 歌單 ----------
    @api.get("/services")
    def api_services():
        return store.list_services(db)

    @api.post("/services")
    def api_create_service(request: Request, body: dict = Body(...)):
        return store.create_service(db, body, _actor_name(request))

    @api.get("/services/{service_id}")
    def api_service(service_id: int):
        return store.get_service(db, service_id)

    @api.patch("/services/{service_id}")
    def api_update_service(request: Request, service_id: int, body: dict = Body(...)):
        return store.update_service(db, service_id, body, body.get("version"), _actor_name(request))

    @api.delete("/services/{service_id}")
    def api_delete_service(service_id: int):
        store.delete_service(db, service_id)
        return {"ok": True}

    @api.post("/services/{service_id}/duplicate")
    def api_duplicate_service(request: Request, service_id: int, body: dict = Body(default={})):
        new_date = body.get("date") or _next_sunday().isoformat()
        return store.duplicate_service(db, service_id, new_date, _actor_name(request))

    @api.post("/services/{service_id}/items")
    def api_add_item(request: Request, service_id: int, body: dict = Body(default={})):
        return store.add_item(db, service_id, body, _actor_name(request))

    @api.post("/services/{service_id}/reorder")
    def api_reorder(request: Request, service_id: int, body: dict = Body(...)):
        return store.reorder_items(db, service_id, body.get("itemIds") or [], _actor_name(request))

    @api.post("/services/{service_id}/apply")
    def api_apply(request: Request, service_id: int, body: dict = Body(...)):
        return store.apply_look(db, service_id, body, _actor_name(request))

    @api.post("/services/{service_id}/gdoc")
    def api_reimport(request: Request, service_id: int, body: dict = Body(default={})):
        service = store.get_service(db, service_id)
        url = body.get("url") or service["sourceUrl"] or store.get_settings(db)["gdoc_url"]
        if not url:
            raise AppError("不知道要讀哪一份 Google 文件", "請先到「從 Google 文件匯入」貼上文件網址。")
        sheet = fetch_sheet(url)
        return store.import_doc(db, sheet, service_id, _actor_name(request))

    @api.post("/services/{service_id}/export")
    def api_export(request: Request, service_id: int):
        by = _actor_name(request)
        resolved = store.resolve_service(db, service_id)
        if not resolved["songs"]:
            raise AppError("歌單裡還沒有歌", "先加幾首歌再匯出。")
        buf, count, warnings = pptx_builder.build(resolved, paths.images_dir)
        data = buf.getvalue()
        svc = resolved["service"]
        rel = f"{svc['date'][:4]}/{store.timestamp_slug()}_{service_id}.pptx"
        target = paths.exports_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        rec = store.record_export(db, svc, store.export_filename(svc), rel, count, len(data), resolved, warnings, by)
        synced = store.sync_library(db, service_id, by)
        return {"export": rec, "downloadUrl": f"/exports/{rec['id']}/download", "warnings": warnings,
                "library": synced, "service": store.get_service(db, service_id)}

    @api.get("/services/{service_id}/resolved")
    def api_resolved(service_id: int):
        return store.resolve_service(db, service_id)

    # ---------- 歌單裡的歌 ----------
    @api.patch("/items/{item_id}")
    def api_update_item(request: Request, item_id: int, body: dict = Body(...)):
        return store.update_item(db, item_id, body, body.get("version"), _actor_name(request))

    @api.delete("/items/{item_id}")
    def api_delete_item(request: Request, item_id: int):
        store.delete_item(db, item_id, _actor_name(request))
        return {"ok": True}

    @api.post("/items/{item_id}/to-library")
    def api_item_to_library(request: Request, item_id: int):
        item = store.get_item(db, item_id)
        report = store.sync_library(db, item["serviceId"], _actor_name(request), item_ids=[item_id])
        return {"report": report, "item": store.get_item(db, item_id)}

    # ---------- Google 文件 ----------
    @api.post("/gdoc/preview")
    def api_gdoc_preview(body: dict = Body(...)):
        url = (body.get("url") or store.get_settings(db)["gdoc_url"] or "").strip()
        if not url:
            raise AppError("請先貼上 Google 文件的網址")
        sheet = fetch_sheet(url)
        songs = []
        for s in sheet.songs:
            lib = store.find_song(db, s.title)
            songs.append({**s.__dict__, "missing": label_mismatches(s),
                          "library": {"id": lib["id"], "title": lib["title"],
                                      "lyricsChanged": lib["lyrics"].strip() != s.lyrics.strip()} if lib else None})
        existing = [x for x in store.list_services(db) if sheet.date and x["date"] == sheet.date]
        return {"sheet": {**sheet.to_dict(), "songs": songs}, "sameDate": existing}

    @api.post("/gdoc/import")
    def api_gdoc_import(request: Request, body: dict = Body(...)):
        url = (body.get("url") or store.get_settings(db)["gdoc_url"] or "").strip()
        if not url:
            raise AppError("請先貼上 Google 文件的網址")
        sheet = fetch_sheet(url)
        if body.get("date"):
            sheet.date = store._clean_date(body["date"])
        if body.get("remember", True):
            store.save_settings(db, {"gdoc_url": url})
        service_id = store._opt_id(body.get("serviceId"))
        return store.import_doc(db, sheet, service_id, _actor_name(request))

    # ---------- 詩歌庫 ----------
    @api.get("/songs")
    def api_songs(q: str = "", limit: int = 50):
        return store.list_songs(db, q, limit=max(1, min(limit, 5000)))

    @api.post("/songs")
    def api_create_song(request: Request, body: dict = Body(...)):
        return store.create_song(db, body, _actor_name(request))

    @api.get("/songs/{song_id}")
    def api_song(song_id: int):
        return {**store.get_song(db, song_id), "history": store.song_history(db, song_id)}

    @api.patch("/songs/{song_id}")
    def api_update_song(request: Request, song_id: int, body: dict = Body(...)):
        return store.update_song(db, song_id, body, _actor_name(request))

    @api.delete("/songs/{song_id}")
    def api_delete_song(song_id: int):
        store.delete_song(db, song_id)
        return {"ok": True}

    @api.post("/songs/{song_id}/restore/{revision_id}")
    def api_restore(request: Request, song_id: int, revision_id: int):
        return store.restore_revision(db, song_id, revision_id, _actor_name(request))

    # ---------- 背景 ----------
    @api.get("/themes")
    def api_themes(archived: bool = False):
        return store.list_themes(db, archived)

    @api.post("/themes")
    def api_create_theme(body: dict = Body(...)):
        return store.create_theme(db, body)

    @api.patch("/themes/{theme_id}")
    def api_update_theme(theme_id: int, body: dict = Body(...)):
        return store.update_theme(db, theme_id, body)

    @api.delete("/themes/{theme_id}")
    def api_delete_theme(theme_id: int):
        return {"result": store.delete_theme(db, theme_id)}

    @api.post("/images")
    async def api_upload(request: Request, file: UploadFile = File(...), theme: int = 1):
        chunks, total = [], 0
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > imagestore.MAX_UPLOAD_BYTES:
                raise AppError("圖片太大了（上限 25MB）", "請先把圖片縮小一點再上傳。", status=413)
            chunks.append(chunk)
        return store.add_image(db, paths, b"".join(chunks), file.filename or "圖片", _actor_name(request),
                               create_theme=bool(theme))

    # ---------- 排版 ----------
    @api.get("/styles")
    def api_styles(archived: bool = False):
        return store.list_styles(db, archived)

    @api.post("/styles")
    def api_create_style(body: dict = Body(...)):
        return store.create_style(db, body)

    @api.patch("/styles/{style_id}")
    def api_update_style(style_id: int, body: dict = Body(...)):
        return store.update_style(db, style_id, body)

    @api.post("/styles/{style_id}/duplicate")
    def api_duplicate_style(style_id: int):
        return store.duplicate_style(db, style_id)

    @api.delete("/styles/{style_id}")
    def api_delete_style(style_id: int):
        return {"result": store.delete_style(db, style_id)}

    # ---------- 匯出紀錄 ----------
    @api.get("/exports")
    def api_exports():
        return store.list_exports(db)

    @api.get("/exports/{export_id}")
    def api_export_detail(export_id: int):
        return store.get_export(db, export_id, with_snapshot=True)

    # ---------- 設定 ----------
    @api.get("/settings")
    def api_settings(request: Request):
        settings = store.get_settings(db)
        if not _is_local(request):
            settings.pop("cloudflared_path", None)
        return settings

    @api.patch("/settings")
    def api_save_settings(request: Request, body: dict = Body(...)):
        if not _is_local(request):
            body = {k: v for k, v in body.items() if k != "cloudflared_path"}
        return store.save_settings(db, body)

    @api.post("/settings/password")
    def api_set_password(body: dict = Body(...)):
        password = str(body.get("password") or "")
        if body.get("clear"):
            with db.tx() as conn:
                conn.execute("DELETE FROM kv WHERE key='password_hash'")
            site.logout_everyone()
            return {"ok": True, "hasPassword": False}
        if len(password) < 6:
            raise AppError("密碼至少要 6 個字", "建議用一句好記的話，例如「每週都要敬拜2026」。")
        db.kv_set("password_hash", passwords.hash_password(password))
        site.logout_everyone()
        return {"ok": True, "hasPassword": True}

    @api.get("/sessions")
    def api_sessions():
        return [s.public() for s in site.sessions.active()]

    @api.post("/sessions/clear")
    def api_clear_sessions():
        return {"removed": site.logout_everyone()}

    @api.get("/tunnel")
    def api_tunnel():
        return {**tunnel.status(), "hasPassword": bool(db.kv_get("password_hash"))}

    @api.post("/tunnel/start")
    def api_tunnel_start():
        if not db.kv_get("password_hash"):
            raise AppError("請先設定團隊密碼", "沒有密碼就開對外連結，拿到網址的人都能改資料。先在下面設定密碼。")
        try:
            return tunnel.start()
        except TunnelDriverError as exc:
            raise AppError(str(exc), INSTALL_HINT) from exc

    @api.post("/tunnel/stop")
    def api_tunnel_stop():
        return tunnel.stop()

    @api.get("/tunnel/qr.svg")
    def api_tunnel_qr():
        url = tunnel.status()["url"]
        if not url:
            raise NotFound("對外連結還沒開")
        import qrcode
        import qrcode.image.svg

        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return Response(buf.getvalue(), media_type="image/svg+xml")

    @api.post("/legacy/import")
    def api_legacy(request: Request, body: dict = Body(default={})):
        path = str(body.get("path") or paths.legacy_file)
        return legacy.import_file(db, paths, path, _actor_name(request))

    @api.post("/backup")
    def api_backup():
        dest = backup.run_backup(paths)
        return {"file": str(dest), "bytes": dest.stat().st_size}

    app.include_router(api)
    return app


def _next_sunday(today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=(6 - today.weekday()) % 7)
