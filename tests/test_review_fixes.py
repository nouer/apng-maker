"""codex レビュー（2026-10-05）の指摘ごとの回帰テスト。番号はレビューの指摘番号。"""

import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from PIL import Image  # noqa: E402

from apng_maker import apng_check, cli, encode, scene as scene_mod  # noqa: E402
from apng_maker.render import Renderer  # noqa: E402

SMALL = {"text": "A", "canvas": {"width": 200, "height": 120}, "font": {"size": 48},
         "export": {"fps": 30}}


def small(**over):
    return scene_mod.build(scene_mod.deep_merge(SMALL, over))


def same(a, b):
    return a.mode == b.mode and a.size == b.size and a.tobytes() == b.tobytes()


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, (json.loads(out.getvalue()) if code == 0 and out.getvalue().strip() else None)


def chunks(data):
    pos, out = 8, []
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        out.append([ctype, bytearray(data[pos + 8:pos + 8 + length])])
        pos += 12 + length
    return out


def build_png(chs):
    out = bytearray(apng_check.SIGNATURE)
    for ctype, body in chs:
        out += struct.pack(">I", len(body)) + ctype + bytes(body)
        out += struct.pack(">I", zlib.crc32(ctype + bytes(body)) & 0xFFFFFFFF)
    return bytes(out)


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def two_frame_apng(self):
        frames = [Image.new("RGBA", (8, 8), c) for c in ("red", "blue")]
        path = os.path.join(self.dir, "two.png")
        encode.save_apng(frames, path, [100, 100])
        with open(path, "rb") as f:
            return f.read()


class Test01FrameSchedule(unittest.TestCase):
    def test_low_fps_still_samples_the_hold(self):
        r = Renderer(small(export={"fps": 1}))
        times, durs = encode.frame_schedule(r.duration, 1)
        self.assertIn(1.0, times)
        self.assertTrue(any(r.frame(t).getchannel("A").getbbox() for t in times))

    def test_no_sample_is_skipped_and_durations_follow_times(self):
        times, durs = encode.frame_schedule(1.65, 30)
        self.assertEqual(times[:-1], [k / 30 for k in range(50)])
        self.assertEqual(times[-1], 1.65)
        self.assertEqual(len(durs), len(times))
        self.assertTrue(all(d >= 0 for d in durs))
        self.assertEqual(sum(durs[:-1]), round(1.65 * 1000))

    def test_reported_playback_matches_apng(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "a.png")
            code, res = run_cli(["text", "--text", "AB", "--fps", "7", "-o", out])
            self.assertEqual(code, 0)
            self.assertAlmostEqual(res["playback_s"], apng_check.inspect(out)["total_s"], places=3)


class Test02HoldLoop(unittest.TestCase):
    def test_hold_repeats_after_one_period_from_its_start(self):
        r = Renderer(small(anim={"hold": {"fx": "pulse", "dur": 2.0, "period": 1.0}, "out": {"fx": "none"}}))
        t = r.timeline.in_end + 0.01
        self.assertTrue(same(r.frame(t), r.frame(t + 1.0)))

    def test_loopable_flag_is_strict(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "a.png")
            base = ["text", "--text", "A", "--set", "anim.hold.fx=wave", "--set", "anim.hold.period=1",
                    "-o", out]
            self.assertTrue(run_cli(base + ["--set", "anim.hold.dur=2"])[1]["hold_loopable"])
            self.assertFalse(run_cli(base + ["--set", "anim.hold.dur=0"])[1]["hold_loopable"])
            shake = ["--set", "anim.hold.dur=2", "--set", 'anim.camera_shake={"at":"in_end","dur":0.3}']
            self.assertFalse(run_cli(base + shake)[1]["hold_loopable"])
            # 1.01 秒は 30fps で 30.3 フレーム。hold の枚数が整数にならず、継ぎ目でずれる
            odd = ["--set", "anim.hold.dur=1.01", "--set", "anim.hold.period=1.01"]
            self.assertFalse(run_cli(base[:-2] + odd + ["-o", out])[1]["hold_loopable"])


class Test03Segments(unittest.TestCase):
    def test_every_frame_time_lies_in_its_segment(self):
        sc = small(anim={"in": {"dur": 0.35}})
        r = Renderer(sc)
        times, _ = encode.frame_schedule(r.duration, 30)
        segs = encode.segments_in_frames(r.timeline.segments(), times)
        for name, (a, b) in segs.items():
            lo, hi = r.timeline.segments()[name]
            for i in range(a, b):
                self.assertGreaterEqual(times[i] + 1e-9, lo, (name, i))
                if name != "out":
                    self.assertLess(times[i], hi, (name, i))
        self.assertEqual(segs["out"][1], len(times))


class Test04CompletedStill(Tmp):
    def test_still_is_not_empty_with_zero_hold_and_instant_exit(self):
        out = os.path.join(self.dir, "s.png")
        code, _ = run_cli(["text", "--text", "A", "--set", "anim.hold.dur=0",
                           "--set", "anim.out.fx=erase", "--still", "-o", out])
        self.assertEqual(code, 0)
        with Image.open(out) as im:
            self.assertIsNotNone(im.convert("RGBA").getchannel("A").getbbox())


class Test05AutoFit(unittest.TestCase):
    def test_many_lines_fit_vertically(self):
        r = Renderer(small(text="A\nB\nC\nD", canvas={"width": 320, "height": 160}))
        _, y0, _, y1 = r.layout.box
        self.assertGreaterEqual(y0, 0)
        self.assertLessEqual(y1, 160)

    def test_many_columns_fit_horizontally_in_vertical_writing(self):
        r = Renderer(small(text="一\n二\n三\n四\n五", writing="vertical",
                           canvas={"width": 160, "height": 320}))
        x0, _, x1, _ = r.layout.box
        self.assertGreaterEqual(x0, 0)
        self.assertLessEqual(x1, 160)


class Test06ApngCheck(Tmp):
    def mutate(self, fn):
        chs = chunks(self.two_frame_apng())
        fn(chs)
        path = os.path.join(self.dir, "bad.png")
        with open(path, "wb") as f:
            f.write(build_png(chs))
        return path

    def fctl(self, chs, k=0):
        return [c for c in chs if c[0] == b"fcTL"][k][1]

    def test_rejects_invalid_dispose_and_blend(self):
        for offset in (24, 25):
            path = self.mutate(lambda chs: self.fctl(chs).__setitem__(offset, 255))
            with self.assertRaises(ValueError):
                apng_check.inspect(path)

    def test_rejects_zero_width_frame(self):
        path = self.mutate(lambda chs: self.fctl(chs, 1).__setitem__(slice(4, 8), b"\0\0\0\0"))
        with self.assertRaises(ValueError):
            apng_check.inspect(path)

    def test_rejects_missing_frame_data(self):
        def drop_last_fdat(chs):
            idx = max(i for i, c in enumerate(chs) if c[0] == b"fdAT")
            del chs[idx]
        with self.assertRaises(ValueError):
            apng_check.inspect(self.mutate(drop_last_fdat))

    def test_rejects_actl_after_idat(self):
        def move(chs):
            i = next(i for i, c in enumerate(chs) if c[0] == b"acTL")
            actl = chs.pop(i)
            chs.insert(len(chs) - 1, actl)
        with self.assertRaises(ValueError):
            apng_check.inspect(self.mutate(move))

    def test_truncated_file_is_value_error(self):
        data = self.two_frame_apng()
        for cut in (8, len(data) - 1):
            path = os.path.join(self.dir, f"cut{cut}.png")
            with open(path, "wb") as f:
                f.write(data[:cut])
            with self.assertRaises(ValueError):
                apng_check.inspect(path)

    def test_valid_file_still_passes(self):
        path = os.path.join(self.dir, "ok.png")
        with open(path, "wb") as f:
            f.write(self.two_frame_apng())
        self.assertEqual(apng_check.inspect(path)["frames"], 2)


class Test08SplitTiming(Tmp):
    def test_cumulative_rounding_keeps_total(self):
        frames = [Image.new("RGBA", (4, 4), (k * 2, 0, 0, 255)) for k in range(120)]
        path = os.path.join(self.dir, "f.png")
        encode.save_apng(frames, path, [8] * 120)
        chs = chunks(open(path, "rb").read())
        for c in chs:
            if c[0] == b"fcTL":
                c[1][20:24] = struct.pack(">HH", 1, 120)
        with open(path, "wb") as f:
            f.write(build_png(chs))
        _, durs, _ = encode.split_apng(path)
        self.assertEqual(sum(durs), 1000)


class Test09FramesFromSplitDir(Tmp):
    def test_split_dir_with_sheet_round_trips(self):
        frames = [Image.new("RGBA", (6, 6), c) for c in ("red", "green", "blue")]
        src = os.path.join(self.dir, "w.png")
        encode.save_apng(frames, src, [50, 60, 70], loop=2)
        code, res = run_cli(["split", src, "--sheet"])
        self.assertEqual(code, 0)
        out = os.path.join(self.dir, "re.png")
        code, res = run_cli(["frames", res["out_dir"], "-o", out])
        self.assertEqual(code, 0)
        self.assertEqual(res["frames"], 3)
        info = apng_check.inspect(out)
        self.assertEqual((info["width"], info["loops"]), (6, 2))
        self.assertAlmostEqual(info["total_s"], 0.18, places=3)


class Test10InputValidation(Tmp):
    def setUp(self):
        super().setUp()
        for i, c in enumerate(("red", "blue")):
            Image.new("RGBA", (4, 4), c).save(os.path.join(self.dir, f"f{i}.png"))

    def test_bad_numbers_are_rejected(self):
        out = os.path.join(self.dir, "o.png")
        for extra in (["--fps", "0"], ["--fps", "-1"], ["--loop", "-1"], ["--durations=-1,100"],
                      ["--sheet", "--columns", "0"], ["--sheet", "--spacing", "-1"]):
            with self.subTest(extra=extra):
                code, _ = run_cli(["frames", self.dir + "/f*.png", "-o", out] + extra)
                self.assertEqual(code, 2)

    def test_text_loop_must_be_non_negative(self):
        code, _ = run_cli(["text", "--text", "A", "--loop", "-1", "-o", os.path.join(self.dir, "t.png")])
        self.assertEqual(code, 2)

    def test_zero_delay_is_allowed(self):
        code, _ = run_cli(["frames", self.dir + "/f*.png", "--durations", "0,100",
                           "-o", os.path.join(self.dir, "z.png")])
        self.assertEqual(code, 0)


class Test11PalettePreview(Tmp):
    def test_preview_frames_are_what_was_written(self):
        frames = [Image.linear_gradient("L").convert("RGBA").resize((64, 64)) for _ in range(2)]
        frames[1] = frames[1].rotate(90)
        path = os.path.join(self.dir, "p.png")
        mode, written = encode.save_apng(frames, path, [100, 100], palette=True)
        self.assertEqual(mode, "P")
        back, _, _ = encode.split_apng(path)
        for a, b in zip(written, back):
            self.assertTrue(same(a, b))


if __name__ == "__main__":
    unittest.main()
