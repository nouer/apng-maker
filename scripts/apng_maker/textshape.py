"""文字の組み方：1行ぶんの文字を「セル」に分け、行の中での位置と長さを決める。

横書き：各文字は単独で描くので、位置は「前の文字の位置＋前の文字の幅＋字間＋2文字の間の
  詰め量」で決める。詰め量は raqm で組んだ2文字の長さから単独の幅2つを引いたもので、
  ペアカーニング（AV・To など）と日本語の詰め（palt）がここに入る。単独で描く以上、
  文字をまたぐ合字（ffi など）や文脈で形が変わる字形は使えないので、無効にしておく。
縦書き：フォントの縦書き用字形（vert）に差し替えて描く。句読点・括弧・長音・小書き文字は
  フォントが縦書き用に用意した形と位置になる。英字は横倒し（side）、2桁までの数字は
  縦中横（tcy）にする。
raqm の無い環境では、字形の差し替えができないので、回転と位置ずらしで近似する。
"""

from dataclasses import dataclass

from PIL import features as pil_features

HAS_RAQM = pil_features.check("raqm")

# raqm が無いときの縦書きの近似
FALLBACK_ROTATE = set("ー－—―〜～…‥（）「」『』【】〔〕〈〉《》()[]<>-=→←")
FALLBACK_PUNCT = set("、。，．,.")
FALLBACK_SMALL = set("ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ")


@dataclass
class Cell:
    text: str
    kind: str              # "h" 横書き / "v" 縦書き用字形 / "side" 横倒し / "tcy" 縦中横
    ruby: int | None = None
    feats: tuple = ()
    adv: float = 0.0       # 行の向きの長さ（字間を含まない）
    dx: float = 0.0        # raqm の無い縦書きでの位置ずらし
    dy: float = 0.0
    rot: bool = False      # 描いたあと 90° 回す

    @property
    def blank(self):
        return not self.text.strip()


def h_features(font_cfg):
    feats = ["-liga", "-clig", "-calt"]
    if not font_cfg.get("kerning", True):
        feats.append("-kern")
    if font_cfg.get("palt", False):
        feats.append("palt")
    return tuple(feats)


def _ascii(g):
    return len(g) == 1 and "!" <= g <= "~"


class Shaper:
    """1つの文字組（本文・サブ・ルビ）の組み方。font は PIL の FreeTypeFont。"""

    def __init__(self, font, size, letter_spacing, vertical, font_cfg):
        self.font = font
        self.size = size
        self.ls = letter_spacing
        self.vertical = vertical
        self.hfeats = h_features(font_cfg) if HAS_RAQM else ()
        self._single_cache, self._kern_cache = {}, {}

    def _length(self, text, feats):
        kw = {"features": list(feats)} if feats and HAS_RAQM else {}
        return self.font.getlength(text, **kw)

    def _single(self, text):
        if text not in self._single_cache:
            self._single_cache[text] = self._length(text, self.hfeats)
        return self._single_cache[text]

    def _kern(self, a, b):
        """2文字を並べたときの詰め量（負なら詰まる）。"""
        key = (a, b)
        if key not in self._kern_cache:
            self._kern_cache[key] = self._length(a + b, self.hfeats) - self._single(a) - self._single(b)
        return self._kern_cache[key]

    # ---------- セルに分ける ----------

    def cells(self, tokens):
        """tokens: [(文字, ルビ番号)]（1段落）→ [Cell]"""
        if not self.vertical:
            return [Cell(g, "h", rid, self.hfeats) for g, rid in tokens]
        out, i = [], 0
        while i < len(tokens):
            g, rid = tokens[i]
            if _ascii(g):
                j = i
                while j < len(tokens) and _ascii(tokens[j][0]) and tokens[j][1] == rid:
                    j += 1
                run = "".join(t for t, _ in tokens[i:j])
                if len(run) <= 2 and (run.isdigit() or set(run) <= set("!?")):
                    out.append(Cell(run, "tcy", rid))
                else:
                    out.extend(Cell(c, "side", rid, rot=True) for c in run)
                i = j
                continue
            out.append(self._vertical_cell(g, rid))
            i += 1
        return out

    def _vertical_cell(self, g, rid):
        if HAS_RAQM:
            return Cell(g, "v", rid, ("vert",))
        S = self.size
        if g in FALLBACK_PUNCT:
            return Cell(g, "v", rid, dx=S * 0.6, dy=-S * 0.6)
        if g in FALLBACK_SMALL:
            return Cell(g, "v", rid, dx=S * 0.1, dy=-S * 0.1)
        return Cell(g, "v", rid, rot=g in FALLBACK_ROTATE)

    # ---------- 長さと位置 ----------

    def place(self, cells):
        """各セルの行頭からの開始位置を入れ、行の長さを返す（字間を含む）。セルの adv も埋める。"""
        starts, pos = [], 0.0
        for k, c in enumerate(cells):
            c.adv = self.advance(c)
            if k:
                pos += cells[k - 1].adv + self.join(cells[k - 1], c)
            starts.append(pos)
        return starts, (pos + cells[-1].adv) if cells else 0.0

    def advance(self, c):
        """セル単独の、行の向きの長さ。"""
        return self._vertical_adv(c) if self.vertical else self._single(c.text)

    def join(self, a, b):
        """セル a の次にセル b を置くときの、a の終わりから b の始まりまで（字間＋詰め量）。"""
        return self.ls + (0.0 if self.vertical else self._kern(a.text, b.text))

    def length(self, cells):
        """行の長さだけを測る（折り返しの判定用）。"""
        return self.place(cells)[1]

    def _vertical_adv(self, c):
        if c.kind == "side":
            return self._length(c.text, ())
        if c.text == " ":
            return self.size * 0.3
        return self.size
