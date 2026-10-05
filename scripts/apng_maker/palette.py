"""大きなアニメーションを、全フレーム共通の256色パレットへ減色する。

全フレームを1枚に並べて減色すると、画素数に比例してメモリを使う（1920×1080 を300枚なら
2GB を超える）。ここでは次の2段に分け、メモリを1フレーム分と見本の分で済ませる。

1. 見本：フレームを間引いて並べた見本から、パレットを作る。Pillow は透明度つきの色を
   決まったパレットへ当てはめられないので、透明度を ALPHA_LEVELS 段に分け、段ごとに
   RGB だけのパレットを作る。どの段がどれだけ使われているかは全フレームで数え、
   色数はその割合で配る。間引いた見本に無い段があれば、その段を含むフレームを見本に足す
   （足さないと、その段の画素を別の透明度へ寄せることになり、文字が消えることがある）
2. 当てはめ：各フレームを透明度の段ごとに切り分け、その段のパレットへ RGB で当てはめる
   （ディザなし。ディザを掛けるとフレームごとに模様が変わり、ちらつく）

透明度を段にまとめるぶん、文字の輪郭のなめらかさはわずかに落ちる。
"""

from PIL import Image, ImageStat

ALPHA_LEVELS = 16
SAMPLE_PIXELS = 8_000_000


def _picks(frames, budget, presence):
    """見本にするフレームの番号。等間隔に間引き、見本に無い段を含むフレームを足す。"""
    w, h = frames[0].size
    count = max(1, min(len(frames), budget // max(1, w * h)))
    picks = {round(k * (len(frames) - 1) / max(1, count - 1)) for k in range(count)}
    covered = set().union(*(presence[i] for i in picks))
    for i, levels in enumerate(presence):
        if levels - covered:
            picks.add(i)
            covered |= levels
    return sorted(picks)


def _sample(frames, picks):
    w, h = frames[0].size
    strip = Image.new("RGBA", (w, h * len(picks)))
    for j, i in enumerate(picks):
        strip.paste(frames[i], (0, h * j))
    return strip


def _allocate(counts, total_colors):
    """段ごとの色数。どの段にも最低1色、残りは画素数の割合で配る。"""
    levels = [l for l, c in counts.items() if c > 0]
    if not levels:
        return {}
    total = sum(counts[l] for l in levels)
    alloc = {l: max(1, int(total_colors * counts[l] / total)) for l in levels}
    while sum(alloc.values()) > total_colors:
        biggest = max(alloc, key=alloc.get)
        alloc[biggest] -= 1
    return alloc


class SharedPalette:
    def __init__(self, frames, colors=256, levels=ALPHA_LEVELS, sample_pixels=SAMPLE_PIXELS):
        self.lut = [round(v * (levels - 1) / 255) for v in range(256)]
        counts = {l: 0 for l in range(1, levels)}
        presence = []
        for f in frames:
            hist = f.getchannel("A").point(self.lut).histogram()
            presence.append({l for l in counts if hist[l]})
            for l in counts:
                counts[l] += hist[l]
        strip = _sample(frames, _picks(frames, sample_pixels, presence))
        lvl = strip.getchannel("A").point(self.lut)
        rgb = strip.convert("RGB")
        self.entries = [(0, 0, 0, 0)]       # 0 番は完全な透明
        self.subs = {}                      # 段 → (パレットでの開始番号, [RGB…])
        for level, n in _allocate(counts, colors - 1).items():
            mask = lvl.point(lambda v, level=level: 255 if v == level else 0)
            fill = tuple(int(m) for m in ImageStat.Stat(rgb, mask).mean)
            img = Image.new("RGB", rgb.size, fill)   # 段の外は段の平均色で埋め、色を無駄にしない
            img.paste(rgb, mask=mask)
            q = img.quantize(n, method=Image.Quantize.MEDIANCUT)
            pal = q.getpalette()
            used = sorted(i for _, i in q.getcolors(256))
            cols = [tuple(pal[3 * i:3 * i + 3]) for i in used]
            alpha = round(level * 255 / (levels - 1))
            self.subs[level] = (len(self.entries), cols)
            self.entries.extend(c + (alpha,) for c in cols)
        # 見本に無かった段は、いちばん近い段へ寄せる
        present = sorted(self.subs)
        self.level_map = [0] + [min(present, key=lambda p: abs(p - l)) if present else 0
                                for l in range(1, levels)]
        self.flat = [v for e in self.entries for v in e]
        self.flat += [0, 0, 0, 0] * (256 - len(self.entries))
        self._pal_images = {level: _palette_image(cols) for level, (_, cols) in self.subs.items()}

    def apply(self, frame):
        """1フレームを、このパレットの P 画像にする。"""
        lvl = frame.getchannel("A").point([self.level_map[x] for x in self.lut])
        out = Image.new("L", frame.size, 0)
        rgb = frame.convert("RGB")
        for level, (base, cols) in self.subs.items():
            mask = lvl.point(lambda v, level=level: 255 if v == level else 0)
            box = mask.getbbox()
            if box is None:
                continue
            q = rgb.crop(box).quantize(palette=self._pal_images[level], dither=Image.Dither.NONE)
            n = len(cols)
            idx = Image.frombytes("L", q.size, q.tobytes()).point(
                lambda i, base=base, n=n: base + (i if i < n else 0))
            out.paste(idx, box[:2], mask.crop(box))
        result = Image.frombytes("P", frame.size, out.tobytes())
        result.putpalette(self.flat, rawmode="RGBA")
        return result


def _palette_image(cols):
    """RGB の色リストを、quantize(palette=…) に渡せる P 画像にする。
    余りの番号は先頭の色で埋める（黒で埋めると暗い色がそちらへ吸われる）。"""
    flat = [v for c in cols for v in c]
    flat += list(cols[0]) * (256 - len(cols))
    img = Image.new("P", (1, 1))
    img.putpalette(flat)
    return img


def quantize(frames, colors=256):
    pal = SharedPalette(frames, colors)
    return [pal.apply(f) for f in frames]
