---
name: apng-maker
description: ゲームや動画の素材として、APNG（アニメーションPNG）をローカルで作る。「APNGを作って」「文字アニメ」「カットイン」「戦闘開始の演出」「レベルアップの文字」「テロップ」「スプライトシート」「連番PNGをアニメに」「APNGを分解」がトリガー。文字アニメ（登場・表示中・退場の効果、縁取り・影・発光・帯）、連番画像からの組み立て、APNGの分解・検査、ゲームエンジン向けのシートとJSONの書き出しまでを、Python と Pillow だけで行う。ネットワークには出ない。
---

# apng-maker

APNG をローカルで作るためのスキル。Python 3 と Pillow だけで動き、ネットワークには出ない。

```
シーン(JSON) → 配置（1文字ずつ） → タイムライン（文字ごとの開始時刻） → 時刻 t の1枚 → APNG
                                                              └→ シート＋JSON / 連番PNG / 確認用の一覧
```

同じシーンと同じ時刻からは、必ず同じ絵が出る。乱数は文字番号と時刻から決めている。

## 入口

コマンドは、このスキルのフォルダにある `scripts/apngmk.py` である。

```bash
A=<このスキルのフォルダ>/scripts/apngmk.py
python3 $A presets          # プリセット一覧
python3 $A effects          # 効果の一覧
python3 $A text --preset battle_start --text "ボス戦" -o output/boss.png --preview
```

完成物の置き場所は、作業中のプロジェクトの決まりに従う。決まりが無ければ `output/` に置く。

## 作り方の手順（AI が作るとき）

1. **プリセットを選ぶ。** 近いものを `presets` から選ぶ。なければ一番近いものを土台にして `--set` で変える
2. **`--preview` を付けて書き出す。** `<名前>_preview.png` に、間引いたフレームが時刻付きで並ぶ
3. **プレビュー画像を Read で見る。** 文字の欠け、縁取りの点、はみ出し、動きの順序を確かめる。APNG のアニメーションは目で再生できないので、必ずこの一覧で見る
4. 直して、2 に戻る
5. 仕上げで `--palette`（256色・軽量）を付ける。ゲームで使うなら `--sheet` も付ける
6. `python3 $A info <出力>` で、フレーム数・ループ回数・全体の秒数を確かめる

## プリセット

| 名前 | 用途 |
|---|---|
| `battle_start` | 戦闘開始のカットイン。帯が開き、文字が叩きつけられて画面が揺れる |
| `level_up` | レベルアップ。跳ねて現れ、表示中は波打つ（表示中はループ可） |
| `stage_clear` | 中央から順にポップし、表示中は鼓動する |
| `game_over` | ぼかしから浮かび、そのまま残る（1回再生） |
| `ready_go` | 対戦前の掛け声。スライドで入り、ズームで抜ける |
| `warning` | ボス接近の警告。グリッチで現れて点滅する |
| `location_telop` | 場所テロップ。サブテキスト＋本文＋伸びる下線 |
| `dialog_typewriter` | 会話ウィンドウの文字送り |
| `title_vertical` | 和風タイトル（縦書き・明朝） |

## 設定を変える

`--set キー=値` を何度でも重ねられる。値は JSON として読む（数値・配列・オブジェクトがそのまま入る）。

```bash
python3 $A text --preset level_up --text "RANK UP" \
  --set anim.in.fx=pop --set anim.in.order=center \
  --set 'style.fill={"type":"gradient","colors":["#ffffff","#66ccff"]}' \
  -o output/rankup.png --preview
```

まとまった変更は JSON ファイルにして `--scene my.json` で渡す（プリセットの上に重なる）。
`--dump-scene` を付けると、既定値を補ったあとの全設定が出る。

### 主なキー

大きさの単位は **em**（文字サイズの倍数）。例外は `font.size`・`canvas`・`layout.margin`・`layout.offset`・`layout.wrap_width`・`export.trim_pad` で、これらは px。時間はすべて秒。

| キー | 意味 |
|---|---|
| `text` / `sub.text` | 本文 / サブテキスト（`\n` で改行）。`sub.position` は `above` か `below` |
| `writing` | `horizontal` / `vertical` |
| `canvas.width` `height` `background` | 描く面の大きさ。背景は既定で透明 |
| `font.family` `weight` `size` `letter_spacing` `line_height` | `family` は `gothic` か `mincho`、またはフォントファイルのパス。`weight` は `regular`〜`black` |
| `font.kerning` / `font.palt` | ペアカーニング（既定 true）/ 日本語の詰め（既定 false。かなや括弧の左右の空きを詰める） |
| `ruby.size` / `ruby.gap` | ルビの大きさと、親字との間（既定 0.5 / 0.05） |
| `layout.align` `anchor` `margin` `offset` `auto_fit` `wrap_width` | 寄せ方・縦位置。`auto_fit` は、行の長さか行を重ねた厚みがはみ出すとき、文字を縮める（縁取りや影のはみ出しは見ない）。`wrap_width` を指定すると、その px 幅で折り返す（簡易禁則つき。縮めても幅は変えない） |
| `style.fill` | `{"type":"solid","color":"#fff"}` か `{"type":"gradient","colors":[…],"dir":"v"または"h"}` |
| `style.strokes` | 縁取りの配列 `[{"width":0.12,"color":"#000"},…]`。複数書くと二重縁になる |
| `style.shadow` / `style.glow` | `{"dx","dy","blur","color","opacity"}` / `{"radius","color","opacity"}` |
| `deco.type` | `none` `band`（帯） `box`（箱） `underline` `lines`（上下線） |
| `anim.in` / `anim.out` | `fx` `dur` `stagger`（1文字ごとの遅れ） `order` `dir` `ease` |
| `anim.hold` | `fx` `dur` `period`（周期） `amp`（強さ） |
| `anim.camera_shake` | `{"at":"in_end","dur":0.3,"amp":0.06}`。全体を揺らす |
| `export` | `fps` `loop`（0=無限・n=n回） `palette` `trim` `trim_pad` `poster` `tail` |

### ルビ

青空文庫式で書く。`--text '魔王《まおう》を倒せ'` のように渡す。

| 書き方 | 親字 |
|---|---|
| `魔王《まおう》` | 《 の直前にある漢字の連なり |
| `｜古の剣《いにしえのつるぎ》` | ｜ から 《 まで（かなや英字を含む親字はこちら） |

- 横書きは親字の上、縦書きは親字の右に付く。ルビのある文字組は、そのぶん行送りが広がる
- ルビが親字より短ければ均等に割り付け、長ければ親字の中央に合わせてはみ出させる。行の寄せと自動縮小は、はみ出しまで含めて測る（折り返しの判定は親字の長さだけで行う）
- ルビは親字と同じ動きをする（移動量も親字に合わせる）
- 親字や読みが空、または空白だけの記法はルビにならず、そのまま文字として出る
- ルビは親字の最初の文字と同じ時刻に登場し、退場する
- 折り返しは親字の途中で切らない
- 対応する 》 が同じ段落に無い 《 や、親字の無い 《》 は、そのまま文字として出る

### 縦書き

`writing=vertical` にすると、フォントの縦書き用字形で描く。句読点、括弧、長音、小書き文字、三点リーダーは、縦書き用の形と位置になる。
2桁までの半角数字と `!?` は縦中横（`12`、`!?`）にし、それより長い半角英数字は横倒しにする。

### 効果

| 区間 | 名前 |
|---|---|
| 登場 `in` | fade, rise, drop, slide, pop, shrinkIn, zoomIn, slam, spin, flip, bounce, blurIn, scatter, typewriter, flicker, glitch, flash, wipe, none |
| 表示中 `hold` | none, float, wave, pulse, shake, blink, glow, flicker, glitch |
| 退場 `out` | fade, rise, sink, slide, shrink, growOut, zoomThrough, blurOut, scatter, erase, flicker, glitch, wipe, none |
| 順序 `order` | forward, reverse, center, edges, random |

`out.fx=none` にすると消えずに残る。1回再生（`loop=1`）なら、最後の状態で止まる。

## ゲームで使う

`--sheet` を付けると、`<名前>_sheet.png`（格子に並べた1枚）と `<名前>_sheet.json` が出る。

```json
{
  "frame_width": 780, "frame_height": 378, "columns": 11, "count": 107,
  "fps": 30, "loop": 0,
  "origin": [88, 26],
  "segments_frames": {"in": [0, 29], "hold": [29, 89], "out": [89, 107]},
  "hold_loopable": true,
  "frames": [{"x": 0, "y": 0, "w": 780, "h": 378, "duration_ms": 33}]
}
```

- **`segments_frames`**：in → hold → out のフレーム範囲（開始を含み、終わりを含まない）。各フレームは、描いた時刻が入る区間に振り分ける。in を1回流し、hold をループさせ、閉じるときに out を流す、という使い方ができる。番号は**シートと連番 PNG の番号**である。APNG は同じ絵が続くフレームを1枚に結合するため、枚数が少なくなる（実行結果の `frames` と `apng_frames` の差）。区間ごとに切り替えて再生するなら、シートか連番 PNG を使う
- **`hold_loopable`**：hold の区間を繰り返したとき、切れ目なくつながるか。次をすべて満たすと true になる
  - 表示中の効果が周期的である（none・float・wave・pulse・blink・glow）。float の周期は `period × 1.6`
  - `hold.dur` が 0 より長く、周期の整数倍で、しかも `hold.dur × fps` が整数（hold の枚数が割り切れる）
  - 画面揺れが hold に重ならず、装飾は hold の前に開き終わっている
- **`origin`**：余白を切り落とした絵が、元の描画面のどこにあったか。画面中央に出す演出は、この値で位置を戻せる
- 連番 PNG が欲しいときは `--frames-dir <ディレクトリ>`
- 実行結果の `duration_s` はタイムラインの長さ、`playback_s` は実際の再生時間である。最後の1枚（完成した状態か、消えきった状態）にも 1/fps 秒の表示時間が付くので、`playback_s` のほうが少し長い
- `--palette` を付けると APNG とプレビューは256色になる。シートと連番 PNG はフルカラーのままである

## 既存の画像を扱う

AI で作ったキャラクターの連番画像などを、そのまま APNG にできる。

```bash
python3 $A frames "work/walk_*.png" --fps 12 --pingpong --trim --palette --sheet -o output/walk.png --preview
python3 $A frames work/idle/ --durations 200,100,100,300 --loop 0 -o output/idle.png
python3 $A split output/walk.png --sheet          # 連番 PNG ＋ 表示時間の JSON へ分解
python3 $A info output/walk.png --verbose         # チャンクを直接読んで検査
```

- 入力の大きさが揃っていなければ、最大の大きさへ中央寄せで余白を足す（`--fit error` で止める）
- `split` が書いたフォルダを `frames` に渡すと、`*_timing.json` に並ぶファイルだけを、元の表示時間とループ回数で組み直す（同じフォルダの `_sheet.png` は読まない）。`--fps`・`--durations`・`--loop` を付ければ、そちらが優先される
- `split` は表示時間を経過時刻で丸める。1/120 秒のような ms で割り切れない値でも、合計の長さが縮まない
- 並び順は自然順（`f2.png` が `f10.png` より先）

## 軽くするには

APNG は差分の矩形だけを保存し、同じ絵が続くフレームは1枚に結合する。それでも大きいときは、次の順に効く。

1. `--palette`（256色）。グラデーションや発光が強いと色の段差が出るので、プレビューで確かめる
2. `--fps` を下げる（24 や 20）
3. 表示中の効果を `none` にする。毎フレーム全体が動く効果（wave・shake）は、差分が小さくならない
4. `font.size` と `canvas` を小さくする

## 限界

- 1文字ずつ描くので、文字をまたぐ合字（ffi など）や、前後の文字で形が変わる字形は使わない（無効にしてある）。アラビア文字のような、つながって形が変わる文字は正しく描けない
- カーニング、日本語の詰め、縦書き用字形は、Pillow が raqm 付きでビルドされているときだけ効く。raqm が無ければ、1文字ずつの配置と、回転と位置ずらしによる縦書きの近似になる
- ルビは1かたまりに1つで、熟語ルビ（親字1文字ずつに分けて付ける組み方）や肩付きはしない。ルビが長いときに親字の字間を空ける調整もしない
- 縦中横は2桁までの半角数字と `!?` だけである
- 256色化は全フレームで1つのパレットを共有する。全フレームの画素数が 4000万以下なら全フレームを並べて減色し、超えると間引いた見本からパレットを作って1枚ずつ当てはめる。後者は透明度を16段にまとめるので、輪郭のなめらかさがわずかに落ちる
- 全フレームを手元に持ってから書き出すので、長くて大きいアニメーションはメモリを使う。1916×843 を212枚（60fps で約3.5秒）書き出したとき、256色で約3GB・40秒、フルカラーで約3.7GB・172秒だった
- フォントの別名は fontconfig（`fc-match`）で探す。手元に無いフォントはパスで渡す

## 検証

```bash
cd <このスキルのフォルダ> && python3 -m unittest discover -s tests -v
```

確かめていること:

- APNG の構造（CRC、途中で切れていないこと、チャンクの順序、通し番号、フレームの寸法、dispose と blend の値、各フレームの画像データ、フレーム数、ループ回数、既定画像）
- 同じ時刻から同じ絵が出ること（RGB まで含めて比べる）
- 全効果と全プリセットが描けること
- 分解して元に戻ること
- シートの座標
- 区間とループの判定
- 不正な数値を受け付けないこと
- ルビの解析と配置、カーニングと日本語の詰め、縦書き用字形と縦中横、大きなアニメーションの256色化
