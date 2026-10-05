"""1文字ずつの配置。横書き・縦書き、明示改行、幅指定の折り返し（簡易禁則）、自動縮小。

各文字の「中心」(cx, cy) を決める。描画はこの中心を基準に行う。
"""

from dataclasses import dataclass, field

from . import fonts
from .util import graphemes

# 行頭に置かない文字（前の行の末尾へ追い込む）
NO_LINE_START = set("、。，．,.・：；？！?!ー）」』】〕〉》…‥ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ")
# 縦書きで 90° 回す文字
VERTICAL_ROTATE = set("ー－—―〜～…‥（）「」『』【】〔〕〈〉《》()[]<>-=→←")
# 縦書きで右上へ寄せる文字（句読点・小書き）
VERTICAL_PUNCT = set("、。，．,.")
VERTICAL_SMALL = set("ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ")


@dataclass
class Glyph:
    ch: str
    group: int          # 0 = 本文, 1 = サブテキスト
    size: float
    cx: float
    cy: float
    adv: float
    rot: bool = False
    blank: bool = False
    index: int = 0      # 全体での通し番号
    seq: int = 0        # 空白を除いた通し番号（効果の順序に使う）


@dataclass
class Layout:
    glyphs: list = field(default_factory=list)
    box: tuple = (0, 0, 0, 0)     # 文字全体の外接矩形（文字サイズ基準のおおよそ）
    size: float = 0.0             # 本文の実際の文字サイズ（自動縮小後）
    vertical: bool = False


class _Group:
    def __init__(self, scene, gid, size):
        f = scene["font"]
        sub = scene.get("sub") or {}
        self.gid = gid
        self.size = size
        self.weight = (sub.get("weight") if gid else None) or f["weight"]
        self.family = f["family"]
        ls = sub.get("letter_spacing", f["letter_spacing"]) if gid else f["letter_spacing"]
        self.ls = ls * size
        self.font = fonts.load(self.family, self.weight, size)

    def adv(self, ch, vertical):
        if ch == " " or ch == "　":
            return self.size * (0.3 if ch == " " else 1.0)
        return self.size if vertical else self.font.getlength(ch)


def _wrap(chars, measure, max_w, ls):
    """幅 max_w で折り返す。行頭禁則の文字は前の行へ追い込む。"""
    lines, cur, w = [], [], 0.0
    for ch in chars:
        a = measure(ch)
        need = a + (ls if cur else 0)
        if cur and max_w and w + need > max_w and ch not in NO_LINE_START:
            lines.append(cur)
            cur, w = [], 0.0
            need = a
        cur.append(ch)
        w += need
    lines.append(cur)
    return lines


def _lines_for(text, group, vertical, wrap):
    out = []
    for para in str(text).split("\n"):
        out.extend(_wrap(graphemes(para), lambda c: group.adv(c, vertical), wrap, group.ls))
    return out


def _line_len(line, group, vertical):
    if not line:
        return 0.0
    return sum(group.adv(c, vertical) for c in line) + group.ls * (len(line) - 1)


def _measure(scene, scale):
    S = scene["font"]["size"] * scale
    vertical = scene["writing"] == "vertical"
    wrap = scene["layout"]["wrap_width"] or None  # px のまま。縮小しても折り返し幅は変えない
    groups = [(_Group(scene, 0, S), scene["text"])]
    if scene.get("sub") and scene["sub"]["text"]:
        groups.append((_Group(scene, 1, S * scene["sub"]["size"]), scene["sub"]["text"]))
    return S, vertical, [(g, _lines_for(t, g, vertical, wrap)) for g, t in groups]


def _extent(scene, S, vertical, groups, lh):
    """(行方向の最大長, 行を重ねた方向の厚み)"""
    along = max(_line_len(l, g, vertical) for g, ls in groups for l in ls)
    cross = sum(len(ls) * g.size * lh for g, ls in groups)
    if len(groups) == 2:
        cross += scene["sub"]["gap"] * S
    return along, cross


def compute(scene):
    W, H = scene["canvas"]["width"], scene["canvas"]["height"]
    lay = scene["layout"]
    lh = scene["font"]["line_height"]
    margin = lay["margin"]
    scale = 1.0
    S, vertical, groups = _measure(scene, scale)
    if lay["auto_fit"]:
        # 行の長さと、行を重ねた厚み（行数×行送り＋サブとの間）の両方を収める。
        # 縮めると折り返しの行数が変わるので、収まるまで測り直す
        lim_along = (H if vertical else W) - 2 * margin
        lim_cross = (W if vertical else H) - 2 * margin
        for _ in range(6):
            along, cross = _extent(scene, S, vertical, groups, lh)
            k = min(1.0, lim_along / along if along > 0 and lim_along > 0 else 1.0,
                    lim_cross / cross if cross > 0 and lim_cross > 0 else 1.0)
            if k >= 0.999:
                break
            scale *= k * 0.999
            S, vertical, groups = _measure(scene, scale)
    # ブロック（本文とサブ）を並べる順と大きさ
    sub = scene.get("sub")
    blocks = [(g, ls) for g, ls in groups]
    if len(blocks) == 2 and sub["position"] == "above":
        blocks = [blocks[1], blocks[0]]
    gap = (sub["gap"] * S) if len(blocks) == 2 else 0.0
    cross = [len(ls) * g.size * lh for g, ls in blocks]
    total_cross = sum(cross) + gap
    placer = _place_vertical if vertical else _place_horizontal
    glyphs = placer(scene, blocks, cross, gap, total_cross, W, H, lh)
    for i, g in enumerate(glyphs):
        g.index = i
    seq = 0
    for g in glyphs:
        g.seq = seq
        if not g.blank:
            seq += 1
    ink = [g for g in glyphs if not g.blank] or glyphs
    x0 = min(g.cx - g.adv / 2 for g in ink)
    x1 = max(g.cx + g.adv / 2 for g in ink)
    y0 = min(g.cy - g.size / 2 for g in ink)
    y1 = max(g.cy + g.size / 2 for g in ink)
    return Layout(glyphs=glyphs, box=(x0, y0, x1, y1), size=S, vertical=vertical)


def _anchor_start(anchor, extent, total, margin):
    if anchor in ("top", "left"):
        return margin
    if anchor in ("bottom", "right"):
        return extent - margin - total
    return (extent - total) / 2


def _place_horizontal(scene, blocks, cross, gap, total, W, H, lh):
    lay = scene["layout"]
    ox, oy = lay["offset"]
    y = _anchor_start(lay["anchor"], H, total, lay["margin"]) + oy
    out = []
    for (g, lines), h in zip(blocks, cross):
        pitch = g.size * lh
        for li, line in enumerate(lines):
            lw = _line_len(line, g, False)
            x = _anchor_start(lay["align"], W, lw, lay["margin"]) + ox
            cy = y + pitch * li + pitch / 2
            for ch in line:
                a = g.adv(ch, False)
                out.append(Glyph(ch, g.gid, g.size, x + a / 2, cy, a, blank=not ch.strip()))
                x += a + g.ls
        y += h + gap
    return out


def _place_vertical(scene, blocks, cross, gap, total, W, H, lh):
    """縦書き：列は右から左へ。align は列の上下寄せ、anchor は全体の左右位置として読む。"""
    lay = scene["layout"]
    ox, oy = lay["offset"]
    anchor = {"top": "right", "bottom": "left"}.get(lay["anchor"], "center")
    right = _anchor_start(anchor, W, total, lay["margin"]) + total + ox
    align = {"left": "top", "right": "bottom"}.get(lay["align"], "center")
    out = []
    for (g, lines), w in zip(blocks, cross):
        pitch = g.size * lh
        for li, line in enumerate(lines):
            ll = _line_len(line, g, True)
            y = _anchor_start(align, H, ll, lay["margin"]) + oy
            cx = right - pitch * li - pitch / 2
            for ch in line:
                a = g.adv(ch, True)
                gx, gy = cx, y + a / 2
                if ch in VERTICAL_PUNCT:
                    gx, gy = gx + g.size * 0.6, gy - g.size * 0.6
                elif ch in VERTICAL_SMALL:
                    gx, gy = gx + g.size * 0.1, gy - g.size * 0.1
                out.append(Glyph(ch, g.gid, g.size, gx, gy, a,
                                 rot=ch in VERTICAL_ROTATE, blank=not ch.strip()))
                y += a + g.ls
        right -= w + gap
    return out
