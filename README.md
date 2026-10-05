# apng-maker

ゲームのカットインやテロップに使う文字アニメを、APNG（アニメーション PNG）で書き出すツールです。
Claude Code のスキルとして置くと、Claude に「戦闘開始のカットインを作って」と頼むだけで、プリセットを選んで書き出し、仕上がりを画像で確かめるところまで進めてくれます。
コマンドラインから直接使うこともできます。

<p>
<img src="docs/battle_start.png" alt="戦闘開始のカットイン" width="320">
<img src="docs/level_up.png" alt="LEVEL UP の文字アニメ" width="320">
</p>
<p>
<img src="docs/warning.png" alt="WARNING の警告演出" width="320">
<img src="docs/title_vertical.png" alt="縦書きの和風タイトル" width="120">
<img src="docs/ruby_vertical.png" alt="ルビと縦中横を使った縦書き" width="150">
</p>

処理はすべて手元で完結し、ネットワークには接続しません。
必要なのは Python と Pillow だけです。

## できること

| 機能 | 内容 |
|---|---|
| 文字アニメ | 登場19種、表示中9種、退場14種の効果を、1文字ずつ時間差をつけて動かす。縁取り（二重も可）、影、発光、グラデーション、帯や箱の装飾、画面揺れに対応 |
| 文字組み | カーニングと日本語の詰め、青空文庫式のルビ（`魔王《まおう》`）、縦書き用字形による縦書き、縦中横 |
| ゲーム向けの書き出し | フレームを格子に並べたスプライトシートと、その座標や区間を書いた JSON を出す |
| 既存画像の組み立て | AI で生成したキャラクターの連番画像などを、APNG とスプライトシートにまとめる |
| 分解と検査 | APNG を連番 PNG と表示時間の JSON に分解する。チャンクを直接読んで、規格どおりか検査する |

同じ設定と同じ時刻からは、必ず同じ絵が出ます。
文字の飛び散り方やノイズの乱数は、文字の番号と時刻から決めています。
そのため、プレビューで見た絵と書き出した絵がずれることはありません。

## 必要なもの

- Python 3.10 以降
- Pillow（12.3 で動作を確認しています）
- 日本語フォント。既定では fontconfig の `fc-match` で Noto Sans CJK JP と Noto Serif CJK JP を探します。fontconfig の無い環境では、`font.family` にフォントファイルのパスを渡してください

```bash
pip install pillow
```

## Claude Code のスキルとして使う

使い方は、スキルの置き場所へ複製するだけです。

```bash
# 自分のすべてのプロジェクトで使う
git clone https://github.com/nouer/apng-maker.git ~/.claude/skills/apng-maker

# 特定のプロジェクトでだけ使う
git clone https://github.com/nouer/apng-maker.git <プロジェクト>/.claude/skills/apng-maker
```

あとは「レベルアップの文字アニメを APNG で」「この連番 PNG をスプライトシートにして」のように頼めば、Claude が `SKILL.md` の手順に沿って作業します。
Claude は APNG の動きを目で再生できません。
そこで、フレームを間引いて並べたプレビュー画像を書き出し、それを読んで仕上がりを確かめる手順にしています。

## コマンドラインで使う

入口は `scripts/apngmk.py` です。

```bash
python3 scripts/apngmk.py presets      # プリセットの一覧
python3 scripts/apngmk.py effects      # 効果の一覧

# プリセットの文言を差し替えて書き出す。--preview で確認用の一覧画像も出る
python3 scripts/apngmk.py text --preset battle_start --text "ボス戦" --preview -o output/boss.png

# 設定は --set で上書きできる。値は JSON として読む
python3 scripts/apngmk.py text --preset level_up --text "RANK UP" \
  --set anim.in.fx=pop --set anim.in.order=center \
  --set 'style.fill={"type":"gradient","colors":["#ffffff","#66ccff"]}' \
  --palette --sheet -o output/rankup.png
```

まとまった設定は JSON ファイルに書いて `--scene` で渡します。
`--dump-scene` を付けると、既定値を補ったあとの全設定を表示します。
設定項目と効果の一覧は `SKILL.md` を見てください。

### プリセット

| 名前 | 内容 |
|---|---|
| `battle_start` | 帯が開き、文字が叩きつけられて画面が揺れる |
| `level_up` | 跳ねて現れ、表示中は波打ちながら光る |
| `stage_clear` | 中央から順にポップし、表示中は鼓動する |
| `game_over` | ぼかしから浮かび、そのまま残る |
| `ready_go` | スライドで入り、ズームで抜ける |
| `warning` | グリッチで現れ、点滅する |
| `location_telop` | 小さな見出しと場所名、伸びる下線 |
| `dialog_typewriter` | 会話ウィンドウで1文字ずつ表示する |
| `title_vertical` | 縦書き、明朝の和風タイトル |

## ゲームに組み込む

`--sheet` を付けると、`<名前>_sheet.png` と `<名前>_sheet.json` が出ます。

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

`segments_frames` は、登場（in）、表示中（hold）、退場（out）のフレーム範囲です。
登場を1回流し、表示中の区間を必要なだけ繰り返し、閉じるときに退場を流す、という再生のための区切りです。
表示中の区間を繰り返しても継ぎ目が出ないときに限り、`hold_loopable` が `true` になります。

`origin` は、透明な余白を切り落とす前の描画面での、絵の左上の座標です。
画面の中央に出す演出なら、この値で元の位置へ戻してください。

APNG のほうは同じ絵が続くフレームを1枚に結合して軽くしているため、フレーム数がシートより少ないことがあります。
区間を切り替えながら再生する場合は、シートか連番 PNG（`--frames-dir`）を使ってください。

## 連番画像から作る

```bash
# 歩行の連番を往復再生の APNG とシートにする
python3 scripts/apngmk.py frames "work/walk_*.png" --fps 12 --pingpong --trim --sheet -o output/walk.png

# フレームごとに表示時間を変える（ms）
python3 scripts/apngmk.py frames work/idle/ --durations 200,100,100,300 -o output/idle.png

# 分解して、組み直す
python3 scripts/apngmk.py split output/walk.png
python3 scripts/apngmk.py frames output/walk_frames/ -o output/walk2.png

# 規格どおりか検査する
python3 scripts/apngmk.py info output/walk.png
```

大きさの揃っていない画像は、いちばん大きい画像に合わせ、中央に寄せて透明な余白を足します。
ファイルの並びは自然順（`f2.png` が `f10.png` より先）です。

## ファイルを軽くするには

`level_up`（780×378、30fps、フルカラー）は 6.9MB ありました。
ここから1つずつ変えたときの大きさが、次の表です（効いた順）。

| 変えたこと | 大きさ |
|---|---|
| `--palette` で256色にする | 1.1MB |
| 表示中の効果（波打ち）を `none` にする | 2.2MB |
| 文字と描画面を縦横それぞれ約6割にする | 2.6MB |
| `--fps 15` にする | 3.5MB |

256色化がいちばん効きます。
ただし、グラデーションや発光が強いと色の段差が出るので、プレビューで確かめてください。
波打ちや震えは毎フレーム全体が動くため、前のフレームとの差分が小さくならず、ファイルが重くなります。

## ルビと縦書き

ルビの書き方は青空文庫式です。

```bash
python3 scripts/apngmk.py text --preset title_vertical \
  --text '第12話\n｜夜明け《よあけ》の約束《やくそく》' -o output/title.png
```

`約束《やくそく》` のように書くと、《 の直前にある漢字の連なりが親字になります。
かなを含む親字は、`｜夜明け《よあけ》` のように ｜ で始まりを示してください。

縦書きの句読点や括弧、長音には、フォントに入っている縦書き用の字形を使います。
数字は2桁までなら縦中横、それより長い英数字は横倒しです。

## 制約

- カーニングと日本語の詰め、縦書き用の字形が効くのは、Pillow が raqm 付きでビルドされているときだけです。使えるかどうかは `python3 -c "from PIL import features; print(features.check('raqm'))"` で確かめられます。raqm が無い環境では1文字ずつ並べ、縦書きは回転と位置ずらしで近似します
- ルビは親字のかたまりごとに1つ付けます。熟語ルビ、肩付き、ルビが長いときの親字の字間調整はしません
- 縦中横の対象は、2桁までの半角数字と `!?` に限られます
- 全フレームを手元に持ってから書き出すため、長くて大きいアニメーションはメモリを使います。1916×843 の212枚では、256色で約3GB、フルカラーで約3.7GB でした

## テスト

```bash
python3 -m unittest discover -s tests -v
```

APNG の構造の検査、同じ時刻から同じ絵が出ること、全効果と全プリセットの描画、分解と組み直し、シートの座標、ループの判定、不正な入力の拒否を確かめています。

## ライセンス

MIT License。詳しくは [LICENSE](LICENSE) を見てください。
