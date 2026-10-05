"""コマンドライン。

  text     シーン（プリセット / JSON）から文字アニメを作る
  frames   既存の連番画像から APNG・シートを作る
  split    APNG を連番 PNG（とシート）へ分解する
  info     APNG を検査して要約を出す
  presets  プリセット一覧    effects  効果の一覧
"""

import argparse
import glob
import json
import math
import os
import sys

from . import apng_check, effects, encode, scene as scene_mod
from .render import Renderer, completed_frame

MAX_LOOP = 2 ** 31 - 1
MAX_DELAY_MS = 65535  # APNG の遅延は 16bit。Pillow は ms 単位（分母 1000）で書く

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRESET_DIR = os.path.join(SKILL_DIR, "presets")


def _preset_path(name):
    path = name if name.endswith(".json") and os.path.isfile(name) else os.path.join(PRESET_DIR, name + ".json")
    if not os.path.isfile(path):
        raise SystemExit(f"プリセットが見つかりません: {name}（`presets` で一覧を確認できます）")
    return path


def _out_paths(out):
    stem, ext = os.path.splitext(out)
    if ext.lower() not in (".png", ".apng"):
        stem, ext = out, ".png"
    return stem, ext


def _check_sheet_args(args):
    if args.columns is not None and args.columns < 1:
        raise ValueError("--columns は 1 以上にしてください")
    if args.spacing < 0:
        raise ValueError("--spacing は 0 以上にしてください")


def _apng_frames(path):
    """実際に APNG へ入ったフレーム数。同じ絵が続くと結合されるので、frames より少ないことがある。
    すべて同じ絵なら、アニメーションでない PNG になり 1 を返す。"""
    info = apng_check.inspect(path)
    return info["frames"] if info["animated"] else 1


def build_scene(args):
    data = {}
    if args.preset:
        data = scene_mod.load_json(_preset_path(args.preset))
    if args.scene:
        data = scene_mod.deep_merge(data, scene_mod.load_json(args.scene))
    if args.text is not None:
        data["text"] = args.text.replace("\\n", "\n")
    if args.sub is not None:
        data = scene_mod.deep_merge(data, {"sub": {"text": args.sub.replace("\\n", "\n")}})
    for item in args.set or []:
        key, _, value = item.partition("=")
        data = scene_mod.set_path(data, key.strip(), value)
    for key, val in (("fps", args.fps), ("loop", args.loop)):
        if val is not None:
            data = scene_mod.deep_merge(data, {"export": {key: val}})
    if args.palette:
        data = scene_mod.deep_merge(data, {"export": {"palette": True}})
    if args.no_trim:
        data = scene_mod.deep_merge(data, {"export": {"trim": False}})
    return scene_mod.build(data)


def cmd_text(args):
    _check_sheet_args(args)
    scene = build_scene(args)
    if args.dump_scene:
        print(json.dumps(scene, ensure_ascii=False, indent=2))
        return 0
    ex = scene["export"]
    fps = ex["fps"]
    r = Renderer(scene)
    times, durs = encode.frame_schedule(r.duration, fps)
    complete = completed_frame(scene) if (ex["poster"] or args.still) else None
    if ex["trim"]:
        # 描画面の大きさのまま全フレームを持つとメモリを食うので、1枚ずつ中身だけ切って持つ
        pieces = [encode.crop_to_content(r.frame(t)) for t in times]
        extra = [encode.crop_to_content(complete)] if complete is not None else []
        box = encode.pieces_bbox(pieces + extra, r.size, ex["trim_pad"])
        frames = encode.assemble(pieces, r.size, box)
        complete = complete.crop(box) if complete is not None else None
    else:
        box = (0, 0) + r.size
        frames = [r.frame(t) for t in times]
    stem, ext = _out_paths(args.output)
    os.makedirs(os.path.dirname(stem) or ".", exist_ok=True)
    tl = r.timeline
    result = {"canvas": list(r.size), "origin": list(box[:2]), "size": list(frames[0].size),
              "fps": fps, "frames": len(frames), "duration_s": round(r.duration, 3),
              "playback_s": round(sum(durs) / 1000, 3), "loop": ex["loop"],
              "segments_s": {k: [round(a, 3), round(b, 3)] for k, (a, b) in tl.segments().items()},
              "segments_frames": encode.segments_in_frames(tl.segments(), times),
              "hold_loopable": r.hold_loopable(fps)}
    shown = frames
    if args.still:
        complete.save(stem + ext, optimize=True)
        result["output"] = stem + ext
    else:
        poster = complete if ex["poster"] else None
        mode, shown = encode.save_apng(frames, stem + ext, durs, loop=ex["loop"], poster=poster,
                                       palette=ex["palette"])
        result.update({"output": stem + ext, "color": mode, "bytes": os.path.getsize(stem + ext),
                       "apng_frames": _apng_frames(stem + ext)})
    meta = {k: result[k] for k in ("canvas", "origin", "fps", "loop", "segments_frames", "hold_loopable")}
    if args.sheet:
        result["sheet_json"] = encode.save_sheet(frames, stem + "_sheet.png", durs, args.columns,
                                                 args.spacing, meta)
    if args.frames_dir:
        encode.save_sequence(frames, args.frames_dir, os.path.basename(stem))
        result["frames_dir"] = args.frames_dir
    if args.preview:  # 256色化したときは、減色後の絵を見せる
        result["preview"] = encode.contact_sheet(shown, times, stem + "_preview.png")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _timing_manifest(inputs):
    """split が書いたフォルダなら、*_timing.json に並ぶファイルと表示時間・ループ回数を使う。
    フォルダには _sheet.png も置かれるので、ファイルを数え上げると余計な1枚が混ざる。"""
    if len(inputs) != 1 or not os.path.isdir(inputs[0]):
        return None
    found = glob.glob(os.path.join(inputs[0], "*_timing.json"))
    if len(found) != 1:
        return None
    with open(found[0], encoding="utf-8") as f:
        timing = json.load(f)
    timing["paths"] = [os.path.join(inputs[0], n) for n in timing["files"]]
    return timing


def _frame_durations(args, count, manifest):
    if args.durations:
        durs = [int(x) for x in args.durations.split(",")]
        if len(durs) == 1:
            durs = durs * count
        if len(durs) != count:
            raise ValueError(f"--durations の数 {len(durs)} とフレーム数 {count} が違います")
    elif manifest and args.fps is None:
        durs = list(manifest["durations_ms"])
    else:
        fps = 12 if args.fps is None else args.fps
        if not math.isfinite(fps) or not 0 < fps <= 1000:
            raise ValueError("--fps は 0 より大きく 1000 以下にしてください")
        durs = encode.durations_ms(count, fps)
    if any(not 0 <= d <= MAX_DELAY_MS for d in durs):
        raise ValueError(f"表示時間は 0〜{MAX_DELAY_MS} ms にしてください")
    return durs


def cmd_frames(args):
    _check_sheet_args(args)
    if args.trim_pad < 0:
        raise ValueError("--trim-pad は 0 以上にしてください")
    manifest = _timing_manifest(args.inputs)
    paths = manifest["paths"] if manifest else encode.collect_inputs(args.inputs)
    loop = args.loop if args.loop is not None else (manifest or {}).get("loop", 0)
    if not 0 <= loop <= MAX_LOOP:
        raise ValueError("--loop は 0 以上にしてください（0 = 無限）")
    frames = encode.load_frames(paths, args.fit)
    durs = _frame_durations(args, len(frames), manifest)
    if args.pingpong and len(frames) > 2:
        frames = frames + frames[-2:0:-1]
        durs = durs + durs[-2:0:-1]
    box = (0, 0) + frames[0].size
    if args.trim:
        frames, box = encode.trim(frames, args.trim_pad)
    stem, ext = _out_paths(args.output)
    os.makedirs(os.path.dirname(stem) or ".", exist_ok=True)
    mode, shown = encode.save_apng(frames, stem + ext, durs, loop=loop, palette=args.palette)
    result = {"inputs": len(paths), "frames": len(frames), "apng_frames": _apng_frames(stem + ext),
              "size": list(frames[0].size), "origin": list(box[:2]), "output": stem + ext,
              "color": mode, "bytes": os.path.getsize(stem + ext), "loop": loop}
    if args.sheet:
        result["sheet_json"] = encode.save_sheet(frames, stem + "_sheet.png", durs, args.columns,
                                                 args.spacing, {"loop": loop, "origin": list(box[:2])})
    if args.preview:
        times = [sum(durs[:i]) / 1000 for i in range(len(frames))]
        result["preview"] = encode.contact_sheet(shown, times, stem + "_preview.png")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_split(args):
    _check_sheet_args(args)
    frames, durs, loop = encode.split_apng(args.input)
    stem = os.path.splitext(os.path.basename(args.input))[0]
    out_dir = args.out_dir or os.path.join(os.path.dirname(args.input) or ".", stem + "_frames")
    paths = encode.save_sequence(frames, out_dir, stem)
    with open(os.path.join(out_dir, stem + "_timing.json"), "w", encoding="utf-8") as f:
        json.dump({"loop": loop, "durations_ms": durs, "files": [os.path.basename(p) for p in paths]},
                  f, ensure_ascii=False, indent=2)
    result = {"frames": len(frames), "out_dir": out_dir, "loop": loop}
    if args.sheet:
        result["sheet_json"] = encode.save_sheet(frames, os.path.join(out_dir, stem + "_sheet.png"),
                                                 durs, args.columns, args.spacing, {"loop": loop})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_info(args):
    info = apng_check.inspect(args.input)
    if "durations_s" in info and not args.verbose:
        info["durations_s"] = f"{len(info['durations_s'])} 件（--verbose で全件）"
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


def cmd_presets(args):
    for name in sorted(os.listdir(PRESET_DIR)):
        if name.endswith(".json"):
            data = scene_mod.load_json(os.path.join(PRESET_DIR, name))
            print(f"{name[:-5]:<18} {data.get('_description', '')}")
    return 0


def cmd_effects(args):
    print("in   :", ", ".join(effects.IN_FX))
    print("hold :", ", ".join(effects.HOLD_FX))
    print("out  :", ", ".join(effects.OUT_FX))
    print("deco :", ", ".join(scene_mod.CHOICES["deco.type"]))
    print("order:", ", ".join(scene_mod.CHOICES["anim.in.order"]))
    return 0


def _add_sheet_opts(p):
    p.add_argument("--sheet", action="store_true", help="スプライトシート（_sheet.png と .json）も書く")
    p.add_argument("--columns", type=int, default=None, help="シートの列数（既定は正方形に近く）")
    p.add_argument("--spacing", type=int, default=0, help="シートのフレーム間の隙間 px")


def parser():
    ap = argparse.ArgumentParser(prog="apngmk", description="APNG をローカルで作る")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("text", help="文字アニメを作る")
    p.add_argument("--preset", help="プリセット名（presets/ 内）")
    p.add_argument("--scene", help="シーン JSON（プリセットに重ねる）")
    p.add_argument("--text", help="本文（\\n で改行）")
    p.add_argument("--sub", help="サブテキスト")
    p.add_argument("--set", action="append", metavar="KEY=VALUE",
                   help="設定を上書き（例 anim.in.fx=pop、style.fill.color=\"#ff0\"）")
    p.add_argument("--fps", type=int)
    p.add_argument("--loop", type=int, help="0 = 無限、n = n 回")
    p.add_argument("--palette", action="store_true", help="256色に減色して軽くする")
    p.add_argument("--no-trim", action="store_true", help="透明な余白を切り落とさない")
    p.add_argument("--still", action="store_true", help="完成状態の PNG 静止画だけを書く")
    p.add_argument("--frames-dir", help="連番 PNG も書くディレクトリ")
    p.add_argument("--preview", action="store_true", help="確認用の一覧画像 _preview.png も書く")
    p.add_argument("--dump-scene", action="store_true", help="既定値を補ったシーンを表示して終わる")
    p.add_argument("-o", "--output", default="output/text.png")
    _add_sheet_opts(p)
    p.set_defaults(func=cmd_text)

    p = sub.add_parser("frames", help="連番画像から APNG を作る")
    p.add_argument("inputs", nargs="+", help="ファイル・ディレクトリ・ワイルドカード")
    p.add_argument("-o", "--output", default="output/frames.png")
    p.add_argument("--fps", type=float, default=None, help="既定 12（split のフォルダなら元の表示時間）")
    p.add_argument("--durations", help="ms をカンマ区切り（1つならすべて同じ）")
    p.add_argument("--loop", type=int, default=None, help="0 = 無限（既定）、n = n 回")
    p.add_argument("--pingpong", action="store_true", help="往復再生（1-2-3-2-1…）にする")
    p.add_argument("--fit", choices=("pad", "error"), default="pad")
    p.add_argument("--trim", action="store_true")
    p.add_argument("--trim-pad", type=int, default=0)
    p.add_argument("--palette", action="store_true")
    p.add_argument("--preview", action="store_true")
    _add_sheet_opts(p)
    p.set_defaults(func=cmd_frames)

    p = sub.add_parser("split", help="APNG を連番 PNG に分解する")
    p.add_argument("input")
    p.add_argument("--out-dir")
    _add_sheet_opts(p)
    p.set_defaults(func=cmd_split)

    p = sub.add_parser("info", help="APNG を検査する")
    p.add_argument("input")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_info)

    sub.add_parser("presets", help="プリセット一覧").set_defaults(func=cmd_presets)
    sub.add_parser("effects", help="効果の一覧").set_defaults(func=cmd_effects)
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (scene_mod.SceneError, ValueError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
