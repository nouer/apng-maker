"""1文字ぶんの画像（スプライト）を作る。

スプライトは文字の中心が画像の中心に来るように作る。こうしておくと、拡大・回転しても
中心がずれない。発光（glow）は表示中の効果で強さを変えるため、本体と分けて持つ。
"""

from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import fonts
from .textshape import HAS_RAQM
from .util import rgba


@dataclass
class Sprite:
    body: Image.Image
    glow: Image.Image | None


def _style_for(scene, group):
    style = scene["style"]
    if group == 1 and scene["sub"].get("fill"):
        style = {**style, "fill": scene["sub"]["fill"]}
    return style


def _pad(style, S):
    pad = max((s["width"] for s in style.get("strokes") or []), default=0) * S
    sh = style.get("shadow")
    if sh:
        pad = max(pad, (max(abs(sh.get("dx", 0)), abs(sh.get("dy", 0))) + sh.get("blur", 0) * 3) * S)
    gl = style.get("glow")
    if gl:
        pad = max(pad, gl.get("radius", 0.15) * S * 3)
    return int(pad + S * 0.15 + 4)


def _gradient(fill, w, h, top, bottom):
    """塗りの色の画像。グラデーションは文字の上端〜下端（または左右）に掛ける。"""
    colors = [rgba(c) for c in fill.get("colors") or ["#ffffff", "#888888"]]
    horizontal = fill.get("dir") == "h"
    n = len(colors) - 1
    length = w if horizontal else h
    strip = Image.new("RGBA", (length, 1) if horizontal else (1, length))
    lo, hi = (0, w) if horizontal else (top, bottom)
    span = max(1.0, hi - lo)
    for i in range(length):
        t = min(1.0, max(0.0, (i - lo) / span)) * n
        k = min(int(t), n - 1)
        f = t - k
        a, b = colors[k], colors[k + 1]
        color = tuple(int(a[j] + (b[j] - a[j]) * f + 0.5) for j in range(4))
        strip.putpixel((i, 0) if horizontal else (0, i), color)
    return strip.resize((w, h), Image.NEAREST)


def _text_mask(size, font, xy, ch, stroke=0, feats=()):
    mask = Image.new("L", size, 0)
    kw = {"features": list(feats)} if feats and HAS_RAQM else {}
    ImageDraw.Draw(mask).text(xy, ch, font=font, fill=255, anchor="ms",
                              stroke_width=int(round(stroke)), stroke_fill=255, **kw)
    return mask


def _em_center(font):
    """ベースラインから見た、字面（全角の枠）の中心の高さ（上が負）。
    「口」の外形から求める。縦書き用字形はこの枠を基準に作られているので、ここを中心に描く。"""
    try:
        _, top, _, bottom = font.getbbox("口", anchor="ls")
        if bottom > top:
            return (top + bottom) / 2
    except (OSError, ValueError):
        pass
    asc, desc = font.getmetrics()
    return -(asc - desc) / 2


def _close_holes(mask, gap):
    """外側の縁取りが埋めた小さな隙間を、内側の層でも埋める（膨張→収縮）。
    埋めないと、内側の層の隙間から外側の色が点になって見える。"""
    k = int(gap) | 1
    if k < 3:
        return mask
    k = min(k, 15)
    return mask.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))


def _colored(mask, color):
    layer = Image.new("RGBA", mask.size, rgba(color)[:3] + (0,))
    a = rgba(color)[3]
    layer.putalpha(mask if a == 255 else mask.point(lambda v: v * a // 255))
    return layer


def build(glyph, scene):
    """Glyph から Sprite を作る。空白は None。"""
    if glyph.blank:
        return None
    style = _style_for(scene, glyph.group)
    S = glyph.size
    weight = scene["font"]["weight"]
    if glyph.group == 1 and scene["sub"].get("weight"):
        weight = scene["sub"]["weight"]
    font = fonts.load(scene["font"]["family"], weight, S)
    feats = glyph.feats if HAS_RAQM else ()
    pad = _pad(style, S)
    # 横に描いたときの文字の幅（縦書きの v は全角、縦中横はつないだ文字列の幅）
    width = font.getlength(glyph.ch) if glyph.kind in ("side", "tcy") else (
        S if glyph.kind == "v" else glyph.adv)
    half_w = int(max(width, S) / 2 + pad)
    half_h = int(S / 2 + pad)
    if glyph.rot:
        half_w, half_h = max(half_w, half_h), max(half_w, half_h)
    size = (half_w * 2, half_h * 2)
    xy = (half_w, half_h - _em_center(font))

    body = Image.new("RGBA", size, (0, 0, 0, 0))
    # 縁取りは太い順に重ねる（外側の縁 → 内側の縁 → 塗り）
    prev_w = None
    for st in sorted(style.get("strokes") or [], key=lambda s: -s["width"]):
        w = st["width"] * S
        if w > 0:
            mask = _text_mask(size, font, xy, glyph.ch, w, feats)
            if prev_w is not None:
                mask = _close_holes(mask, prev_w - w)
            body.alpha_composite(_colored(mask, st["color"]))
            prev_w = w
    fill_mask = _text_mask(size, font, xy, glyph.ch, 0, feats)
    fill = style["fill"]
    if fill.get("type") == "gradient":
        top, bottom = half_h - S / 2, half_h + S / 2
        paint = _gradient(fill, size[0], size[1], top, bottom)
        alpha = ImageChops.multiply(paint.getchannel("A"), fill_mask)
        paint.putalpha(alpha)
        body.alpha_composite(paint)
    else:
        body.alpha_composite(_colored(fill_mask, fill.get("color", "#ffffff")))

    sh = style.get("shadow")
    if sh:
        shadow = _colored(body.getchannel("A"), rgba(sh.get("color", "#000000"), sh.get("opacity", 0.6)))
        shadow = ImageChops.offset(shadow, int(sh.get("dx", 0.04) * S), int(sh.get("dy", 0.06) * S))
        if sh.get("blur", 0) > 0:
            shadow = shadow.filter(ImageFilter.GaussianBlur(sh["blur"] * S))
        shadow.alpha_composite(body)
        body = shadow

    glow = None
    gl = style.get("glow")
    if gl:
        base = body.getchannel("A").filter(ImageFilter.GaussianBlur(gl.get("radius", 0.15) * S))
        boost = gl.get("strength", 1.6)
        base = base.point(lambda v: min(255, int(v * boost)))
        glow = _colored(base, rgba(gl.get("color", "#ffcc00"), gl.get("opacity", 0.9)))

    if glyph.rot:
        body = body.rotate(-90)
        glow = glow.rotate(-90) if glow else None
    if glyph.kind == "tcy" and width > S * 0.95:   # 縦中横は1文字の枠に収まるよう横を縮める
        k = S * 0.95 / width
        body = _squeeze(body, k)
        glow = _squeeze(glow, k) if glow else None
    return Sprite(body=body, glow=glow)


def _squeeze(img, k):
    w, h = img.size
    nw = max(2, int(w * k) // 2 * 2)
    return img.resize((nw, h), Image.LANCZOS)


def build_all(layout, scene):
    """同じ文字・同じ組・同じ向きのスプライトは使い回す。"""
    cache, out = {}, []
    for g in layout.glyphs:
        key = (g.ch, g.group, g.rot, round(g.size, 2), g.kind, g.feats)
        if key not in cache:
            cache[key] = build(g, scene)
        out.append(cache[key])
    return out
