"""文字の後ろに敷く装飾：帯（band）・箱（box）・下線（underline）・上下線（lines）。

open は開く進み具合（0→1）、close は閉じる進み具合（0→1）。
"""

from PIL import ImageDraw

from .easing import ease
from .util import new_layer, rgba


def draw(canvas_size, layout, deco, open_p, close_p, offset=(0, 0)):
    """装飾を描いたレイヤーを返す。何も描かないときは None。"""
    kind = deco["type"]
    k = ease("outCubic", open_p) * (1 - ease("inCubic", close_p))
    if kind == "none" or k <= 0.001:
        return None
    W, H = canvas_size
    S = layout.size
    pad = deco["pad"] * S
    th = max(1.0, deco["thickness"] * S)
    color = rgba(deco["color"], deco["opacity"])
    ox, oy = offset
    x0, y0, x1, y1 = layout.box
    x0, x1, y0, y1 = x0 + ox, x1 + ox, y0 + oy, y1 + oy
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    layer = new_layer(W, H)
    d = ImageDraw.Draw(layer)
    v = layout.vertical

    if kind == "band":
        if v:
            half = ((x1 - x0) / 2 + pad) * k
            d.rectangle((cx - half, 0, cx + half, H), fill=color)
        else:
            half = ((y1 - y0) / 2 + pad) * k
            d.rectangle((0, cy - half, W, cy + half), fill=color)
    elif kind == "box":
        hw, hh = (x1 - x0) / 2 + pad, (y1 - y0) / 2 + pad
        if v:
            hw *= k
        else:
            hh *= k
        d.rounded_rectangle((cx - hw, cy - hh, cx + hw, cy + hh),
                            radius=int(deco.get("radius", 0.15) * S * k), fill=color)
    elif kind == "underline":
        if v:
            x = x0 - pad * 0.5
            d.rectangle((x - th, y0 - pad, x, y0 - pad + (y1 - y0 + 2 * pad) * k), fill=color)
        else:
            y = y1 + pad * 0.5
            d.rectangle((x0 - pad, y, x0 - pad + (x1 - x0 + 2 * pad) * k, y + th), fill=color)
    elif kind == "lines":
        if v:
            half = ((y1 - y0) / 2 + pad * 2) * k
            for x in (x0 - pad, x1 + pad):
                d.rectangle((x - th / 2, cy - half, x + th / 2, cy + half), fill=color)
        else:
            half = ((x1 - x0) / 2 + pad * 2) * k
            for y in (y0 - pad, y1 + pad):
                d.rectangle((cx - half, y - th / 2, cx + half, y + th / 2), fill=color)
    return layer
