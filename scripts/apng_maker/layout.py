"""配置。横書き・縦書き、明示改行、幅指定の折り返し（簡易禁則）、ルビ、自動縮小。

各文字の「中心」(cx, cy) を決める。描画はこの中心を基準に行う。
文字の組み方（カーニング・縦書き用字形など）は textshape、ルビの解析は ruby が受け持つ。
"""

from dataclasses import dataclass, field

from . import fonts, ruby as ruby_mod
from .textshape import Shaper

# 行頭に置かない文字（前の行の末尾へ追い込む）
NO_LINE_START = set("、。，．,.・：；？！?!ー）」』】〕〉》…‥ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ")


@dataclass
class Glyph:
    ch: str
    group: int          # 0 = 本文, 1 = サブテキスト
    size: float
    cx: float
    cy: float
    adv: float          # 行の向きの長さ
    kind: str = "h"     # h / v / side / tcy（textshape.Cell と同じ）
    feats: tuple = ()
    rot: bool = False
    blank: bool = False
    index: int = 0      # 全体での通し番号
    seq: int = 0        # 空白とルビを除いた通し番号（効果の順序に使う）
    aux: bool = False   # ルビ。親字の最初の文字と同じ時刻に動く
    base: "Glyph | None" = None


@dataclass
class Layout:
    glyphs: list = field(default_factory=list)
    box: tuple = (0, 0, 0, 0)     # 文字全体の外接矩形（文字サイズ基準のおおよそ）
    size: float = 0.0             # 本文の実際の文字サイズ（自動縮小後）
    vertical: bool = False


class _Group:
    """本文かサブテキストの、1つの文字組。"""

    def __init__(self, scene, gid, size, text, vertical, wrap):
        f = scene["font"]
        sub = scene.get("sub") or {}
        r = scene["ruby"]
        self.gid, self.size = gid, size
        weight = (sub.get("weight") if gid else None) or f["weight"]
        ls = sub.get("letter_spacing", f["letter_spacing"]) if gid else f["letter_spacing"]
        self.shaper = Shaper(fonts.load(f["family"], weight, size), size, ls * size, vertical, f)
        self.ruby_size = size * r["size"]
        self.ruby_shaper = Shaper(fonts.load(f["family"], weight, self.ruby_size), self.ruby_size,
                                  0.0, vertical, f)
        tokens, self.rubies = ruby_mod.parse(text)
        self.band = (self.ruby_size + r["gap"] * size) if self.rubies else 0.0
        self.ruby_cells, self.ruby_len = [], []
        for reading in self.rubies:
            cells = self.ruby_shaper.cells([(c, None) for c in ruby_mod.graphemes(reading)])
            self.ruby_cells.append(cells)
            self.ruby_len.append(self.ruby_shaper.length(cells))
        self.lines = []
        for para in _paragraphs(tokens):
            self.lines.extend(self._wrap(self.shaper.cells(para), wrap))

    def pitch(self, lh):
        return self.size * lh + self.band

    def line_range(self, line):
        """行の各セルの開始位置と、ルビのはみ出しを含めた行の範囲 (starts, lo, hi)。
        lo は行頭より前へはみ出す分（0 以下）、hi は行頭からの終わり。"""
        starts, length = self.shaper.place(line)
        lo, hi = 0.0, length
        for rid, b0, b1 in _ruby_spans(line, starts):
            rlen = self.ruby_len[rid]
            if rlen > b1 - b0:
                r0 = (b0 + b1 - rlen) / 2
                lo, hi = min(lo, r0), max(hi, r0 + rlen)
        return starts, lo, hi

    def _wrap(self, cells, max_len):
        """幅 max_len で折り返す。ルビの親字の途中では切らず、行頭禁則の文字は前の行へ追い込む。
        行の長さは、かたまりを足すたびに継ぎ目の分だけ足していく（毎回測り直すと2乗になる）。"""
        lines, cur, cur_len = [], [], 0.0
        for unit in _units(cells):
            unit_len = self.shaper.length(unit)
            add = unit_len + (self.shaper.join(cur[-1], unit[0]) if cur else 0.0)
            if cur and max_len and unit[0].text not in NO_LINE_START and cur_len + add > max_len:
                lines.append(cur)
                cur, cur_len, add = [], 0.0, unit_len
            cur.extend(unit)
            cur_len += add
        lines.append(cur)
        return lines


def _paragraphs(tokens):
    para = []
    for t in tokens:
        if t[0] == "\n":
            yield para
            para = []
        else:
            para.append(t)
    yield para


def _ruby_spans(line, starts):
    """行の中のルビの親字の範囲 [(ルビ番号, 始まり, 終わり)]。"""
    spans = {}
    for c, s in zip(line, starts):
        if c.ruby is None:
            continue
        if c.ruby not in spans:
            spans[c.ruby] = [s, s + c.adv]
        spans[c.ruby][1] = s + c.adv
    return [(rid, b0, b1) for rid, (b0, b1) in spans.items()]


def _units(cells):
    """同じルビに属するセルを1かたまりにする。"""
    units = []
    for c in cells:
        if units and c.ruby is not None and units[-1][-1].ruby == c.ruby:
            units[-1].append(c)
        else:
            units.append([c])
    return units


def _build(scene, scale):
    S = scene["font"]["size"] * scale
    vertical = scene["writing"] == "vertical"
    wrap = scene["layout"]["wrap_width"] or None  # px のまま。縮小しても折り返し幅は変えない
    groups = [_Group(scene, 0, S, scene["text"], vertical, wrap)]
    if scene.get("sub") and scene["sub"]["text"]:
        groups.append(_Group(scene, 1, S * scene["sub"]["size"], scene["sub"]["text"], vertical, wrap))
    return S, vertical, groups


def _extent(scene, S, groups, lh):
    """(行方向の最大長, 行を重ねた方向の厚み)"""
    along = max(hi - lo for g in groups for line in g.lines for _, lo, hi in [g.line_range(line)])
    cross = sum(len(g.lines) * g.pitch(lh) for g in groups)
    if len(groups) == 2:
        cross += scene["sub"]["gap"] * S
    return along, cross


def compute(scene):
    W, H = scene["canvas"]["width"], scene["canvas"]["height"]
    lay = scene["layout"]
    lh = scene["font"]["line_height"]
    margin = lay["margin"]
    scale = 1.0
    S, vertical, groups = _build(scene, scale)
    if lay["auto_fit"]:
        # 行の長さと、行を重ねた厚み（行数×行送り＋ルビ＋サブとの間）の両方を収める。
        # 縮めると折り返しの行数が変わるので、収まるまで測り直す
        lim_along = (H if vertical else W) - 2 * margin
        lim_cross = (W if vertical else H) - 2 * margin
        for _ in range(6):
            along, cross = _extent(scene, S, groups, lh)
            k = min(1.0, lim_along / along if along > 0 and lim_along > 0 else 1.0,
                    lim_cross / cross if cross > 0 and lim_cross > 0 else 1.0)
            if k >= 0.999:
                break
            scale *= k * 0.999
            S, vertical, groups = _build(scene, scale)
    sub = scene.get("sub")
    if len(groups) == 2 and sub["position"] == "above":
        groups = [groups[1], groups[0]]
    gap = (sub["gap"] * S) if len(groups) == 2 else 0.0
    total = sum(len(g.lines) * g.pitch(lh) for g in groups) + gap
    glyphs = _place(scene, groups, gap, total, W, H, lh, vertical)
    _number(glyphs)
    return Layout(glyphs=glyphs, box=_box(glyphs, vertical), size=S, vertical=vertical)


def _number(glyphs):
    seq = 0
    for i, g in enumerate(glyphs):
        g.index = i
        if not g.aux:
            g.seq = seq
            seq += 0 if g.blank else 1
    for g in glyphs:
        if g.aux:
            g.seq = g.base.seq


def _box(glyphs, vertical):
    ink = [g for g in glyphs if not g.blank] or glyphs
    if not ink:
        return (0, 0, 0, 0)
    hw = (lambda g: g.size / 2) if vertical else (lambda g: g.adv / 2)
    hh = (lambda g: g.adv / 2) if vertical else (lambda g: g.size / 2)
    return (min(g.cx - hw(g) for g in ink), min(g.cy - hh(g) for g in ink),
            max(g.cx + hw(g) for g in ink), max(g.cy + hh(g) for g in ink))


def _anchor_start(anchor, extent, total, margin):
    if anchor in ("top", "left"):
        return margin
    if anchor in ("bottom", "right"):
        return extent - margin - total
    return (extent - total) / 2


def _place(scene, groups, gap, total, W, H, lh, vertical):
    """行を並べる。横書きは上から下、縦書きは右から左。
    縦書きでは align を列の上下寄せ、anchor を全体の左右位置として読む。"""
    lay = scene["layout"]
    ox, oy = lay["offset"]
    if vertical:
        anchor = {"top": "right", "bottom": "left"}.get(lay["anchor"], "center")
        cursor = _anchor_start(anchor, W, total, lay["margin"]) + total + ox   # 右端から左へ
        align = {"left": "top", "right": "bottom"}.get(lay["align"], "center")
    else:
        cursor = _anchor_start(lay["anchor"], H, total, lay["margin"]) + oy    # 上端から下へ
        align = lay["align"]
    out = []
    for g in groups:
        pitch = g.pitch(lh)
        for line in g.lines:
            starts, lo, hi = g.line_range(line)
            if vertical:
                along0 = _anchor_start(align, H, hi - lo, lay["margin"]) + oy - lo
                cross_c = cursor - g.band - g.size * lh / 2       # ルビは列の右側
                ruby_c = cursor - g.ruby_size / 2
                cursor -= pitch
            else:
                along0 = _anchor_start(align, W, hi - lo, lay["margin"]) + ox - lo
                cross_c = cursor + g.band + g.size * lh / 2       # ルビは行の上側
                ruby_c = cursor + g.ruby_size / 2
                cursor += pitch
            bases = []
            for c, s in zip(line, starts):
                a = along0 + s + c.adv / 2
                cx, cy = (cross_c + c.dx, a + c.dy) if vertical else (a, cross_c)
                gl = Glyph(c.text, g.gid, g.size, cx, cy, c.adv, c.kind, c.feats, c.rot, c.blank)
                out.append(gl)
                bases.append((gl, c.ruby, along0 + s, c.adv))
            out.extend(_ruby_glyphs(g, bases, ruby_c, vertical))
        cursor += -gap if vertical else gap
    return out


def _ruby_glyphs(g, bases, cross_c, vertical):
    """親字の範囲の上（縦書きは右）にルビを置く。ルビが親字より短ければ均等に割り付け、
    長ければ親字の中央に合わせてはみ出させる。"""
    out = []
    spans = {}
    for gl, rid, start, adv in bases:
        if rid is None:
            continue
        if rid not in spans:
            spans[rid] = [gl, start, start + adv]
        spans[rid][2] = start + adv
    for rid, (first, b0, b1) in spans.items():
        cells = g.ruby_cells[rid]
        starts, length = g.ruby_shaper.place(cells)
        blen = b1 - b0
        for k, (c, s) in enumerate(zip(cells, starts)):
            if length < blen:
                a = b0 + blen / len(cells) * (k + 0.5)
            else:
                a = b0 + (blen - length) / 2 + s + c.adv / 2
            cx, cy = (cross_c + c.dx, a + c.dy) if vertical else (a, cross_c)
            out.append(Glyph(c.text, g.gid, g.ruby_size, cx, cy, c.adv, c.kind, c.feats, c.rot,
                             c.blank, aux=True, base=first))
    return out
