"""青空文庫式のルビの解析。

  魔王《まおう》     《》の直前にある漢字の連なりが親字になる
  ｜古の剣《いにしえのつるぎ》  ｜から《までが親字になる（かなや英字を含む親字はこちら）

解析すると、見た目の1文字ずつの列と、それぞれがどのルビに属するかの番号を返す。
対応する《》が無い記号は、そのまま文字として残す。
"""

import re

from .util import graphemes

EXPLICIT = "｜"
OPEN, CLOSE = "《", "》"
_KANJI = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003FFFF々〆〇ヶ]")


def is_kanji(g):
    return bool(_KANJI.match(g[0]))


def _next_marks(gs):
    """各位置から見て、同じ段落で次に来る 《 と 》 の位置（無ければ None）。
    1度だけ後ろから走査して求める（《 ごとに先を探すと、閉じない 《 が多い文で2乗になる）。"""
    nxt_open, nxt_close = [None] * len(gs), [None] * len(gs)
    o = c = None
    for i in range(len(gs) - 1, -1, -1):
        if gs[i] == "\n":
            o = c = None
        nxt_open[i], nxt_close[i] = o, c
        if gs[i] == OPEN:
            o = i
        elif gs[i] == CLOSE:
            c = i
    return nxt_open, nxt_close


def _filled(chars):
    return bool("".join(chars).strip())


def parse(text):
    """(文字の列 [(文字, ルビ番号 or None)], ルビの文字列のリスト) を返す。
    ルビとして成り立たない記法（親字や読みが空・空白だけ、閉じない 《）は、そのまま文字として残す。"""
    gs = graphemes(str(text))
    nxt_open, nxt_close = _next_marks(gs)
    out, rubies = [], []
    i = 0
    while i < len(gs):
        g = gs[i]
        if g == EXPLICIT:
            op = nxt_open[i]
            end = nxt_close[op] if op is not None else None
            if end is not None:
                base, reading = gs[i + 1:op], gs[op + 1:end]
                if _filled(base) and _filled(reading) and EXPLICIT not in base:
                    rid = len(rubies)
                    rubies.append("".join(reading))
                    out.extend((c, rid) for c in base)
                    i = end + 1
                    continue
        elif g == OPEN:
            end = nxt_close[i]
            start = _kanji_run_start(out)
            if end is not None and start is not None and _filled(gs[i + 1:end]):
                rid = len(rubies)
                rubies.append("".join(gs[i + 1:end]))
                out[start:] = [(c, rid) for c, _ in out[start:]]
                i = end + 1
                continue
        out.append((g, None))
        i += 1
    return out, rubies


def _kanji_run_start(out):
    k = len(out)
    while k > 0 and out[k - 1][1] is None and is_kanji(out[k - 1][0]):
        k -= 1
    return k if k < len(out) else None


def strip(text):
    """ルビの記法を取り除いた本文。"""
    tokens, _ = parse(text)
    return "".join(c for c, _ in tokens)
