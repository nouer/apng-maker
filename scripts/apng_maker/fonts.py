"""フォントの解決。別名（gothic / mincho）か、フォントファイルのパスを受け付ける。"""

import functools
import os
import subprocess

from PIL import ImageFont

FAMILY_ALIASES = {
    "gothic": "Noto Sans CJK JP",
    "sans": "Noto Sans CJK JP",
    "mincho": "Noto Serif CJK JP",
    "serif": "Noto Serif CJK JP",
}

WEIGHT_STYLES = {
    "thin": "Thin", "light": "Light", "regular": "Regular", "medium": "Medium",
    "semibold": "SemiBold", "bold": "Bold", "black": "Black", "heavy": "Black",
}


class FontError(ValueError):
    pass


@functools.lru_cache(maxsize=64)
def resolve(family, weight="bold"):
    """(ファイルパス, TTC内の番号) を返す。"""
    if os.path.isfile(family):
        return family, 0
    name = FAMILY_ALIASES.get(family, family)
    style = WEIGHT_STYLES.get(str(weight).lower(), str(weight))
    try:
        res = subprocess.run(
            ["fc-match", "-f", "%{file}:%{index}:%{family}", f"{name}:style={style}"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as e:
        raise FontError(f"fc-match でフォントを探せませんでした: {family} ({e})") from e
    path, index, found = res.split(":", 2)
    if name.split()[0].lower() not in found.lower():
        raise FontError(
            f"フォント '{family}' が見つかりません（代わりに '{found}' が選ばれました）。"
            " ファイルパスを直接指定してください。"
        )
    return path, int(index or 0)


@functools.lru_cache(maxsize=256)
def load(family, weight, size):
    path, index = resolve(family, weight)
    return ImageFont.truetype(path, max(1, int(round(size))), index=index)
