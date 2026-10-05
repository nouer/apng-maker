"""apng_maker の検証。実行: python3 -m unittest discover -s tests -v（スキルのフォルダで）"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from PIL import Image, ImageChops  # noqa: E402

from apng_maker import apng_check, cli, encode, scene as scene_mod, timeline  # noqa: E402
from apng_maker.render import Renderer  # noqa: E402
from apng_maker.util import graphemes  # noqa: E402

SMALL = {"text": "テスト", "canvas": {"width": 320, "height": 160},
         "font": {"size": 48}, "export": {"fps": 12}}


def small(**over):
    return scene_mod.build(scene_mod.deep_merge(SMALL, over))


def same(a, b):
    """RGB も含めて完全一致か。getbbox() は既定で alpha しか見ないので使わない。"""
    return a.mode == b.mode and a.size == b.size and a.tobytes() == b.tobytes()


class TestScene(unittest.TestCase):
    def test_unknown_effect_is_rejected_with_choices(self):
        with self.assertRaises(scene_mod.SceneError) as cm:
            small(anim={"in": {"fx": "explode"}})
        self.assertIn("anim.in.fx", str(cm.exception))
        self.assertIn("fade", str(cm.exception))

    def test_set_path_parses_json_values(self):
        s = scene_mod.set_path({}, "anim.hold.dur", "2.5")
        self.assertEqual(s["anim"]["hold"]["dur"], 2.5)
        s = scene_mod.set_path(s, "style.fill.color", "#ff0000")
        self.assertEqual(s["style"]["fill"]["color"], "#ff0000")

    def test_deep_merge_does_not_mutate(self):
        base = {"a": {"b": 1}}
        scene_mod.deep_merge(base, {"a": {"c": 2}})
        self.assertEqual(base, {"a": {"b": 1}})

    def test_all_presets_are_valid_and_render(self):
        for name in os.listdir(cli.PRESET_DIR):
            with self.subTest(preset=name):
                sc = scene_mod.build(scene_mod.load_json(os.path.join(cli.PRESET_DIR, name)))
                r = Renderer(sc)
                img = r.frame(r.timeline.in_end)
                self.assertIsNotNone(img.getchannel("A").getbbox(), "完成状態が空です")


class TestText(unittest.TestCase):
    def test_graphemes_keep_combined_characters(self):
        self.assertEqual(graphemes("が👍🏻a"), ["が", "👍🏻", "a"])

    def test_center_order_is_symmetric(self):
        self.assertEqual(timeline.ranks(5, "center", 1), [2, 1, 0, 1, 2])
        self.assertEqual(timeline.ranks(4, "edges", 1), [0, 1, 1, 0])

    def test_segments_follow_hold_duration(self):
        r = Renderer(small(anim={"hold": {"dur": 1.5}}))
        seg = r.timeline.segments()
        self.assertAlmostEqual(seg["hold"][1] - seg["hold"][0], 1.5)
        self.assertLessEqual(seg["out"][1], r.duration)

    def test_same_time_gives_same_image(self):
        sc = small(anim={"in": {"fx": "scatter"}, "hold": {"fx": "shake"}, "out": {"fx": "glitch"}})
        a, b = Renderer(sc), Renderer(sc)
        for t in (0.1, 0.4, 0.9, a.duration - 0.1):
            self.assertTrue(same(a.frame(t), b.frame(t)), f"t={t}")

    def test_before_start_is_empty_and_hold_is_full(self):
        r = Renderer(small(anim={"start_delay": 0.3}))
        self.assertIsNone(r.frame(0.0).getchannel("A").getbbox())
        self.assertIsNotNone(r.frame(r.timeline.in_end).getchannel("A").getbbox())

    def test_every_effect_renders(self):
        from apng_maker import effects
        for phase, table in (("in", effects.IN_FX), ("hold", effects.HOLD_FX), ("out", effects.OUT_FX)):
            for fx in table:
                with self.subTest(phase=phase, fx=fx):
                    r = Renderer(small(anim={phase: {"fx": fx}}))
                    for k in range(6):
                        r.frame(r.duration * k / 5)

    def test_vertical_layout_runs_top_to_bottom(self):
        r = Renderer(small(writing="vertical", text="縦書き", canvas={"width": 160, "height": 320}))
        ys = [g.cy for g in r.layout.glyphs]
        self.assertEqual(ys, sorted(ys))

    def test_vertical_anchor_top_is_right_side(self):
        base = dict(writing="vertical", text="縦", canvas={"width": 200, "height": 120}, font={"size": 40})
        top = Renderer(small(**base, layout={"anchor": "top", "margin": 10})).layout.glyphs[0].cx
        bottom = Renderer(small(**base, layout={"anchor": "bottom", "margin": 10})).layout.glyphs[0].cx
        self.assertGreater(top, 100)
        self.assertLess(bottom, 100)

    def test_auto_fit_shrinks_long_text(self):
        r = Renderer(small(text="とても長い文章がここに入ります"))
        x0, _, x1, _ = r.layout.box
        self.assertLessEqual(x1 - x0, 320)
        self.assertLess(r.layout.size, 48)


class TestEncode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _frames(self, n=4, dup=False):
        out = []
        for i in range(n):
            im = Image.new("RGBA", (40, 30), (0, 0, 0, 0))
            k = 0 if dup else i
            im.paste((255, 40 * k, 0, 200), (5 + k * 3, 5, 15 + k * 3, 15))
            out.append(im)
        return out

    def test_apng_structure_loops_and_poster(self):
        frames = self._frames()
        poster = frames[-1]
        path = os.path.join(self.dir, "a.png")
        encode.save_apng(frames, path, [100] * 4, loop=3, poster=poster)
        info = apng_check.inspect(path)
        self.assertTrue(info["animated"])
        self.assertEqual(info["frames"], 4)
        self.assertEqual(info["loops"], 3)
        self.assertFalse(info["default_image_is_frame"])
        self.assertAlmostEqual(info["total_s"], 0.4, places=3)

    def test_identical_frames_are_merged(self):
        path = os.path.join(self.dir, "d.png")
        encode.save_apng(self._frames(dup=True) + self._frames(2)[1:], path, [100] * 5)
        info = apng_check.inspect(path)
        self.assertLess(info["frames"], 5)
        self.assertAlmostEqual(info["total_s"], 0.5, places=3)

    def test_palette_keeps_transparency(self):
        path = os.path.join(self.dir, "p.png")
        frames = self._frames()
        mode, _ = encode.save_apng(frames, path, [100] * 4, palette=True)
        self.assertEqual(mode, "P")
        self.assertEqual(apng_check.inspect(path)["color_type"], "palette")
        back, _, _ = encode.split_apng(path)
        self.assertEqual(back[2].getpixel((0, 0))[3], 0)
        self.assertEqual(back[2].getpixel((12, 8)), frames[2].getpixel((12, 8)))

    def test_split_round_trip(self):
        frames = self._frames()
        path = os.path.join(self.dir, "r.png")
        encode.save_apng(frames, path, [80, 90, 100, 110], loop=0)
        back, durs, loop = encode.split_apng(path)
        self.assertEqual(durs, [80, 90, 100, 110])
        self.assertEqual(loop, 0)
        for a, b in zip(frames, back):
            self.assertTrue(same(a, b))

    def test_split_skips_poster_that_is_not_a_frame(self):
        frames = self._frames()
        path = os.path.join(self.dir, "poster.png")
        encode.save_apng(frames, path, [80, 90, 100, 110], poster=frames[-1])
        back, durs, _ = encode.split_apng(path)
        self.assertEqual(durs, [80, 90, 100, 110])
        self.assertTrue(same(back[0], frames[0]))

    def test_trim_is_common_to_all_frames(self):
        trimmed, box = encode.trim(self._frames(), pad=1)
        self.assertEqual(box, (4, 4, 25, 16))
        self.assertTrue(all(f.size == trimmed[0].size for f in trimmed))

    def test_durations_do_not_drift(self):
        d = encode.durations_ms(30, 30)
        self.assertEqual(sum(d), 1000)
        self.assertLessEqual(max(d) - min(d), 1)

    def test_sheet_json(self):
        path = os.path.join(self.dir, "s.png")
        jp = encode.save_sheet(self._frames(5), path, [100] * 5, columns=2, spacing=2)
        with open(jp, encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual((meta["columns"], meta["rows"], meta["count"]), (2, 3, 5))
        self.assertEqual(meta["frames"][3]["x"], 42)
        with Image.open(path) as im:
            self.assertEqual(im.size, (82, 94))


class TestCli(unittest.TestCase):
    def test_text_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "t.png")
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.main(["text", "--preset", "level_up", "--text", "GO", "--fps", "10",
                                 "--set", "anim.hold.dur=1.0", "--palette", "--sheet", "--preview",
                                 "-o", out])
            self.assertEqual(code, 0)
            res = json.loads(buf.getvalue())
            info = apng_check.inspect(out)
            self.assertEqual(info["loops"], 0)
            self.assertTrue(res["hold_loopable"])
            self.assertTrue(os.path.isfile(res["sheet_json"]))
            self.assertTrue(os.path.isfile(res["preview"]))
            seg = res["segments_frames"]
            self.assertEqual(seg["hold"][1] - seg["hold"][0], 10)
            self.assertEqual(seg["in"][0], 0)
            self.assertEqual(seg["in"][1], seg["hold"][0])
            self.assertEqual(seg["hold"][1], seg["out"][0])
            self.assertEqual(seg["out"][1], res["frames"])
            self.assertEqual(res["apng_frames"], info["frames"])
            with open(res["sheet_json"], encoding="utf-8") as f:
                self.assertEqual(json.load(f)["count"], res["frames"])

    def test_frames_from_directory(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(3):
                Image.new("RGBA", (20, 20), (i * 80, 0, 0, 255)).save(os.path.join(d, f"f{i}.png"))
            out = os.path.join(d, "o.png")
            with redirect_stdout(io.StringIO()):
                code = cli.main(["frames", d, "--fps", "8", "--pingpong", "-o", out])
            self.assertEqual(code, 0)
            self.assertEqual(apng_check.inspect(out)["frames"], 4)

    def test_bad_scene_returns_error_code(self):
        with tempfile.TemporaryDirectory() as d:
            code = cli.main(["text", "--set", "anim.in.fx=nope", "-o", os.path.join(d, "x.png")])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
