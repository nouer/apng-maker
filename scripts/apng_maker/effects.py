"""登場（in）・表示中（hold）・退場（out）の効果。

各効果は「進み具合 u（0→1）」または「経過秒 t」から、文字の状態の差分を返す。
状態のキー：
  a      不透明度（掛け算）     dx, dy 位置のずれ px（足し算）
  s      拡大率（掛け算）       sx, sy 横・縦だけの拡大率（掛け算）
  r      回転 度（足し算）      blur   ぼかし px（足し算）
  bright 白飛び 0〜1（最大）    glitch ノイズの強さ 0〜1（最大）
  glow   発光の強さ（掛け算）
乱数は文字番号と時刻から決めるので、同じ時刻なら必ず同じ絵になる。
"""

import math

from .easing import TAU, ease
from .util import clamp, rnd, rnd_signed

IDENTITY = {"a": 1.0, "dx": 0.0, "dy": 0.0, "s": 1.0, "sx": 1.0, "sy": 1.0,
            "r": 0.0, "blur": 0.0, "bright": 0.0, "glitch": 0.0, "glow": 1.0}

_MUL = ("a", "s", "sx", "sy", "glow")
_MAX = ("bright", "glitch")


def combine(state, delta):
    """state に delta を重ねた新しい dict を返す。"""
    out = dict(state)
    for k, v in delta.items():
        if k in _MUL:
            out[k] *= v
        elif k in _MAX:
            out[k] = max(out[k], v)
        else:
            out[k] += v
    return out


def _dir_vec(d):
    return {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[d]


def _flicker(u, c, steps=9):
    """だんだん点いていく明滅。最後は必ず点灯。"""
    if u >= 1:
        return 1.0
    k = int(u * steps)
    return 1.0 if rnd(c.seed, c.i, k, 7) < 0.25 + 0.75 * u else 0.15


# ---------------- 登場 ----------------
# 関数は (u, c) を受け取る。u は 0→1 の生の進み具合、c は文字の文脈（S, i, seed, dir, ease）。

def _in_slide(u, c):
    e = ease(c.ease, u, "outCubic")
    vx, vy = _dir_vec(c.dir)
    return {"a": ease("outQuad", u), "dx": vx * (1 - e) * c.S, "dy": vy * (1 - e) * c.S}


def _in_scatter(u, c):
    e = ease(c.ease, u, "outCubic")
    ang = rnd(c.seed, c.i, 1) * TAU
    dist = (1.2 + rnd(c.seed, c.i, 2)) * c.S * 1.5
    return {"a": e, "dx": math.cos(ang) * dist * (1 - e), "dy": math.sin(ang) * dist * (1 - e),
            "r": rnd_signed(c.seed, c.i, 3) * 180 * (1 - e)}


IN_FX = {
    "none": (0.0, lambda u, c: {}),
    "fade": (0.35, lambda u, c: {"a": ease(c.ease, u, "outQuad")}),
    "rise": (0.4, lambda u, c: {"a": ease("outQuad", u),
                                "dy": (1 - ease(c.ease, u, "outCubic")) * 0.5 * c.S}),
    "drop": (0.4, lambda u, c: {"a": ease("outQuad", u),
                                "dy": -(1 - ease(c.ease, u, "outCubic")) * 0.5 * c.S}),
    "slide": (0.4, _in_slide),
    "pop": (0.35, lambda u, c: {"a": clamp(u * 3), "s": max(0.0, ease(c.ease, u, "outBack"))}),
    "shrinkIn": (0.35, lambda u, c: {"a": ease("outQuad", u),
                                     "s": 1 + 1.5 * (1 - ease(c.ease, u, "outCubic"))}),
    "zoomIn": (0.4, lambda u, c: {"a": ease("outQuad", u),
                                  "s": 0.2 + 0.8 * ease(c.ease, u, "outCubic")}),
    "slam": (0.25, lambda u, c: {"a": clamp(u * 4), "s": 1 + 2.2 * (1 - u) ** 2}),
    "spin": (0.5, lambda u, c: {"a": clamp(u * 2), "s": ease(c.ease, u, "outCubic"),
                                "r": -360 * (1 - ease(c.ease, u, "outCubic"))}),
    "flip": (0.35, lambda u, c: {"a": clamp(u * 2), "sx": max(0.02, ease(c.ease, u, "outCubic"))}),
    "bounce": (0.7, lambda u, c: {"a": clamp(u * 4),
                                  "dy": -(1 - ease("outBounce", u)) * 1.2 * c.S}),
    "blurIn": (0.45, lambda u, c: {"a": ease("outQuad", u),
                                   "blur": (1 - ease(c.ease, u, "outCubic")) * 0.25 * c.S}),
    "scatter": (0.6, _in_scatter),
    "typewriter": (0.0, lambda u, c: {}),
    "flicker": (0.5, lambda u, c: {"a": _flicker(u, c)}),
    "glitch": (0.4, lambda u, c: {"a": 1.0 if u > 0.15 or rnd(c.seed, c.i, int(u * 20)) > 0.5 else 0.0,
                                  "glitch": 1 - u,
                                  "dx": rnd_signed(c.seed, c.i, int(u * 20), 5) * 0.15 * c.S * (1 - u)}),
    "flash": (0.4, lambda u, c: {"a": ease("outQuad", clamp(u * 2)), "bright": 1 - u,
                                 "s": 1 + 0.15 * (1 - ease("outCubic", u))}),
    # ブロック全体を左から現す（マスクで処理。文字単位では何もしない）
    "wipe": (0.5, lambda u, c: {}),
}
BLOCK_IN = {"wipe"}


# ---------------- 退場 ----------------

def _out_slide(u, c):
    e = ease(c.ease, u, "inCubic")
    vx, vy = _dir_vec(c.dir)
    return {"a": 1 - ease("inQuad", u), "dx": vx * e * c.S, "dy": vy * e * c.S}


def _out_scatter(u, c):
    e = ease(c.ease, u, "outCubic")
    ang = rnd(c.seed, c.i, 11) * TAU
    dist = (1.0 + rnd(c.seed, c.i, 12)) * c.S * 1.5
    return {"a": 1 - ease("inQuad", u), "dx": math.cos(ang) * dist * e,
            "dy": math.sin(ang) * dist * e + 0.6 * c.S * u * u,
            "r": rnd_signed(c.seed, c.i, 13) * 240 * e}


OUT_FX = {
    "none": (0.0, lambda u, c: {}),
    "fade": (0.3, lambda u, c: {"a": 1 - ease(c.ease, u, "inQuad")}),
    "rise": (0.35, lambda u, c: {"a": 1 - u, "dy": -ease(c.ease, u, "inCubic") * 0.5 * c.S}),
    "sink": (0.35, lambda u, c: {"a": 1 - u, "dy": ease(c.ease, u, "inCubic") * 0.5 * c.S}),
    "slide": (0.35, _out_slide),
    "shrink": (0.3, lambda u, c: {"a": 1 - ease("inQuad", u), "s": 1 - ease(c.ease, u, "inCubic")}),
    "growOut": (0.35, lambda u, c: {"a": 1 - u, "s": 1 + 0.8 * ease(c.ease, u, "outCubic")}),
    "zoomThrough": (0.35, lambda u, c: {"a": 1 - ease("inQuad", u),
                                        "s": 1 + 3 * ease(c.ease, u, "inCubic"), "blur": u * 0.1 * c.S}),
    "blurOut": (0.4, lambda u, c: {"a": 1 - ease("inQuad", u), "blur": u * 0.25 * c.S}),
    "scatter": (0.6, _out_scatter),
    "erase": (0.0, lambda u, c: {}),
    "flicker": (0.45, lambda u, c: {"a": 1 - _flicker(u, c) if u < 1 else 0.0}),
    "glitch": (0.35, lambda u, c: {"a": 0.0 if u > 0.85 or rnd(c.seed, c.i, int(u * 20), 9) < u * 0.6 else 1.0,
                                   "glitch": u,
                                   "dx": rnd_signed(c.seed, c.i, int(u * 20), 6) * 0.15 * c.S * u}),
    "wipe": (0.4, lambda u, c: {}),
}
BLOCK_OUT = {"wipe"}


# ---------------- 表示中 ----------------
# 関数は (t, c) を受け取る。t は表示中に入ってからの秒、c.period は周期の秒、c.amp は強さの倍率。
# float / wave / pulse / blink / glow は周期的なので、hold.dur を周期の整数倍にすると切れ目なくループする。

def _hold_shake(t, c):
    k = int(t * 30)
    amp = 0.035 * c.S * c.amp
    return {"dx": rnd_signed(c.seed, c.i, k, 21) * amp, "dy": rnd_signed(c.seed, c.i, k, 22) * amp}


def _hold_pulse(t, c):
    beat = (t / c.period) % 1.0
    kick = math.exp(-beat * 9) + 0.6 * math.exp(-max(0.0, beat - 0.22) * 9) * (beat > 0.22)
    return {"s": 1 + 0.07 * c.amp * kick}


def _hold_flicker(t, c):
    k = int(t * 15)
    return {"a": 0.35 if rnd(c.seed, k, 31) < 0.08 else 1.0}


def _hold_glitch(t, c):
    k = int(t * 12)
    on = rnd(c.seed, k, 41) < 0.12
    return {"glitch": 0.8 * c.amp if on else 0.0,
            "dx": rnd_signed(c.seed, c.i, k, 42) * 0.08 * c.S if on else 0.0}


HOLD_FX = {
    "none": lambda t, c: {},
    "float": lambda t, c: {"dy": math.sin(TAU * t / (c.period * 1.6) + c.i * 0.5) * 0.06 * c.S * c.amp},
    "wave": lambda t, c: {"dy": math.sin(TAU * t / c.period - c.i * 0.6) * 0.12 * c.S * c.amp},
    "pulse": _hold_pulse,
    "shake": _hold_shake,
    "blink": lambda t, c: {"a": 1.0 if (t / c.period) % 1.0 < 0.6 else 0.15},
    "glow": lambda t, c: {"glow": 0.55 + 0.45 * math.cos(TAU * t / c.period) * c.amp},
    "flicker": _hold_flicker,
    "glitch": _hold_glitch,
}

PERIODIC_HOLD = {"none", "float", "wave", "pulse", "blink", "glow"}


def hold_period(name, period):
    """表示中の効果がちょうど一周する秒数（周期的でなければ None）。"""
    if name not in PERIODIC_HOLD:
        return None
    if name == "none":
        return 0.0
    return period * (1.6 if name == "float" else 1.0)
