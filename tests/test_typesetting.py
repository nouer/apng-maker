"""文字組みの検証：ルビ、カーニングと日本語の詰め、縦書き用字形、縦中横、大きなアニメの256色化。"""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

from PIL import Image, ImageDraw  # noqa: E402

from apng_maker import apng_check, encode, palette, ruby, scene as scene_mod  # noqa: E402
from apng_maker.layout import compute  # noqa: E402
from apng_maker.render import Renderer  # noqa: E402
from apng_maker.sprites import build  # noqa: E402
from apng_maker.textshape import HAS_RAQM  # noqa: E402

BASE = {"canvas": {"width": 800, "height": 400}, "font": {"size": 60}, "layout": {"auto_fit": False},
        "export": {"fps": 12}}


def scene(**over):
    return scene_mod.build(scene_mod.deep_merge(BASE, over))


def width_of(text, **font):
    lay = compute(scene(text=text, font=font))
    g = [x for x in lay.glyphs if not x.aux]
    return (g[-1].cx + g[-1].adv / 2) - (g[0].cx - g[0].adv / 2)


class TestRubyParse(unittest.TestCase):
    def test_implicit_base_is_preceding_kanji_run(self):
        tokens, rubies = ruby.parse("あの魔王《まおう》だ")
        self.assertEqual(rubies, ["まおう"])
        self.assertEqual([c for c, r in tokens if r == 0], ["魔", "王"])
        self.assertEqual("".join(c for c, _ in tokens), "あの魔王だ")

    def test_explicit_base(self):
        tokens, rubies = ruby.parse("｜古の剣《いにしえのつるぎ》を")
        self.assertEqual([c for c, r in tokens if r == 0], ["古", "の", "剣"])
        self.assertEqual(rubies, ["いにしえのつるぎ"])

    def test_without_kanji_or_closing_mark_is_literal(self):
        self.assertEqual(ruby.strip("かな《ルビ》"), "かな《ルビ》")
        self.assertEqual(ruby.strip("漢字《ひらき"), "漢字《ひらき")
        self.assertEqual(ruby.strip("｜だけ"), "｜だけ")
        self.assertEqual(ruby.strip("漢字《》"), "漢字《》")

    def test_does_not_cross_lines(self):
        self.assertEqual(ruby.strip("漢字《かん\nじ》"), "漢字《かん\nじ》")


class TestRubyLayout(unittest.TestCase):
    def test_ruby_sits_above_base_and_moves_with_it(self):
        sc = scene(text="魔王《まおう》来る")
        r = Renderer(sc)
        rub = [g for g in r.layout.glyphs if g.aux]
        base = [g for g in r.layout.glyphs if g.ch in "魔王"]
        self.assertEqual("".join(g.ch for g in rub), "まおう")
        self.assertTrue(all(g.cy < base[0].cy for g in rub))
        mid = (base[0].cx + base[1].cx) / 2
        self.assertAlmostEqual(sum(g.cx for g in rub) / 3, mid, delta=1)
        for g in rub:
            self.assertEqual(r.timeline.in_start[g.index], r.timeline.in_start[base[0].index])

    def test_vertical_ruby_is_on_the_right(self):
        lay = compute(scene(text="魔王《まおう》", writing="vertical", canvas={"width": 300, "height": 600}))
        rub = [g for g in lay.glyphs if g.aux]
        base = [g for g in lay.glyphs if not g.aux]
        self.assertTrue(all(g.cx > base[0].cx for g in rub))

    def test_wrap_never_splits_a_ruby_base(self):
        lay = compute(scene(text="あいう魔王軍団《まおうぐんだん》", layout={"wrap_width": 280, "auto_fit": False}))
        base_rows = {round(g.cy) for g in lay.glyphs if g.ch in "魔王軍団"}
        self.assertEqual(len(base_rows), 1)

    def test_ruby_does_not_overlap_previous_line(self):
        lay = compute(scene(text="魔王《まおう》\n魔王《まおう》", font={"size": 60, "line_height": 1.1}))
        bases = [g for g in lay.glyphs if not g.aux]
        first_bottom = max(g.cy + g.size / 2 for g in bases[:2])
        second_ruby_top = min(g.cy - g.size / 2 for g in lay.glyphs if g.aux and g.base is bases[2])
        self.assertGreaterEqual(second_ruby_top, first_bottom - 0.5)

    def test_ruby_band_is_counted_by_auto_fit(self):
        lay = compute(scene(text="魔王《まおう》\n魔王《まおう》\n魔王《まおう》",
                            canvas={"width": 800, "height": 300}, layout={"auto_fit": True}))
        self.assertGreaterEqual(lay.box[1], 0)
        self.assertLessEqual(lay.box[3], 300)


@unittest.skipUnless(HAS_RAQM, "raqm が無い環境では字形の差し替えができない")
class TestShaping(unittest.TestCase):
    def test_kerning_tightens_pairs(self):
        self.assertLess(width_of("AVATAR", kerning=True), width_of("AVATAR", kerning=False))

    def test_palt_tightens_japanese(self):
        self.assertLess(width_of("「ジャンプ。」", palt=True), width_of("「ジャンプ。」", palt=False) * 0.9)

    def test_vertical_uses_vert_glyphs_tcy_and_sideways(self):
        lay = compute(scene(text="第12話HP、", writing="vertical", canvas={"width": 300, "height": 800}))
        kinds = [(g.ch, g.kind) for g in lay.glyphs]
        self.assertIn(("12", "tcy"), kinds)
        self.assertIn(("H", "side"), kinds)
        self.assertIn(("、", "v"), kinds)

    def test_vertical_comma_is_drawn_upper_right(self):
        lay = compute(scene(text="、", writing="vertical", canvas={"width": 300, "height": 300}))
        sp = build(lay.glyphs[0], scene(text="、", writing="vertical", style={"strokes": []}))
        x0, y0, x1, y1 = sp.body.getchannel("A").getbbox()
        w, h = sp.body.size
        self.assertGreater((x0 + x1) / 2, w / 2)
        self.assertLess((y0 + y1) / 2, h / 2)


class TestLargePalette(unittest.TestCase):
    def frames(self):
        out = []
        for k in range(6):
            im = Image.new("RGBA", (120, 80), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            for x in range(100):
                d.line((10 + x, 10, 10 + x, 60), fill=(255, 2 * x + k * 5, 40, 255))
            d.ellipse((20 + k * 5, 20, 60 + k * 5, 70), fill=(30, 200, 255, 128))
            out.append(im)
        return out

    def test_shared_palette_without_strip(self):
        frames = self.frames()
        q = encode.quantize_shared(frames, limit=0)        # 上限 0 で必ず見本方式に入る
        self.assertTrue(all(f.mode == "P" for f in q))
        self.assertTrue(all(f.getpalette(rawmode="RGBA") == q[0].getpalette(rawmode="RGBA") for f in q))
        for a, b in zip(frames, q):
            b = b.convert("RGBA")
            self.assertEqual(b.getpixel((2, 2))[3], 0)          # 透明は透明のまま
            ra, rb = a.getpixel((50, 30)), b.getpixel((50, 30))
            self.assertLess(max(abs(x - y) for x, y in zip(ra, rb)), 24)
            ea, eb = a.getpixel((40, 45)), b.getpixel((40, 45))  # 半透明の円
            self.assertLess(abs(ea[3] - eb[3]), 20)

    def test_saved_apng_is_valid(self):
        frames = self.frames()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "big.png")
            images = palette.quantize(frames)
            images[0].save(path, save_all=True, append_images=images[1:], duration=100, loop=0)
            info = apng_check.inspect(path)
            self.assertEqual((info["frames"], info["color_type"]), (6, "palette"))


if __name__ == "__main__":
    unittest.main()


class TestCodexRound2(unittest.TestCase):
    """codex レビュー2回目（2026-10-05）の指摘ごとの回帰テスト。番号は指摘番号。"""

    def test_01_alpha_level_missing_from_sample_is_kept(self):
        frames = [Image.new("RGBA", (1, 1), (255, 0, 0, a)) for a in (0, 255, 0)]
        p = palette.SharedPalette(frames, sample_pixels=2)
        self.assertEqual(p.apply(frames[1]).convert("RGBA").getpixel((0, 0)), (255, 0, 0, 255))
        frames = [Image.new("RGBA", (1, 1), (255, 0, 0, a)) for a in (255, 17, 255)]
        p = palette.SharedPalette(frames, sample_pixels=2)
        self.assertLess(abs(p.apply(frames[1]).convert("RGBA").getpixel((0, 0))[3] - 17), 10)

    def test_02_long_ruby_is_fitted_and_stays_on_canvas(self):
        for writing in ("horizontal", "vertical"):
            with self.subTest(writing=writing):
                lay = compute(scene(text="漢《かんじのながいよみかたです》", writing=writing,
                                    canvas={"width": 300, "height": 300}, font={"size": 120},
                                    layout={"auto_fit": True, "margin": 0}))
                x0, y0, x1, y1 = lay.box
                self.assertGreaterEqual(min(x0, y0), -1)
                self.assertLessEqual(max(x1, y1), 301)

    @unittest.skipUnless(HAS_RAQM, "raqm が無い環境ではカーニングしない")
    def test_03_kerned_glyph_is_where_the_pair_puts_it(self):
        from apng_maker import fonts
        lay = compute(scene(text="To", font={"size": 120, "letter_spacing": 0, "palt": True}))
        t, o = lay.glyphs
        font = fonts.load("gothic", "black", 120)
        feats = list(t.feats)
        expected_o_start = font.getlength("To", features=feats) - font.getlength("o", features=feats)
        self.assertAlmostEqual((o.cx - o.adv / 2) - (t.cx - t.adv / 2), expected_o_start, delta=0.5)

    def test_04_ruby_does_not_change_order_timing(self):
        def starts(text):
            r = Renderer(scene(text=text, anim={"in": {"fx": "typewriter", "order": "random"}}))
            return [round(r.timeline.in_start[g.index], 3) for g in r.layout.glyphs if not g.aux]
        self.assertEqual(starts("魔王来る"), starts("魔王《まおう》来る"))

    def test_05_ruby_moves_with_its_base(self):
        r = Renderer(scene(text="魔王《まおう》", anim={"in": {"fx": "slide", "dur": 1.0}}))
        base = next(g for g in r.layout.glyphs if g.ch == "魔")
        rub = next(g for g in r.layout.glyphs if g.aux)
        self.assertAlmostEqual(r.glyph_state(rub, 0.2)["dx"], r.glyph_state(base, 0.2)["dx"])

    def test_06_failed_explicit_ruby_keeps_bar(self):
        self.assertEqual(ruby.strip("｜《かん》"), "｜《かん》")
        self.assertEqual(ruby.strip("｜漢《》"), "｜漢《》")
        tokens, rubies = ruby.parse("｜《》漢《かん》")
        self.assertEqual([c for c, r in tokens if r == 0], ["漢"])

    def test_07_blank_base_or_reading_is_not_ruby(self):
        self.assertEqual(ruby.parse("｜ 《 》")[1], [])
        Renderer(scene(text="｜ 《 》"))  # 例外にならない

    def test_08_long_text_scales_linearly(self):
        import time
        def cost(n):
            t = time.perf_counter()
            compute(scene(text="漢" * n, layout={"auto_fit": False}))   # 折り返さない長い1行
            ruby.parse("《" * n)
            return time.perf_counter() - t
        cost(200)
        small_cost, big_cost = cost(1000), cost(4000)
        self.assertLess(big_cost, small_cost * 8)   # 2乗なら約16倍
