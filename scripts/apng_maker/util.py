"""小さな共通部品：決定的な乱数、文字の分割、色、はみ出しを許す合成。"""

import unicodedata

from PIL import Image, ImageColor


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return a + (b - a) * t


def hash32(*parts):
    """整数列から 32bit の値を作る。同じ入力なら必ず同じ値になる。"""
    h = 0x811C9DC5
    for p in parts:
        v = int(p) & 0xFFFFFFFF
        for _ in range(4):
            h ^= v & 0xFF
            h = (h * 0x01000193) & 0xFFFFFFFF
            v >>= 8
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    return h


def rnd(*parts):
    """0 以上 1 未満の決定的な乱数。"""
    return hash32(*parts) / 4294967296.0


def rnd_signed(*parts):
    """-1 以上 1 未満の決定的な乱数。"""
    return rnd(*parts) * 2.0 - 1.0


_JOINERS = {"‍"}


def graphemes(text):
    """結合文字・異体字セレクタ・ZWJ をまとめて、見た目の1文字ずつに分ける。"""
    out = []
    join_next = False
    for ch in text:
        cat = unicodedata.category(ch)
        attach = (
            out
            and not out[-1] == "\n"
            and (join_next or cat in ("Mn", "Me") or 0xFE00 <= ord(ch) <= 0xFE0F
                 or 0x1F3FB <= ord(ch) <= 0x1F3FF or ch in _JOINERS)
        )
        if attach:
            out[-1] += ch
        else:
            out.append(ch)
        join_next = ch in _JOINERS
    return out


def rgba(color, opacity=1.0):
    """'#rrggbb' や色名を (r, g, b, a) にする。opacity を掛ける。"""
    if isinstance(color, (list, tuple)):
        r, g, b, *rest = color
        a = rest[0] if rest else 255
    else:
        r, g, b, a = ImageColor.getcolor(color, "RGBA")
    return (r, g, b, int(round(a * clamp(opacity))))


def scale_alpha(img, k):
    """RGBA 画像の不透明度を k 倍した新しい画像を返す。"""
    if k >= 0.999:
        return img
    out = img.copy()
    if k <= 0.001:
        out.putalpha(0)
        return out
    lut = [int(v * k + 0.5) for v in range(256)]
    out.putalpha(img.getchannel("A").point(lut))
    return out


def composite(dst, src, x, y):
    """src を dst の (x, y) へアルファ合成する。はみ出した部分は切り捨てる。dst を書き換える。"""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.width, x + src.width), min(dst.height, y + src.height)
    if x0 >= x1 or y0 >= y1:
        return
    piece = src.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    dst.alpha_composite(piece, (x0, y0))


def new_layer(w, h, color=None):
    return Image.new("RGBA", (w, h), rgba(color) if color else (0, 0, 0, 0))
