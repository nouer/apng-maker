"""タイムライン：各文字の登場開始・退場開始と、全体の区間（in / hold / out）。

  t0 ─ 装飾が開く ─ 文字が順に登場 ─ in_end ─ 表示中(hold) ─ hold_end ─ 文字が順に退場 ─ end
"""

from dataclasses import dataclass, field

from . import effects
from .util import hash32


@dataclass
class Timeline:
    in_start: list = field(default_factory=list)
    in_dur: list = field(default_factory=list)
    out_start: list = field(default_factory=list)
    out_dur: list = field(default_factory=list)
    text_start: float = 0.0
    in_end: float = 0.0
    hold_end: float = 0.0
    out_end: float = 0.0
    duration: float = 0.0
    deco_in: tuple = (0.0, 0.0)     # (開始, 長さ)
    deco_out: tuple | None = None
    block_in: tuple | None = None   # wipe など、ブロック全体の登場 (開始, 長さ)
    block_out: tuple | None = None
    shake: tuple | None = None      # 画面揺れ (開始, 長さ, 振幅px)

    def segments(self):
        """ゲーム側で使う区間（秒）。hold をループさせ、in と out は1回だけ流す使い方を想定。"""
        return {"in": [0.0, self.in_end], "hold": [self.in_end, self.hold_end],
                "out": [self.hold_end, self.duration]}


def ranks(count, order, seed):
    """表示順。ranks[i] は i 番目の文字が何番目に動くか。"""
    idx = list(range(count))
    if order == "reverse":
        return [count - 1 - i for i in idx]
    if order in ("center", "edges"):
        mid = (count - 1) / 2
        dist = [abs(i - mid) for i in idx]
        key = sorted(idx, key=lambda i: (dist[i] if order == "center" else -dist[i], i))
    elif order == "random":
        key = sorted(idx, key=lambda i: hash32(seed, i, 99))
    else:
        return idx
    out = [0] * count
    rank, prev = -1, None
    for i in key:  # 同じ距離の文字（中央から左右対称）は同時に動かす
        d = round(abs(i - (count - 1) / 2), 3) if order in ("center", "edges") else i
        if d != prev:
            rank += 1
            prev = d
        out[i] = rank
    return out


def build(scene, layout):
    anim = scene["anim"]
    a_in, a_hold, a_out = anim["in"], anim["hold"], anim["out"]
    seed = int(scene.get("seed", 1))
    deco = scene["deco"]
    deco_on = deco["type"] != "none"
    t0 = max(0.0, anim.get("start_delay", 0.0))
    lead = min(0.3, deco["dur"] * 0.6) if deco_on and deco["type"] in ("band", "box") else 0.0
    text_start = t0 + lead

    glyphs = layout.glyphs
    n_seq = sum(1 for g in glyphs if not g.blank)
    in_fx, out_fx = a_in["fx"], a_out["fx"]
    in_dur = max(0.0, a_in.get("dur", effects.IN_FX[in_fx][0]))
    out_dur = max(0.0, a_out.get("dur", effects.OUT_FX[out_fx][0]))
    if in_fx in ("typewriter", "none"):
        in_dur = 0.0
    if out_fx in ("erase", "none"):
        out_dur = 0.0
    tl = Timeline(text_start=text_start)

    block_in = in_fx in effects.BLOCK_IN
    r_in = ranks(n_seq, a_in["order"], seed)
    for g in glyphs:
        if block_in or in_fx == "none":
            start = text_start
        else:
            start = text_start + r_in[min(g.seq, n_seq - 1)] * a_in["stagger"]
        tl.in_start.append(start)
        tl.in_dur.append(0.0 if block_in else in_dur)
    tl.in_end = max(s + d for s, d in zip(tl.in_start, tl.in_dur)) if glyphs else text_start
    if block_in:
        tl.block_in = (text_start, in_dur)
        tl.in_end = text_start + in_dur
    if in_fx == "typewriter":  # 最後の文字が出た瞬間ではなく、1文字ぶんの間を置いて完了とする
        tl.in_end += a_in["stagger"]
    tl.hold_end = tl.in_end + max(0.0, a_hold["dur"])

    block_out = out_fx in effects.BLOCK_OUT
    r_out = ranks(n_seq, a_out["order"], seed + 1)
    for g in glyphs:
        if out_fx == "none":
            tl.out_start.append(float("inf"))
            tl.out_dur.append(0.0)
        elif block_out:
            tl.out_start.append(tl.hold_end + out_dur)
            tl.out_dur.append(0.0)
        else:
            tl.out_start.append(tl.hold_end + r_out[min(g.seq, n_seq - 1)] * a_out["stagger"])
            tl.out_dur.append(out_dur)
    if out_fx == "none":
        tl.out_end = tl.hold_end
    elif block_out:
        tl.block_out = (tl.hold_end, out_dur)
        tl.out_end = tl.hold_end + out_dur
    else:
        tl.out_end = max(s + d for s, d in zip(tl.out_start, tl.out_dur))
        if out_fx == "erase":
            tl.out_end += a_out["stagger"]

    if deco_on:
        tl.deco_in = (t0, deco["dur"])
        if out_fx != "none":
            close = max(tl.hold_end, tl.out_end - deco["dur"] * 0.5)
            tl.deco_out = (close, deco["dur"])
            tl.out_end = max(tl.out_end, close + deco["dur"])
    cam = anim.get("camera_shake")
    if cam:
        at = {"in_end": tl.in_end, "text_start": text_start}.get(cam.get("at", "in_end"), tl.in_end)
        if isinstance(cam.get("at"), (int, float)):
            at = float(cam["at"])
        tl.shake = (at, cam.get("dur", 0.3), cam.get("amp", 0.06) * layout.size)
    tl.duration = tl.out_end + max(0.0, scene["export"].get("tail", 0.0))
    return tl
