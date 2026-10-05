"""ある時刻の1枚を描く。同じシーン・同じ時刻なら必ず同じ絵になる。"""

import math
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageFilter

from . import deco as deco_mod
from . import effects, layout as layout_mod, sprites as sprites_mod, timeline as timeline_mod
from .util import clamp, composite, new_layer, rnd, rnd_signed, scale_alpha

HOLD_RAMP = 0.25  # 表示中の効果を、登場し終えてから何秒かけて効かせるか（hold 開始までで打ち切る）


@dataclass
class _Ctx:
    S: float
    i: int
    seed: int
    dir: str
    ease: str | None
    period: float = 1.0
    amp: float = 1.0


class Renderer:
    def __init__(self, scene):
        self.scene = scene
        self.layout = layout_mod.compute(scene)
        self.timeline = timeline_mod.build(scene, self.layout)
        self.sprites = sprites_mod.build_all(self.layout, scene)
        self.size = (scene["canvas"]["width"], scene["canvas"]["height"])
        self.seed = int(scene.get("seed", 1))

    @property
    def duration(self):
        return self.timeline.duration

    # ---------- 文字の状態 ----------

    def glyph_state(self, g, t):
        """時刻 t の文字 g の状態。見えないときは None。"""
        if g.aux:   # ルビは親字と同じ動きをする（大きさに比例させると、移動量が親字の半分になり離れる）
            return self.glyph_state(g.base, t)
        tl, anim = self.timeline, self.scene["anim"]
        i = g.index
        if t < tl.in_start[i]:
            return None
        if t >= tl.out_start[i] + tl.out_dur[i] and tl.out_start[i] != float("inf"):
            return None
        st = dict(effects.IDENTITY)
        a_in, a_hold, a_out = anim["in"], anim["hold"], anim["out"]
        if tl.in_dur[i] > 0 and t < tl.in_start[i] + tl.in_dur[i]:
            c = _Ctx(g.size, g.seq, self.seed, a_in["dir"], a_in.get("ease"))
            u = (t - tl.in_start[i]) / tl.in_dur[i]
            st = effects.combine(st, effects.IN_FX[a_in["fx"]][1](u, c))
        own_in_end = tl.in_start[i] + tl.in_dur[i]
        if a_hold["fx"] != "none" and t >= own_in_end:
            c = _Ctx(g.size, g.seq, self.seed, "left", None,
                     max(0.05, a_hold.get("period", 1.0)), a_hold.get("amp", 1.0))
            delta = effects.HOLD_FX[a_hold["fx"]](t - tl.in_end, c)
            # 立ち上げは登場の区間の中だけで行う。hold に入ったら常に全振幅にしないと、
            # hold の最初の周期だけ振幅が小さくなり、ループの継ぎ目でずれる
            k = 1.0 if t >= tl.in_end else clamp((t - own_in_end) / HOLD_RAMP)
            st = effects.combine(st, _ramp(delta, k))
        if t >= tl.out_start[i] and tl.out_dur[i] > 0:
            c = _Ctx(g.size, g.seq, self.seed, a_out["dir"], a_out.get("ease"))
            u = clamp((t - tl.out_start[i]) / tl.out_dur[i])
            st = effects.combine(st, effects.OUT_FX[a_out["fx"]][1](u, c))
        return st if st["a"] > 0.003 else None

    def hold_loopable(self, fps):
        """シートの hold 区間（segments_frames）を繰り返すと、切れ目なくつながるか。"""
        tl, hold = self.timeline, self.scene["anim"]["hold"]
        period = effects.hold_period(hold["fx"], max(0.05, hold.get("period", 1.0)))
        dur = tl.hold_end - tl.in_end
        if period is None or dur <= 1e-9:
            return False
        if period > 0 and not _is_int(dur / period):
            return False
        if not _is_int(dur * fps):
            return False
        if tl.shake and tl.shake[0] < tl.hold_end and sum(tl.shake[:2]) > tl.in_end:
            return False
        return sum(tl.deco_in) <= tl.in_end + 1e-9

    # ---------- 1枚を描く ----------

    def frame(self, t):
        W, H = self.size
        canvas = new_layer(W, H, self.scene["canvas"].get("background"))
        off = self._shake(t)
        tl = self.timeline
        d_open = _progress(t, *tl.deco_in) if tl.deco_in[1] > 0 else (1.0 if t >= tl.deco_in[0] else 0.0)
        d_close = _progress(t, *tl.deco_out) if tl.deco_out else 0.0
        layer = deco_mod.draw(self.size, self.layout, self.scene["deco"], d_open, d_close, off)
        if layer is not None:
            canvas.alpha_composite(layer)
        text = new_layer(W, H)
        tick = int(t * 30)
        for g, sp in zip(self.layout.glyphs, self.sprites):
            if sp is None:
                continue
            st = self.glyph_state(g, t)
            if st is not None:
                self._draw_glyph(text, g, sp, st, off, tick)
        mask = self._wipe_mask(t)
        if mask is not None:
            text.putalpha(ImageChops.multiply(text.getchannel("A"), mask))
        canvas.alpha_composite(text)
        return canvas

    def _shake(self, t):
        sh = self.timeline.shake
        if not sh or not sh[0] <= t < sh[0] + sh[1]:
            return (0.0, 0.0)
        k = 1 - (t - sh[0]) / sh[1]
        tick = int(t * 60)
        return (rnd_signed(self.seed, tick, 51) * sh[2] * k, rnd_signed(self.seed, tick, 52) * sh[2] * k)

    def _draw_glyph(self, dst, g, sp, st, off, tick):
        img = sp.body
        if st["glitch"] > 0.01:
            img = _glitch(img, st["glitch"], g.size, self.seed, g.index, tick)
        if st["bright"] > 0.01:
            white = Image.new("RGBA", img.size, (255, 255, 255, 0))
            white.putalpha(img.getchannel("A"))
            img = Image.blend(img, white, clamp(st["bright"]))
        if sp.glow is not None and st["glow"] > 0.01:
            base = scale_alpha(sp.glow, clamp(st["glow"])).copy()
            base.alpha_composite(img)
            img = base
        img = scale_alpha(img, clamp(st["a"]))
        X, Y = g.cx + st["dx"] + off[0], g.cy + st["dy"] + off[1]
        kx, ky = st["s"] * st["sx"], st["s"] * st["sy"]
        if kx < 0.01 or ky < 0.01:
            return
        blur = st["blur"]
        if abs(kx - 1) < 1e-3 and abs(ky - 1) < 1e-3 and abs(st["r"]) < 0.05:
            if blur > 0.3:
                img = _blur(img, blur)
            composite(dst, img, int(round(X - img.width / 2)), int(round(Y - img.height / 2)))
            return
        out, x0, y0 = _affine(img, X, Y, kx, ky, st["r"], int(blur * 3) + 2)
        if blur > 0.3:
            out = out.filter(ImageFilter.GaussianBlur(blur))
        composite(dst, out, x0, y0)

    def _wipe_mask(self, t):
        tl = self.timeline
        if tl.block_in and t < sum(tl.block_in):
            p, hide_before = _progress(t, *tl.block_in), False
        elif tl.block_out and t >= tl.block_out[0]:
            p, hide_before = _progress(t, *tl.block_out), True
        else:
            return None
        W, H = self.size
        x0, y0, x1, y1 = self.layout.box
        soft = self.layout.size * 0.6
        v = self.layout.vertical
        lo, hi = (y0, y1) if v else (x0, x1)
        lo, hi = lo - soft, hi + soft
        edge = lo + (hi - lo + soft) * p
        length = H if v else W
        row = Image.new("L", (length, 1) if not v else (1, length))
        for i in range(length):
            val = clamp((edge - i) / soft)  # 1 = 見える
            if hide_before:
                val = 1 - val
            row.putpixel((i, 0) if not v else (0, i), int(val * 255))
        return row.resize((W, H), Image.NEAREST)


def _is_int(x, eps=1e-6):
    return abs(x - round(x)) < eps


def completed_frame(scene):
    """完成状態の1枚（APNG 非対応環境向けの静止画・--still）。

    アニメーションのある時刻を描くのではなく、「退場なし・画面揺れなし」にしたシーンで、
    文字と装飾が出そろった時刻を描く。hold.dur=0 で即時退場する設定でも空にならない。"""
    from .scene import deep_merge

    still = Renderer(deep_merge(scene, {"anim": {"out": {"fx": "none"}, "camera_shake": None}}))
    tl = still.timeline
    return still.frame(max(tl.in_end, sum(tl.deco_in)))


def _progress(t, start, dur):
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return clamp((t - start) / dur)


def _ramp(delta, k):
    """効果の差分を k（0→1）の割合だけ効かせる。"""
    if k >= 1:
        return delta
    out = {}
    for key, v in delta.items():
        base = 1.0 if key in ("a", "s", "sx", "sy", "glow") else 0.0
        out[key] = base + (v - base) * k
    return out


def _blur(img, radius):
    m = int(radius * 3) + 2
    big = Image.new("RGBA", (img.width + 2 * m, img.height + 2 * m), (0, 0, 0, 0))
    big.paste(img, (m, m))
    return big.filter(ImageFilter.GaussianBlur(radius))


def _affine(img, X, Y, kx, ky, deg, margin):
    """img の中心を (X, Y) に置き、拡大・回転した画像と左上座標を返す（小数の位置も反映）。"""
    w, h = img.size
    th = math.radians(deg)
    cos, sin = math.cos(th), math.sin(th)
    hw, hh = w * kx / 2, h * ky / 2
    ex = abs(hw * cos) + abs(hh * sin) + margin
    ey = abs(hw * sin) + abs(hh * cos) + margin
    ox0, oy0 = int(math.floor(X - ex)), int(math.floor(Y - ey))
    ow, oh = int(math.ceil(X + ex)) - ox0, int(math.ceil(Y + ey)) - oy0
    qx, qy = ox0 - X, oy0 - Y
    coeffs = (cos / kx, sin / kx, (qx * cos + qy * sin) / kx + w / 2,
              -sin / ky, cos / ky, (-qx * sin + qy * cos) / ky + h / 2)
    out = img.transform((ow, oh), Image.AFFINE, coeffs, resample=Image.BICUBIC)
    return out, ox0, oy0


def _glitch(img, amount, S, seed, index, tick):
    """横方向のずれと色ずれ。"""
    w, h = img.size
    shift = max(1, int(amount * 0.06 * S))
    alpha = img.getchannel("A")
    red = Image.new("RGBA", img.size, (255, 0, 60, 0))
    red.putalpha(alpha.point(lambda v: v * 6 // 10))
    cyan = Image.new("RGBA", img.size, (0, 230, 255, 0))
    cyan.putalpha(alpha.point(lambda v: v * 6 // 10))
    out = new_layer(w, h)
    composite(out, red, -shift, 0)
    composite(out, cyan, shift, 0)
    out.alpha_composite(img)
    strips = 6
    sh = max(1, h // strips)
    for k in range(strips):
        if rnd(seed, index, tick, k, 61) < amount * 0.7:
            dx = int(rnd_signed(seed, index, tick, k, 62) * amount * 0.12 * S)
            box = (0, k * sh, w, min(h, (k + 1) * sh))
            piece = out.crop(box)
            hole = new_layer(w, box[3] - box[1])
            out.paste(hole, box[:2])
            composite(out, piece, dx, box[1])
    return out
