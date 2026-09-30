import pytest

from worship_ppt import legacy, store
from worship_ppt.errors import AppError, Conflict


def test_first_run_has_presets(db):
    styles = store.list_styles(db)
    themes = store.list_themes(db)
    assert len(styles) == 3 and len(themes) == 2
    settings = store.get_settings(db)
    assert settings["default_style_id"] == styles[0]["id"]
    assert store.get_theme(db, settings["default_theme_id"])["name"] == "純黑底"


def test_import_doc_creates_service_with_items(db, sheet):
    svc = store.import_doc(db, sheet, by="小明")
    assert svc["date"] == "2026-10-11"
    assert [i["title"] for i in svc["items"]] == ["神同在", "常常喜樂", "盼望聖靈", "聖靈請祢來充滿我心"]
    assert all(i["songId"] is None for i in svc["items"])
    assert svc["items"][0]["updatedBy"] == "小明"


def test_export_sync_adds_songs_then_reuses_their_look(db, sheet):
    svc = store.import_doc(db, sheet)
    special = store.create_theme(db, {"name": "山", "bgColor": "#223344"})
    store.update_item(db, svc["items"][0]["id"], {"themeId": special["id"]}, None)
    report = store.sync_library(db, svc["id"])
    assert [r["action"] for r in report] == ["added"] * 4
    song = store.find_song(db, "神同在")
    assert song["theme_id"] == special["id"]
    # 下一週再匯入同一份文件：詩歌庫有這首歌 → 自動用上次的背景
    svc2 = store.import_doc(db, sheet)
    first = svc2["items"][0]
    assert first["songId"] == song["id"] and first["themeId"] == special["id"]
    assert svc2["importReport"][0]["inLibrary"] is True


def test_lyrics_change_keeps_a_revision(db, sheet):
    svc = store.import_doc(db, sheet)
    store.sync_library(db, svc["id"])
    item = store.get_service(db, svc["id"])["items"][0]
    store.update_item(db, item["id"], {"lyrics": "[副]\n新的歌詞"}, item["version"])
    report = store.sync_library(db, svc["id"])
    assert report[0]["action"] == "updated"
    history = store.song_history(db, item["songId"] or store.find_song(db, "神同在")["id"])
    assert history["revisions"][0]["lyrics"].startswith("[主]")
    restored = store.restore_revision(db, store.find_song(db, "神同在")["id"], history["revisions"][0]["id"])
    assert restored["lyrics"].startswith("[主]")


def test_item_version_conflict_is_detected(db, sheet):
    svc = store.import_doc(db, sheet)
    item = svc["items"][0]
    store.update_item(db, item["id"], {"lyrics": "A"}, item["version"], by="小明")
    with pytest.raises(Conflict) as exc:
        store.update_item(db, item["id"], {"lyrics": "B"}, item["version"], by="小華")
    assert "小明" in exc.value.message


def test_reimport_keeps_chosen_look_and_drops_removed_songs(db, sheet):
    svc = store.import_doc(db, sheet)
    special = store.create_theme(db, {"name": "特別"})
    store.update_item(db, svc["items"][1]["id"], {"themeId": special["id"]}, None)
    sheet.songs = sheet.songs[1:3]
    again = store.import_doc(db, sheet, svc["id"])
    assert [i["title"] for i in again["items"]] == ["常常喜樂", "盼望聖靈"]
    assert again["items"][0]["themeId"] == special["id"]


def test_alias_title_in_doc_does_not_rename_library_song(db, sheet):
    svc = store.import_doc(db, sheet)
    store.sync_library(db, svc["id"])
    song = store.find_song(db, "聖靈請祢來充滿我心")
    store.update_song(db, song["id"], {"aliases": "聖靈請祢來"})
    sheet.songs = [sheet.songs[3]]
    sheet.songs[0].title = "聖靈請祢來"
    svc2 = store.import_doc(db, sheet)
    assert svc2["items"][0]["songId"] == song["id"]
    store.sync_library(db, svc2["id"])
    assert store.get_song(db, song["id"])["title"] == "聖靈請祢來充滿我心"


def test_title_key_ignores_spacing_and_punctuation():
    assert store.title_key("常常 喜樂！") == store.title_key("常常喜樂")
    assert store.title_key("Way Maker") == store.title_key("way-maker")


def test_used_theme_is_archived_not_deleted(db, sheet):
    svc = store.import_doc(db, sheet)
    unused = store.create_theme(db, {"name": "沒用過"})
    used = store.create_theme(db, {"name": "用過"})
    store.update_item(db, svc["items"][0]["id"], {"themeId": used["id"]}, None)
    assert store.delete_theme(db, unused["id"]) == "deleted"
    assert store.delete_theme(db, used["id"]) == "archived"
    assert store.get_theme(db, used["id"])["archived"] is True


def test_last_style_cannot_be_deleted(db):
    styles = store.list_styles(db)
    for s in styles[:-1]:
        store.delete_style(db, s["id"])
    with pytest.raises(AppError):
        store.delete_style(db, styles[-1]["id"])


def test_reorder_duplicate_and_apply(db, sheet):
    svc = store.import_doc(db, sheet)
    ids = [i["id"] for i in svc["items"]]
    after = store.reorder_items(db, svc["id"], list(reversed(ids)))
    assert [i["id"] for i in after["items"]] == list(reversed(ids))
    style = store.list_styles(db)[1]
    applied = store.apply_look(db, svc["id"], {"styleId": style["id"]})
    assert {i["styleId"] for i in applied["items"]} == {style["id"]}
    copy = store.duplicate_service(db, svc["id"], "2026-10-18")
    assert copy["date"] == "2026-10-18" and [i["title"] for i in copy["items"]] == [i["title"] for i in after["items"]]


def test_style_values_are_sanitised(db):
    s = store.create_style(db, {"name": "x", "lyrics": {"size": 9999, "color": "red", "font": ""},
                                "lyricsAlign": "justify", "maxLines": -3})
    assert s["lyrics"]["size"] == 200 and s["lyrics"]["color"] == "#FFFFFF"
    assert s["lyricsAlign"] == "center" and s["maxLines"] == 0


def test_legacy_import(db, paths, legacy_files):
    result = legacy.import_file(db, paths, legacy_files)
    assert result["songs"] == ["新酒", "永遠掌權", "豐盛的應許", "一顆謙卑的心", "醫治的愛"]
    assert result["missingImages"] == []
    svc = store.get_service(db, result["serviceId"])
    assert len(svc["items"]) == 5 and svc["followSequence"] is False
    # 同一張圖只存一份
    assert len([t for t in store.list_themes(db) if t["image"]]) == 5
    # 再匯入一次不會重複建歌
    legacy.import_file(db, paths, legacy_files)
    assert len(store.list_songs(db)) == 5
