"""シーン設定（JSON）の既定値・合成・検証。

長さの単位：font.size 以外の「大きさ」は em（文字サイズの倍数）。時間は秒。
"""

import copy
import json

DEFAULTS = {
    "canvas": {"width": 960, "height": 540, "background": None},
    "text": "テキスト",
    "sub": None,
    "writing": "horizontal",
    "font": {"family": "gothic", "weight": "black", "size": 120,
             "letter_spacing": 0.04, "line_height": 1.3, "kerning": True, "palt": False},
    "ruby": {"size": 0.5, "gap": 0.05},
    "layout": {"align": "center", "anchor": "center", "margin": 40,
               "offset": [0, 0], "auto_fit": True, "wrap_width": None},
    "style": {
        "fill": {"type": "solid", "color": "#ffffff"},
        "strokes": [{"width": 0.08, "color": "#000000"}],
        "shadow": None,
        "glow": None,
    },
    "anim": {
        "start_delay": 0.0,
        "in": {"fx": "fade", "dur": 0.35, "stagger": 0.05, "order": "forward",
               "dir": "left", "ease": None},
        "hold": {"fx": "none", "dur": 1.0, "period": 1.0, "amp": 1.0},
        "out": {"fx": "fade", "dur": 0.3, "stagger": 0.03, "order": "forward",
                "dir": "right", "ease": None},
        "camera_shake": None,
    },
    "deco": {"type": "none", "color": "#000000", "opacity": 0.6, "pad": 0.3,
             "thickness": 0.05, "dur": 0.3, "radius": 0.15},
    "export": {"fps": 30, "loop": 0, "palette": False, "trim": True, "trim_pad": 4,
               "poster": True, "tail": 0.0},
}

SUB_DEFAULTS = {"text": "", "size": 0.42, "position": "above", "gap": 0.25,
                "fill": None, "weight": None, "letter_spacing": 0.15}

CHOICES = {
    "writing": ("horizontal", "vertical"),
    "layout.align": ("left", "center", "right"),
    "layout.anchor": ("top", "center", "bottom"),
    "anim.in.order": ("forward", "reverse", "center", "edges", "random"),
    "anim.out.order": ("forward", "reverse", "center", "edges", "random"),
    "anim.in.dir": ("left", "right", "up", "down"),
    "anim.out.dir": ("left", "right", "up", "down"),
    "deco.type": ("none", "band", "box", "underline", "lines"),
}


class SceneError(ValueError):
    pass


def deep_merge(base, over):
    """base に over を重ねた新しい dict を返す（どちらも書き換えない）。"""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def set_path(scene, dotted, value):
    """'anim.in.fx' のような経路へ値を入れた新しい dict を返す。値は JSON として解釈を試みる。"""
    try:
        value = json.loads(value)
    except (TypeError, ValueError):
        pass
    keys = dotted.split(".")
    patch = value
    for k in reversed(keys):
        patch = {k: patch}
    return deep_merge(scene, patch)


def _get(scene, dotted):
    cur = scene
    for k in dotted.split("."):
        cur = cur[k]
    return cur


def build(user_scene):
    """既定値を補い、検証済みのシーンを返す。"""
    from . import effects  # 循環参照を避けるためここで読む

    scene = deep_merge(DEFAULTS, user_scene)
    if isinstance(scene.get("sub"), str):
        scene["sub"] = {"text": scene["sub"]}
    if scene.get("sub"):
        scene["sub"] = deep_merge(SUB_DEFAULTS, scene["sub"])
    errors = []
    for path, allowed in CHOICES.items():
        if _get(scene, path) not in allowed:
            errors.append(f"{path} = {_get(scene, path)!r}（選べるのは {', '.join(allowed)}）")
    for phase, table in (("in", effects.IN_FX), ("hold", effects.HOLD_FX), ("out", effects.OUT_FX)):
        fx = scene["anim"][phase]["fx"]
        if fx not in table:
            errors.append(f"anim.{phase}.fx = {fx!r}（選べるのは {', '.join(sorted(table))}）")
    if not str(scene["text"]).strip():
        errors.append("text が空です")
    for key in ("width", "height"):
        if not 8 <= int(scene["canvas"][key]) <= 4096:
            errors.append(f"canvas.{key} は 8〜4096 にしてください")
    ex = scene["export"]
    if not 1 <= ex["fps"] <= 120:
        errors.append("export.fps は 1〜120 にしてください")
    if not isinstance(ex["loop"], int) or not 0 <= ex["loop"] <= 2 ** 31 - 1:
        errors.append("export.loop は 0 以上の整数にしてください（0 = 無限）")
    for key in ("trim_pad", "tail"):
        if ex[key] < 0:
            errors.append(f"export.{key} は 0 以上にしてください")
    if errors:
        raise SceneError("シーン設定に誤りがあります:\n  - " + "\n  - ".join(errors))
    return scene


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
