"""書き出し：APNG・PNG静止画・連番PNG・スプライトシート（+JSON）・確認用の一覧画像。

APNG の差分矩形と同一フレームの結合は Pillow が行う。256色化は全フレームで1つのパレットを
共有させる（APNG はパレットを1つしか持てないため）。
"""

import json
import math
import os
import re
from bisect import bisect_left

from PIL import Image, ImageDraw

PALETTE_PIXEL_LIMIT = 40_000_000  # 全フレームを縦に並べて減色するときの上限


def frame_schedule(duration, fps):
    """描く時刻と、各フレームの表示時間（ms）を返す。

    時刻は 0, 1/fps, 2/fps, … を duration の手前まで1つも飛ばさずに取り、最後に duration
    ちょうど（完成・消えきった状態）の1枚を足す。表示時間は時刻の差から求めるので、
    再生時間の合計は duration ＋ 最後の1枚の 1/fps になる。"""
    n = max(1, math.ceil(duration * fps - 1e-9))
    times = [k / fps for k in range(n)]
    if duration > times[-1] + 1e-9:
        times.append(duration)
    ticks = [round(t * 1000) for t in times]
    durs = [b - a for a, b in zip(ticks, ticks[1:])]
    durs.append(max(1, round(1000 / fps)))
    return times, durs


def segments_in_frames(segments, times):
    """区間（秒）を、フレーム番号の半開区間 [開始, 終了) にする。
    フレームは描いた時刻で区間に入れる（四捨五入すると、登場途中の絵が hold に入る）。"""
    out = {k: [bisect_left(times, a - 1e-9), bisect_left(times, b - 1e-9)]
           for k, (a, b) in segments.items()}
    out["out"][1] = len(times)  # 終了時刻ちょうどの1枚も out に含める
    return out


def durations_ms(count, fps):
    """フレームごとの表示時間（ms）。丸め誤差が積もらないように配る。"""
    out, acc = [], 0
    for k in range(1, count + 1):
        t = int(round(k * 1000 / fps))
        out.append(max(1, t - acc))
        acc = t
    return out


def union_bbox(frames):
    box = None
    for f in frames:
        b = f.getchannel("A").getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]),
                                         max(box[2], b[2]), max(box[3], b[3]))
    return box


def crop_to_content(img):
    """透明な余白を切り落とした (画像, 左上x, 左上y)。空なら (None, 0, 0)。"""
    box = img.getchannel("A").getbbox()
    if box is None:
        return None, 0, 0
    return img.crop(box), box[0], box[1]


def assemble(pieces, size, box):
    """crop_to_content で切った断片を、描画面 size のうち box の範囲の画像へ戻す。"""
    out = []
    for piece, x, y in pieces:
        frame = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]))
        if piece is not None:
            frame.paste(piece, (x - box[0], y - box[1]))
        out.append(frame)
    return out


def pieces_bbox(pieces, size, pad=0):
    """断片すべてを含む矩形（pad つき、描画面の内側）。すべて空なら描画面全体。"""
    boxes = [(x, y, x + p.width, y + p.height) for p, x, y in pieces if p is not None]
    if not boxes:
        return (0, 0) + tuple(size)
    W, H = size
    return (max(0, min(b[0] for b in boxes) - pad), max(0, min(b[1] for b in boxes) - pad),
            min(W, max(b[2] for b in boxes) + pad), min(H, max(b[3] for b in boxes) + pad))


def trim(frames, pad=0, extra=()):
    """全フレームで共通の透明な余白を切り落とす。(新フレーム, 切り抜き矩形) を返す。"""
    box = union_bbox(list(frames) + list(extra))
    if box is None:
        return list(frames), (0, 0) + frames[0].size
    W, H = frames[0].size
    box = (max(0, box[0] - pad), max(0, box[1] - pad), min(W, box[2] + pad), min(H, box[3] + pad))
    return [f.crop(box) for f in frames], box


def quantize_shared(frames, colors=256):
    """全フレームで共有するパレットへ減色する。大きすぎるときは None。"""
    w, h = frames[0].size
    if w * h * len(frames) > PALETTE_PIXEL_LIMIT:
        return None
    strip = Image.new("RGBA", (w, h * len(frames)))
    for i, f in enumerate(frames):
        strip.paste(f, (0, h * i))
    q = strip.quantize(colors, method=Image.Quantize.FASTOCTREE)
    return [q.crop((0, h * i, w, h * (i + 1))) for i in range(len(frames))]


def save_apng(frames, path, durations, loop=0, poster=None, palette=False):
    """APNG を保存する。poster を渡すと、APNG 非対応の環境で表示される静止画になる。
    loop: 0 = 無限、n = n 回。
    戻り値は (モード 'RGBA'/'P', 書き込んだフレームを RGBA にしたもの)。256色化したときは
    減色後の絵になるので、プレビューやシートはこちらを使う。"""
    images = list(frames) if poster is None else [poster] + list(frames)
    mode = "RGBA"
    if palette:
        q = quantize_shared(images)
        if q is not None:
            images, mode = q, "P"
    first, rest = images[0], images[1:]
    durs = list(durations)  # poster があっても、Pillow はアニメーションのフレームにだけ割り当てる
    kwargs = dict(save_all=True, append_images=rest, duration=durs, loop=loop,
                  disposal=0, blend=0, optimize=True)
    if poster is not None:
        kwargs["default_image"] = True
    if len(images) == 1:
        first.save(path, optimize=True)
    else:
        first.save(path, format="PNG", **kwargs)
    start = 0 if poster is None else 1
    written = [im.convert("RGBA") for im in images[start:]] if mode == "P" else list(frames)
    return mode, written


def save_sequence(frames, out_dir, stem):
    os.makedirs(out_dir, exist_ok=True)
    width = max(4, len(str(len(frames) - 1)))
    paths = []
    for i, f in enumerate(frames):
        p = os.path.join(out_dir, f"{stem}_{i:0{width}d}.png")
        f.save(p, optimize=True)
        paths.append(p)
    return paths


def save_sheet(frames, path, durations, columns=None, spacing=0, meta=None):
    """フレームを格子に並べた1枚画像と、同名の .json を書く。"""
    n = len(frames)
    fw, fh = frames[0].size
    cols = columns or max(1, math.ceil(math.sqrt(n)))
    rows = math.ceil(n / cols)
    sheet = Image.new("RGBA", (cols * fw + (cols - 1) * spacing, rows * fh + (rows - 1) * spacing))
    entries = []
    for i, f in enumerate(frames):
        x, y = (i % cols) * (fw + spacing), (i // cols) * (fh + spacing)
        sheet.paste(f, (x, y))
        entries.append({"x": x, "y": y, "w": fw, "h": fh, "duration_ms": durations[i]})
    sheet.save(path, optimize=True)
    info = {"image": os.path.basename(path), "frame_width": fw, "frame_height": fh,
            "columns": cols, "rows": rows, "count": n, "spacing": spacing, "frames": entries}
    info.update(meta or {})
    json_path = os.path.splitext(path)[0] + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    return json_path


def _checker(size, cell=12):
    w, h = size
    img = Image.new("RGBA", size, (200, 200, 200, 255))
    d = ImageDraw.Draw(img)
    for y in range(0, h, cell):
        for x in range((y // cell) % 2 * cell, w, cell * 2):
            d.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(150, 150, 150, 255))
    return img


def contact_sheet(frames, times, path, picks=12, cell_w=320):
    """確認用：フレームを間引いて市松模様の上に並べ、時刻を添えた1枚を作る。"""
    n = len(frames)
    idx = sorted({round(k * (n - 1) / max(1, picks - 1)) for k in range(min(picks, n))})
    fw, fh = frames[0].size
    k = min(1.0, cell_w / fw)
    tw, th = max(1, int(fw * k)), max(1, int(fh * k))
    cols = min(4, len(idx))
    rows = math.ceil(len(idx) / cols)
    label_h = 16
    sheet = Image.new("RGBA", (cols * (tw + 4) + 4, rows * (th + label_h + 4) + 4), (255, 255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for j, i in enumerate(idx):
        x = 4 + (j % cols) * (tw + 4)
        y = 4 + (j // cols) * (th + label_h + 4)
        cell = _checker((tw, th))
        cell.alpha_composite(frames[i].resize((tw, th), Image.LANCZOS))
        sheet.paste(cell, (x, y + label_h))
        d.text((x, y + 2), f"#{i}  t={times[i]:.2f}s", fill=(0, 0, 0, 255))
    sheet.convert("RGB").save(path)
    return path


# ---------------- 既存の画像を扱う ----------------

def _natural_key(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def collect_inputs(inputs):
    """ファイル・ディレクトリ・ワイルドカードから PNG/画像 の一覧を自然順で返す。"""
    import glob

    exts = (".png", ".webp", ".jpg", ".jpeg", ".gif", ".bmp")
    paths = []
    for item in inputs:
        if os.path.isdir(item):
            paths.extend(sorted((os.path.join(item, n) for n in os.listdir(item)
                                 if n.lower().endswith(exts)), key=_natural_key))
        elif any(c in item for c in "*?["):
            paths.extend(sorted(glob.glob(item), key=_natural_key))
        else:
            paths.append(item)
    if not paths:
        raise FileNotFoundError("入力画像が見つかりません: " + " ".join(inputs))
    return paths


def load_frames(paths, fit="pad"):
    """画像を RGBA で読む。大きさが揃っていなければ、最大の大きさへ中央寄せで余白を足す。"""
    frames = []
    for p in paths:
        with Image.open(p) as im:
            frames.append(im.convert("RGBA"))
    W = max(f.width for f in frames)
    H = max(f.height for f in frames)
    if all(f.size == (W, H) for f in frames):
        return frames
    if fit == "error":
        raise ValueError("フレームの大きさが揃っていません（--fit pad で余白を足せます）")
    out = []
    for f in frames:
        c = Image.new("RGBA", (W, H))
        c.paste(f, ((W - f.width) // 2, (H - f.height) // 2))
        out.append(c)
    return out


def split_apng(path):
    """APNG を、合成済みのフレーム（RGBA）と表示時間 ms に分解する。"""
    from . import apng_check

    info = apng_check.inspect(path)
    # 非対応環境向けの静止画がアニメーションに含まれないとき、Pillow はそれを 0 枚目として数える
    skip = 1 if info["animated"] and not info["default_image_is_frame"] else 0
    frames, durs = [], []
    elapsed, prev_tick = 0.0, 0
    with Image.open(path) as im:
        for i in range(skip, getattr(im, "n_frames", 1)):
            im.seek(i)
            frames.append(im.convert("RGBA").copy())
            # 1枚ずつ丸めると 1/120 秒が 8ms になり、120枚で 960ms に縮む。経過時刻で丸める
            elapsed += float(im.info.get("duration", 0) or 0)
            tick = round(elapsed)
            durs.append(tick - prev_tick)
            prev_tick = tick
        loop = im.info.get("loop", 0)
    return frames, durs, loop
