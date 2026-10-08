"""錯誤類型。每個錯誤都帶一句「下一步怎麼做」，網頁和指令列都直接顯示給使用者看。"""


class AppError(Exception):
    """給使用者看的錯誤：message 說發生什麼事，hint 說接下來怎麼做。"""

    status = 400

    def __init__(self, message: str, hint: str = "", status: int | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        if status is not None:
            self.status = status


class NotFound(AppError):
    status = 404


class Conflict(AppError):
    """別人剛好也改了同一筆資料（版本號對不上）。"""

    status = 409


class SourceError(AppError):
    """讀 Google 文件失敗。"""

    status = 502


class Forbidden(AppError):
    status = 403
