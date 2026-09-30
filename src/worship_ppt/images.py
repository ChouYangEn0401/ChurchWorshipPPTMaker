"""背景圖的存放。

- 依內容的 sha256 命名，同一張圖上傳兩次只存一份。
- 只收看得懂的圖片（用 Pillow 真的打開過）；WebP、BMP、GIF… 一律轉成 PNG / JPEG，
  因為舊版 PowerPoint（例如 2010）打不開 WebP。
- 太大的照片（手機原圖 4000px）縮到長邊 2560px：投影機用不到那麼大，PPT 檔也不會肥到傳不動。
- 縮圖另外存在 thumbs/，網頁清單和預覽用小圖，透過 Cloudflare 從手機看也很快。
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .errors import AppError

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_EDGE = 2560
THUMB_WIDTHS = (320, 960)
IMAGE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

Image.MAX_IMAGE_PIXELS = 80_000_000  # 擋掉故意做出來的超大圖（解壓縮炸彈）


def _is_valid_id(image_id: str) -> bool:
    return bool(IMAGE_ID_RE.match(image_id or ""))


def image_path(images_dir: Path, image_id: str, ext: str) -> Path:
    if not _is_valid_id(image_id) or ext not in (".jpg", ".png"):
        raise AppError("圖片編號不正確", status=404)
    return images_dir / image_id[:2] / f"{image_id}{ext}"


def normalize(data: bytes) -> tuple[bytes, str, int, int]:
    """回傳 (存檔用的位元組, 副檔名, 寬, 高)。看不懂的檔案直接拒絕。"""
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError("圖片太大了（上限 25MB）", "請先用小畫家或手機把圖片縮小一點再上傳。", status=413)
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise AppError("看不懂這個檔案，請上傳 JPG 或 PNG 圖片", "如果是 iPhone 的 HEIC 照片，請先轉成 JPG。")
    fmt = (img.format or "").upper()
    img = ImageOps.exif_transpose(img)  # 手機直拍的照片轉正
    w, h = img.size
    needs_resize = max(w, h) > MAX_EDGE
    if fmt == "JPEG" and not needs_resize and img.mode in ("RGB", "L"):
        return data, ".jpg", w, h
    if fmt == "PNG" and not needs_resize:
        return data, ".png", w, h
    if needs_resize:
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        w, h = img.size
    has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
    out = io.BytesIO()
    if has_alpha:
        img.convert("RGBA").save(out, "PNG", optimize=True)
        return out.getvalue(), ".png", w, h
    img.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
    return out.getvalue(), ".jpg", w, h


def store(images_dir: Path, data: bytes) -> dict:
    """存一張圖，回傳 {id, ext, width, height, bytes}。已經有同一張就直接回傳舊的。"""
    body, ext, w, h = normalize(data)
    image_id = hashlib.sha256(body).hexdigest()[:32]
    path = image_path(images_dir, image_id, ext)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
    return {"id": image_id, "ext": ext, "width": w, "height": h, "bytes": len(body)}


def thumbnail(images_dir: Path, thumbs_dir: Path, image_id: str, ext: str, width: int) -> Path:
    """回傳縮圖路徑（沒有就現做一張）。width 只能是 THUMB_WIDTHS 其中之一。"""
    src = image_path(images_dir, image_id, ext)
    if width not in THUMB_WIDTHS:
        return src
    dst = thumbs_dir / f"{image_id}_{width}.jpg"
    if dst.exists():
        return dst
    with Image.open(src) as img:
        img = img.convert("RGB")
        if img.width > width:
            img.thumbnail((width, width * 4), Image.LANCZOS)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp")
        img.save(tmp, "JPEG", quality=82, optimize=True)
        tmp.replace(dst)
    return dst
