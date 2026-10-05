"""イージング関数（標準的な式。入力 0〜1 → 出力 0〜1 付近）。"""

import math

TAU = math.pi * 2


def _out_bounce(t):
    n1, d1 = 7.5625, 2.75
    if t < 1 / d1:
        return n1 * t * t
    if t < 2 / d1:
        t -= 1.5 / d1
        return n1 * t * t + 0.75
    if t < 2.5 / d1:
        t -= 2.25 / d1
        return n1 * t * t + 0.9375
    t -= 2.625 / d1
    return n1 * t * t + 0.984375


def _out_back(t):
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def _out_elastic(t):
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (TAU / 3)) + 1


EASE = {
    "linear": lambda t: t,
    "inQuad": lambda t: t * t,
    "outQuad": lambda t: 1 - (1 - t) ** 2,
    "inCubic": lambda t: t ** 3,
    "outCubic": lambda t: 1 - (1 - t) ** 3,
    "inOutCubic": lambda t: 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2,
    "outQuart": lambda t: 1 - (1 - t) ** 4,
    "inExpo": lambda t: 0.0 if t <= 0 else 2 ** (10 * t - 10),
    "outExpo": lambda t: 1.0 if t >= 1 else 1 - 2 ** (-10 * t),
    "outBack": _out_back,
    "outElastic": _out_elastic,
    "outBounce": _out_bounce,
}


def ease(name, t, fallback="outCubic"):
    fn = EASE.get(name) if name else None
    return (fn or EASE[fallback])(t)
