"""指令列入口：python -m worship_ppt [指令]

    web            打開網頁（沒寫指令時預設就是這個）
    web --public   打開網頁，並且同時開啟 Cloudflare 對外連結
    init           建立資料庫（安裝時跑一次；可以順便 --gdoc-url 設定文件網址）
    password       設定團隊密碼（從外面連進來時要輸入）
    import-gdoc    從 Google 文件匯入這週歌單
    import-legacy  匯入桌面版的 ppt_settings.json
    export ID      把某一份歌單匯出成 PPT
    backup         備份資料到 backups/
"""

from __future__ import annotations

import argparse
import getpass
import logging
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .errors import AppError
from .paths import Paths

DEFAULT_PORT = 8788


def _setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _setup_logging(paths: Paths) -> None:
    paths.ensure()
    handler = RotatingFileHandler(paths.logs_dir / "worship-ppt.log", maxBytes=1_000_000, backupCount=5,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for noisy in ("httpx", "httpcore", "PIL", "multipart", "python_multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _copy_to_clipboard(text: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def cmd_web(args, paths: Paths) -> int:
    import uvicorn

    from .web.app import create_app

    url = f"http://127.0.0.1:{args.port}"
    if _port_in_use(args.port):
        print(f"敬拜 PPT 產生器已經開著了（{url}），幫你打開瀏覽器。")
        if args.public:
            print("要開對外連結，請到網頁的「設定 → 對外連結」按「開啟」。")
        if not args.no_browser:
            webbrowser.open(url + ("/settings#public" if args.public else "/"))
        return 0

    app = create_app(paths, port=args.port, autostart_tunnel=args.public)
    print(f"⛪ 敬拜 PPT 產生器 v{__version__}")
    print(f"   本機網址：{url}")
    print(f"   資料位置：{paths.data_dir}")
    if not args.public:
        print("   要讓同工從外面一起編輯：到網頁的「設定 → 對外連結」按「開啟」。")
    print("   關掉這個視窗就會停止。")

    if args.public:
        def announce():
            tunnel = app.state.tunnel
            time.sleep(1.0)
            status = tunnel.wait_until_ready(75)
            if status["state"] == "running":
                copied = _copy_to_clipboard(status["url"])
                print()
                print(f"✅ 對外網址：{status['url']}")
                print("   把這個網址傳給同工（LINE 群組），他們輸入團隊密碼就能一起編輯。" +
                      ("（已經複製到剪貼簿）" if copied else ""))
                print("   關掉這個視窗，網址就會失效。")
            else:
                print()
                print(f"❌ 對外連結沒有開起來：{status['error'] or '請看 data/logs/cloudflared.log'}")
                print("   網頁本身還是可以在這台電腦上用。")

        threading.Thread(target=announce, daemon=True).start()

    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url + ("/settings#public" if args.public else "/"))).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", proxy_headers=False,
                forwarded_allow_ips="", server_header=False, access_log=False)
    return 0


def cmd_init(args, paths: Paths) -> int:
    from . import store

    db = store.open_db(paths)
    if args.gdoc_url:
        store.save_settings(db, {"gdoc_url": args.gdoc_url})
        print("✅ 已設定 Google 文件網址")
    print(f"✅ 資料庫準備好了：{paths.db_file}")
    return 0


def cmd_password(args, paths: Paths) -> int:
    from . import security, store

    db = store.open_db(paths)
    if args.clear:
        with db.tx() as conn:
            conn.execute("DELETE FROM kv WHERE key='password_hash'")
        security.delete_all_sessions(db)
        print("✅ 已清除團隊密碼（外面的人會完全連不進來）")
        return 0
    first = getpass.getpass("新的團隊密碼（輸入時不會顯示）：")
    second = getpass.getpass("再輸入一次：")
    if first != second:
        print("❌ 兩次不一樣，沒有改")
        return 1
    if len(first) < 6:
        print("❌ 密碼至少要 6 個字")
        return 1
    db.kv_set("password_hash", security.hash_password(first))
    security.delete_all_sessions(db)
    print("✅ 團隊密碼已設定（之前登入的人要重新登入）")
    return 0


def cmd_import_gdoc(args, paths: Paths) -> int:
    from . import store
    from .gdoc import fetch_sheet

    db = store.open_db(paths)
    url = args.url or store.get_settings(db)["gdoc_url"]
    if not url:
        raise AppError("不知道要讀哪一份 Google 文件", "加上 --url https://docs.google.com/document/d/…")
    sheet = fetch_sheet(url)
    if args.date:
        sheet.date = args.date
    service = store.import_doc(db, sheet, None, "指令列")
    store.save_settings(db, {"gdoc_url": url})
    print(f"✅ 建立歌單 #{service['id']}：{service['date']} {service['name']}")
    for item in service["items"]:
        print(f"   - {item['title']}（歌序：{item['sequence'] or '照歌詞順序'}）")
    for warning in sheet.warnings:
        print(f"⚠️ {warning}")
    return 0


def cmd_import_legacy(args, paths: Paths) -> int:
    from . import legacy, store

    db = store.open_db(paths)
    result = legacy.import_file(db, paths, args.path or paths.legacy_file, "指令列")
    print(f"✅ 匯入 {len(result['songs'])} 首歌，歌單 #{result['serviceId']}")
    if result["missingImages"]:
        print("⚠️ 找不到這些背景圖：" + "、".join(result["missingImages"]))
    return 0


def cmd_export(args, paths: Paths) -> int:
    from . import pptx_builder, store

    db = store.open_db(paths)
    resolved = store.resolve_service(db, args.service_id)
    buf, count, warnings = pptx_builder.build(resolved, paths.images_dir)
    out = Path(args.out) if args.out else Path.cwd() / store.export_filename(resolved["service"])
    out.write_bytes(buf.getvalue())
    print(f"✅ {count} 張投影片 → {out}")
    for warning in warnings:
        print(f"⚠️ {warning}")
    return 0


def cmd_backup(args, paths: Paths) -> int:
    from . import backup, store

    store.open_db(paths)
    dest = backup.run_backup(paths)
    print(f"✅ 備份好了：{dest}（{dest.stat().st_size // 1024} KB）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="worship_ppt", description="教會敬拜 PPT 產生器（網頁版）")
    sub = parser.add_subparsers(dest="cmd")

    web = sub.add_parser("web", help="打開網頁")
    web.add_argument("--port", type=int, default=DEFAULT_PORT)
    web.add_argument("--no-browser", action="store_true", help="不要自動開瀏覽器")
    web.add_argument("--public", action="store_true", help="同時開啟 Cloudflare 對外連結")
    web.set_defaults(func=cmd_web)

    init = sub.add_parser("init", help="建立資料庫")
    init.add_argument("--gdoc-url", default="")
    init.set_defaults(func=cmd_init)

    pw = sub.add_parser("password", help="設定團隊密碼")
    pw.add_argument("--clear", action="store_true", help="清除密碼（外面完全連不進來）")
    pw.set_defaults(func=cmd_password)

    gd = sub.add_parser("import-gdoc", help="從 Google 文件匯入這週歌單")
    gd.add_argument("--url", default="")
    gd.add_argument("--date", default="", help="聚會日期，例如 2026-10-11（不填就用文件上寫的）")
    gd.set_defaults(func=cmd_import_gdoc)

    lg = sub.add_parser("import-legacy", help="匯入桌面版的存檔")
    lg.add_argument("path", nargs="?", default="", help="不填就讀 legacy/desktop/ppt_settings.json")
    lg.set_defaults(func=cmd_import_legacy)

    ex = sub.add_parser("export", help="把歌單匯出成 PPT")
    ex.add_argument("service_id", type=int)
    ex.add_argument("--out", default="")
    ex.set_defaults(func=cmd_export)

    bk = sub.add_parser("backup", help="備份資料")
    bk.set_defaults(func=cmd_backup)
    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        args = parser.parse_args(["web", *(argv or sys.argv[1:])])
    paths = Paths.discover()
    _setup_logging(paths)
    try:
        return args.func(args, paths)
    except AppError as exc:
        print(f"❌ {exc.message}")
        if exc.hint:
            print(f"   → {exc.hint}")
        return 2
    except KeyboardInterrupt:
        return 0
