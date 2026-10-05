"""APNG のチャンクを直接読んで、規格どおりかを確かめる（Pillow に頼らない検査）。

見ているもの（PNG 第3版の APNG の要件から、壊れ方として起こりやすいもの）：
  - 署名・チャンクの長さ・CRC・途中で切れていないこと
  - IHDR で始まり IEND で終わる。acTL は最初の IDAT より前に1つだけ
  - fcTL / fdAT の通し番号が 0 から連続している
  - fcTL の寸法が正で画像の内側にあり、dispose_op は 0〜2、blend_op は 0〜1
  - 既定画像（IDAT）がフレームを兼ねるとき、その fcTL は画像全体と同じ大きさで原点に置く
  - どの fcTL にも、続く画像データ（IDAT か fdAT）がある
  - acTL のフレーム数と fcTL の数が一致し、1 以上
壊れていれば ValueError を投げる。
"""

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _read_chunks(data):
    if not data.startswith(SIGNATURE):
        raise ValueError("PNG の署名がありません")
    pos, chunks = 8, []
    while pos < len(data):
        if pos + 12 > len(data):
            raise ValueError("チャンクの見出しか CRC が欠けています（ファイルが途中で切れています）")
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        if pos + 12 + length > len(data):
            raise ValueError(f"{ctype!r} チャンクが途中で終わっています")
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise ValueError(f"{ctype.decode('latin-1')} の CRC が合いません")
        chunks.append((ctype.decode("latin-1"), body))
        pos += 12 + length
    if not chunks:
        raise ValueError("チャンクがありません")
    return chunks


def _check_fctl(body, w, h, before_idat):
    if len(body) != 26:
        raise ValueError("fcTL の長さが 26 バイトではありません")
    seq, fw, fh, fx, fy, num, den, dispose, blend = struct.unpack(">IIIIIHHBB", body)
    if fw == 0 or fh == 0:
        raise ValueError("フレームの幅か高さが 0 です")
    if fx + fw > w or fy + fh > h:
        raise ValueError("フレームの矩形が画像の外へはみ出しています")
    if dispose > 2 or blend > 1:
        raise ValueError(f"dispose_op={dispose} / blend_op={blend} は規格にない値です")
    if before_idat and (fx, fy, fw, fh) != (0, 0, w, h):
        raise ValueError("既定画像を兼ねるフレームは、画像全体と同じ大きさで原点に置く必要があります")
    return num / (den or 100)


def inspect(path):
    """チャンクを読んで要約を返す。壊れていれば ValueError。"""
    with open(path, "rb") as f:
        chunks = _read_chunks(f.read())
    names = [c[0] for c in chunks]
    if names[0] != "IHDR" or len(chunks[0][1]) != 13:
        raise ValueError("IHDR で始まっていません")
    if names[-1] != "IEND":
        raise ValueError("IEND で終わっていません")
    if "IDAT" not in names:
        raise ValueError("IDAT がありません")
    w, h, depth, ctype_ = struct.unpack(">IIBB", chunks[0][1][:10])
    info = {"width": w, "height": h, "bit_depth": depth,
            "color_type": {6: "RGBA", 3: "palette", 2: "RGB", 0: "gray", 4: "gray+alpha"}.get(ctype_, ctype_),
            "bytes": sum(12 + len(b) for _, b in chunks) + 8, "animated": "acTL" in names}
    if not info["animated"]:
        if "fcTL" in names or "fdAT" in names:
            raise ValueError("acTL が無いのに fcTL / fdAT があります")
        return info

    first_idat = names.index("IDAT")
    if names.count("acTL") != 1 or names.index("acTL") > first_idat:
        raise ValueError("acTL は最初の IDAT より前に1つだけ置く必要があります")
    actl = dict(chunks)["acTL"]
    if len(actl) != 8:
        raise ValueError("acTL の長さが 8 バイトではありません")
    num_frames, num_plays = struct.unpack(">II", actl)
    if num_frames == 0:
        raise ValueError("acTL のフレーム数が 0 です")

    expected_seq, delays = 0, []
    kind, has_data = None, True   # 直前の fcTL が待つ画像データの種類と、受け取ったか
    for i, (name, body) in enumerate(chunks):
        if name in ("fcTL", "fdAT"):
            if len(body) < 4 or struct.unpack(">I", body[:4])[0] != expected_seq:
                raise ValueError("fcTL / fdAT の通し番号が 0 から連続していません")
            expected_seq += 1
        if name == "fcTL":
            if not has_data:
                raise ValueError("画像データの無い fcTL があります")
            delays.append(_check_fctl(body, w, h, before_idat=i < first_idat))
            kind, has_data = ("IDAT" if i < first_idat else "fdAT"), False
        elif name == "fdAT":
            if kind != "fdAT":
                raise ValueError("対応する fcTL の無い fdAT があります")
            has_data = True
        elif name == "IDAT" and kind == "IDAT":
            has_data = True
    if not has_data:
        raise ValueError("最後の fcTL に画像データがありません")
    if len(delays) != num_frames:
        raise ValueError(f"acTL のフレーム数 {num_frames} と fcTL の数 {len(delays)} が違います")
    info.update({"frames": num_frames, "loops": num_plays,
                 "default_image_is_frame": "fcTL" in names[:first_idat],
                 "durations_s": delays, "total_s": round(sum(delays), 4)})
    return info
