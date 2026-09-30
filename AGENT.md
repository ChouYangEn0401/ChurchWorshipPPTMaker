# AGENT.md — notes for AI assistants working on this repo

Church worship PPT maker. Two apps live here:

- **Web app** (`src/worship_ppt/`, Python 3.11, FastAPI + Jinja2 + vanilla JS, SQLite). This is the one being developed.
- **Desktop app** (`legacy/desktop/main.py`, tkinter). Frozen legacy; don't extend it. Its save file (`ppt_settings.json`)
  is importable into the web app (`legacy.py`).

User-facing text (UI, errors, docs, README, CHANGELOG) is Traditional Chinese written for non-technical church
volunteers; every error carries a "what to do next" hint (`errors.AppError(message, hint)`). Code identifiers are
English; comments/docstrings are Chinese, matching the existing files.

## Run / test

```bat
run.bat                              :: first run installs (.venv + deps + init), then http://127.0.0.1:8788
run_public.bat                       :: same + Cloudflare quick tunnel
python main.py [web|init|import-gdoc|…]  :: root entry point; re-runs itself with .venv if deps are missing
.venv\Scripts\python.exe -m pytest -q
```

Tests use a temp `WORSHIP_PPT_HOME` (see `tests/conftest.py`); never point them at the real `data/`.
`tests/test_js_parity.py` needs `node` (skipped otherwise).

## Map

| Module | Role |
|---|---|
| `lyrics.py` | Lyrics → sections → pages; 歌序 parsing/aliases; slide plan; font-size fit + phrase wrapping |
| `static/js/lyrics.js` | **Line-by-line port of `lyrics.py`** for the live preview |
| `gdoc.py` | Fetch a public Google Doc (`/export?format=html`) and parse the song table |
| `store.py` | All DB reads/writes (songs, services + items, themes, styles, exports, settings, import, library sync) |
| `db.py` | SQLite wrapper; append-only `MIGRATIONS`, version in `PRAGMA user_version` |
| `pptx_builder.py` | Build .pptx: one cloned slide layout per background (image/colour + overlay), text boxes, notes |
| `images.py` | Upload normalisation (sha256 ids, WebP→JPG/PNG, downscale), thumbnails |
| `security.py` | local vs tunnel classification, Host allowlist, scrypt passwords, DB sessions, login throttle, headers |
| `tunnel.py` | cloudflared quick tunnel lifecycle (URL parsed from stderr) |
| `web/app.py` | `create_app()`: the `gate` middleware, pages, `/api/*` |

## Invariants — keep these true

1. **Preview = export.** Any change to page splitting, sequence rules, `fit_lines`, `header_scale`, `title_page_size`
   or `char_em` must be made in both `lyrics.py` and `static/js/lyrics.js`; `test_js_parity.py` compares them.
   Avoid float operations that differ between Python and JS (e.g. `round()` ties).
2. **Server binds 127.0.0.1 only** with `proxy_headers=False`. Remote = any Cloudflare header or non-loopback Host.
   Remote requests need a DB session (team password); with no password set, remote is refused entirely.
3. **Host allowlist**: loopback, or the *current* tunnel hostname (`TunnelManager.current_host()`), else 421.
4. Every non-GET request must be same-origin; remote ones also need `X-CSRF-Token` (except `/login`, `/logout` forms).
   Local-only API prefixes are in `LOCAL_ONLY_PREFIXES`.
5. Never render user data as HTML: Jinja autoescape; JS builds DOM with `el()`/`textContent`. No inline `<script>`
   (CSP `script-src 'self'`); page data goes through `<script type="application/json" id="page-data">`.
6. Service items are **snapshots** (lyrics/sequence/look copied from the library). The library (`songs`) is updated
   from a service only on export or explicit "存到詩歌庫" (`store.sync_library`), writing a `song_revisions` row
   whenever lyrics/sequence change. Items and services carry a `version`; stale writes raise `Conflict` (409).
7. Themes/styles that are referenced are archived, not deleted (old services and export snapshots stay renderable).
8. Schema changes: append a new `(version, sql)` to `db.MIGRATIONS`; never edit an old one. No `;` inside SQL literals.
9. `.bat` files are CRLF and start with `chcp 65001` via `_env.bat`; `requirements*.txt` stay ASCII-only.
