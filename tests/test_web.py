"""網頁：本機不用登入、遠端要密碼、各種擋法（Host、CSRF、只限本機的功能）。"""

import httpx
import pytest
from fastapi.testclient import TestClient

from worship_ppt import security, store

from .conftest import LOCAL_BASE, TUNNEL_HOST, remote_client

PAGES = ["/", "/services", "/import", "/songs", "/backgrounds", "/styles", "/exports", "/settings", "/help"]


@pytest.fixture
def seeded(app, sheet):
    db = app.state.db
    svc = store.import_doc(db, sheet, by="test")
    return svc


def set_password(app, pw="敬拜團密碼123"):
    app.state.db.kv_set("password_hash", security.hash_password(pw, n=2 ** 10))
    return pw


def login(app, client: TestClient, pw: str, name="小華"):
    r = client.post("/login", data={"password": pw, "name": name, "next": "/"})
    assert r.status_code == 303, r.text
    page = client.get("/")
    token = page.text.split('name="csrf-token" content="')[1].split('"')[0]
    client.headers["X-CSRF-Token"] = token
    return token


# ---------------------------------------------------------------------------
# 本機
# ---------------------------------------------------------------------------

def test_local_pages_render_without_login(local, seeded):
    for path in PAGES + [f"/services/{seeded['id']}"]:
        r = local.get(path)
        assert r.status_code == 200, path
        assert "Content-Security-Policy" in r.headers


def test_local_full_flow_export_and_download(local, seeded, app):
    item = seeded["items"][0]
    r = local.patch(f"/api/items/{item['id']}", json={"lyrics": "[副]\n改過的歌詞", "version": item["version"]})
    assert r.status_code == 200 and r.json()["updatedBy"] == "本機"
    r = local.post(f"/api/services/{seeded['id']}/export")
    assert r.status_code == 200
    body = r.json()
    assert body["export"]["slides"] > 0
    assert [x["action"] for x in body["library"]] == ["added"] * 4
    dl = local.get(body["downloadUrl"])
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    assert "attachment" in dl.headers["content-disposition"]
    snapshot = local.get(f"/api/exports/{body['export']['id']}").json()["snapshot"]
    assert snapshot["songs"][0]["lyrics"] == "[副]\n改過的歌詞"


def test_stale_version_gets_409_with_who_changed_it(local, seeded):
    item = seeded["items"][0]
    assert local.patch(f"/api/items/{item['id']}", json={"lyrics": "A", "version": item["version"]}).status_code == 200
    r = local.patch(f"/api/items/{item['id']}", json={"lyrics": "B", "version": item["version"]})
    assert r.status_code == 409 and "本機" in r.json()["message"]


def test_cross_site_post_is_blocked_even_locally(app):
    client = TestClient(app, base_url=LOCAL_BASE, headers={"Origin": "https://evil.example"})
    assert client.post("/api/services", json={}).status_code == 403
    no_origin = TestClient(app, base_url=LOCAL_BASE)
    assert no_origin.post("/api/services", json={}).status_code == 403


def test_unknown_host_is_refused(app):
    # DNS rebinding：惡意網域指到 127.0.0.1
    client = TestClient(app, base_url="http://evil.example:8788")
    assert client.get("/").status_code == 421
    # 舊的 / 別人的 trycloudflare 網址
    old = TestClient(app, base_url="https://old-name-here.trycloudflare.com", headers={"cf-connecting-ip": "1.2.3.4"})
    assert old.get("/").status_code == 421


def test_image_upload_and_media(local):
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (1, 2, 3)).save(buf, "JPEG")
    r = local.post("/api/images", files={"file": ("聖誕.jpg", buf.getvalue(), "image/jpeg")})
    assert r.status_code == 200, r.text
    theme = r.json()
    assert theme["name"] == "聖誕"
    thumb = local.get(f"/media/{theme['image']['id']}?w=320")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    bad = local.post("/api/images", files={"file": ("x.jpg", b"not an image", "image/jpeg")})
    assert bad.status_code == 400
    assert local.get("/media/../../worship.db").status_code == 404


# ---------------------------------------------------------------------------
# 遠端（Cloudflare）
# ---------------------------------------------------------------------------

def test_remote_is_closed_until_password_is_set(app):
    client = remote_client(app)
    r = client.get("/")
    assert r.status_code == 403 and "還沒開放" in r.text
    assert client.get("/api/services").status_code == 403


def test_remote_requires_login_then_works(app, seeded):
    pw = set_password(app)
    client = remote_client(app)
    r = client.get(f"/services/{seeded['id']}")
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert client.get("/api/services").status_code == 401
    bad = client.post("/login", data={"password": "錯的", "name": "x", "next": "/"})
    assert bad.status_code == 401
    login(app, client, pw)
    assert client.get(f"/services/{seeded['id']}").status_code == 200
    cookie = client.cookies.get(security.TUNNEL_COOKIE)
    assert cookie
    item = seeded["items"][0]
    r = client.patch(f"/api/items/{item['id']}", json={"key": "G", "version": item["version"]})
    assert r.status_code == 200 and r.json()["updatedBy"] == "小華"


def test_remote_write_needs_csrf_token(app, seeded):
    pw = set_password(app)
    client = remote_client(app)
    login(app, client, pw)
    del client.headers["X-CSRF-Token"]
    item = seeded["items"][0]
    r = client.patch(f"/api/items/{item['id']}", json={"key": "G", "version": item["version"]})
    assert r.status_code == 403


def test_remote_cannot_use_local_only_features(app):
    pw = set_password(app)
    client = remote_client(app)
    login(app, client, pw)
    for path in ("/api/tunnel/start", "/api/settings/password", "/api/backup", "/api/legacy/import", "/api/sessions/clear"):
        assert client.post(path, json={"password": "hijack!!"}).status_code == 403, path
    assert client.get("/api/tunnel").status_code == 403
    settings = client.get("/api/settings").json()
    assert "cloudflared_path" not in settings


def test_login_throttle_blocks_after_repeated_failures(app):
    set_password(app)
    client = remote_client(app, ip="198.51.100.9")
    for _ in range(8):
        client.post("/login", data={"password": "nope", "next": "/"})
    r = client.post("/login", data={"password": "敬拜團密碼123", "next": "/"})
    assert r.status_code == 401 and "錯太多次" in r.text
    other = remote_client(app, ip="198.51.100.10")
    assert other.post("/login", data={"password": "敬拜團密碼123", "next": "/"}).status_code == 303


def test_changing_password_logs_everyone_out(app, local):
    pw = set_password(app)
    client = remote_client(app)
    login(app, client, pw)
    assert local.post("/api/settings/password", json={"password": "新的密碼好長"}).status_code == 200
    assert client.get("/").status_code == 303


def test_open_redirect_is_not_possible(app):
    pw = set_password(app)
    client = remote_client(app)
    r = client.post("/login", data={"password": pw, "next": "//evil.example/x"})
    assert r.headers["location"] == "/"


def test_tunnel_start_needs_password(local):
    r = local.post("/api/tunnel/start")
    assert r.status_code == 400 and "密碼" in r.json()["message"]
