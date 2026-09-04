---
paths:
  - "converter/**/*.py"
  - "viewer/src/**/*.ts"
  - "viewer/src/**/*.vue"
---

# 外部リファレンス（Looking Glass / 深度推定モデル）

**パラメータ名・レイアウト規約・モデルの入出力を推測で書かない。** 必ず下記で現物を確認してから実装する。
非自明な制約をコードに書くときは出典 URL を添える。

## Looking Glass

| ドキュメント | URL |
| --- | --- |
| quilt とは（レイアウト・視点数の考え方） | https://lookingglassfactory.com/tutorial/what-is-a-quilt |
| quilt の主要概念 | https://lfdocs.lookingglassfactory.com/keyconcepts/quilts |
| quilt 動画のエンコード規約 | https://lfdocs.lookingglassfactory.com/keyconcepts/quilts/quilt-video-encoding |
| quilt 動画の再生と音声 | https://docs.lookingglassfactory.com/software/index/quilt-video-audio-and-playback |
| WebXR ライブラリ（`@lookingglass/webxr`） | https://lfdocs.lookingglassfactory.com/software/creator-tools/webxr |
| Bridge SDK（キャリブレーション取得・表示連携） | https://docs.lookingglassfactory.com/software/looking-glass-bridge-sdk |
| Bridge.js（Web から Bridge の media player に quilt を cast する公式ライブラリ） | https://github.com/Looking-Glass/bridge.js |
| コミュニティ製ツール一覧 | https://lfdocs.lookingglassfactory.com/software/third-party-apps-and-tools/community-made-tools-and-projects |

- **quilt の列数×行数と視点数はディスプレイの機種ごとに異なる**（例: Looking Glass 16" は 5 列 × 9 行）。
  変換側でハードコードせず、機種の指定を引数で受ける
- **機種ごとのタイル数はシリアル接頭辞（`LKG-4K` / `LKG-P` など）から引ける。** 対応表は
  `@lookingglass/webxr@0.6.0` の `dist/bundle/webxr.js` にある `LookingGlassConfig` の
  `get quiltWidth` / `get quiltHeight`。**ただしこれをコードへ写さない。** 解像度の既定値が
  実機の値と食い違う（ポリフィル側は Portrait でも 4096² を返す）。実行時に Bridge の
  `defaultQuilt` が返す値のほうが正確なので、ビューアはそれと突き合わせる（`layoutMismatch`）
- 高解像度の quilt 動画はブラウザや OS 標準プレーヤーで再生できない場合がある（コーデック制約）。
  エンコード設定を決めるときは上記「quilt 動画のエンコード規約」を確認する
- **Bridge.js の公式ドキュメントに動画（mp4）の例は無い。** 静止画（jpg）の `QuiltHologram` を `cast` する例のみ。
  quilt 動画を Bridge 経由で再生できるかは実機で確かめてから設計に組み込む

### Bridge.js（`@lookingglass/bridge`）の現物確認で分かったこと

同梱の `dist/*.d.ts` と `dist/looking-glass-bridge.mjs` が唯一の出典。README には型の説明が無い。

- `getDisplays()` の `calibration` は**素の数値**（`pitch: 52.58` の形）。
  `@lookingglass/webxr` の `LookingGlassConfig.calibration` は `{ value: 52.58 }` で包む。**別物なので混ぜない**
- `defaultQuilt` は `{ quiltWidth, quiltHeight }` が**画素数**、`{ columns, rows }` が**タイル数**、
  `quiltAspect` がタイル 1 枚の縦横比。webxr ポリフィル側の `quiltWidth` はタイル数を指すので名前が衝突している
- `QuiltHologram` の `uri` は **Bridge（別プロセス）が読める場所**でなければならない。
  ブラウザ内だけで有効な `blob:` URL は渡せない
- パッケージの `exports` に `"types"` が無く、`moduleResolution: bundler` では同梱の型定義に届かない。
  `viewer/tsconfig.app.json` の `paths` で `dist/index.d.ts` を直接指している
- `exports` の `import` と `require` が**逆**（`import` が CJS、`require` が ESM）。Vite は解決できるが上流のバグ
- **レンチキュラー変換の式は公式ドキュメントに無い。** 唯一の出典は
  `@lookingglass/webxr@0.6.0` の `dist/bundle/webxr.js` にある `Shader()` と、
  `LookingGlassConfig` の `get pitch / tilt / subp`。`viewer/src/lenticular.ts` はこれに合わせている。
  **このパッケージは viewer の依存に入っていない**ので、突き合わせるときは
  `npm pack @lookingglass/webxr@0.6.0` で取り出す
- **タイルは整数サイズの格子に並べ、余った端の画素は UV で除外する。** 公式は
  `tileWidth = round(framebufferWidth / columns)` で格子を作り、`quiltViewPortion` で余白を外す。
  小数境界に置くとどのタイルにも入らない列・行ができる（`viewer/src/lenticular.ts` の `viewPortion`、
  `converter/src/lkg_quilt_converter/quilt.py` の `QuiltSpec.tile_size`）
- **同梱の `.d.ts` は `Display` の `index` / `windowCoords` を `BridgeValue` と宣言しているが、
  実装（`tryParseDisplay`）は全フィールドを unwrap して返す。** 型を信じて `.value` を付けると
  `undefined` になる（型チェックは通る）
- **HTTP API を直に叩くと `calibration` と `defaultQuilt` は JSON の文字列で返る**（`JSON.parse` が要る）。
  bridge.js を経由する場合はライブラリ側が parse する。**Looking Glass 以外のモニタも一覧に混ざり、
  その `calibration` は空文字列**（parse できない）

### 機種の quilt を実機から聞く（ブラウザ不要）

Bridge のローカル API は `http://localhost:33334/<エンドポイント>` への **PUT**。
機種のプリセットを起こすときはここを正本にする。

```bash
TOKEN=$(curl -s -X PUT -H 'Content-Type: application/json' -d '{"name":"probe"}' \
  http://localhost:33334/enter_orchestration | python3 -c 'import sys,json;print(json.load(sys.stdin)["payload"]["value"])')
curl -s -X PUT -H 'Content-Type: application/json' -d "{\"orchestration\":\"$TOKEN\"}" \
  http://localhost:33334/available_output_devices
curl -s -X PUT -H 'Content-Type: application/json' -d "{\"orchestration\":\"$TOKEN\"}" \
  http://localhost:33334/exit_orchestration
```

- 返る `defaultQuilt` が `tileX` / `tileY`（タイル数）と `quiltX` / `quiltY`（画素数）と
  `quiltAspect`（タイル 1 枚の表示上の縦横比）を持つ
- **タイルの画素の縦横比と `quiltAspect` は一致しない。** Go は 4092/11 x 4092/6 = 372x682 画素で
  比は 0.545 だが、表示上は 0.5625。余白の計算は表示上の比で行う
- 実測値（Looking Glass Go, serial `LKG-E`, `hardwareVersion: go_p`）:
  `tileX 11 / tileY 6 / quiltX 4092 / quiltY 4092 / quiltAspect 0.5625`、画面 1440x2560、視野角 54°
- `@lookingglass/webxr@0.6.0` の `LookingGlassConfig` にもシリアル接頭辞ごとの表があり
  タイル数は一致するが、**解像度は実機と食い違う**ことがあるので写さない

## 参考になる既存実装

| 実装 | 何の参考になるか |
| --- | --- |
| https://github.com/9ballsyndrome/WebGL_LookingGlass_QuiltViewer | ブラウザで quilt を表示する最小構成 |
| https://github.com/amariichi/VideoDepthViewer3D | 深度推定 + three.js/WebXR + Looking Glass 出力の全体構成（入力は単眼） |
| https://github.com/JuanIrache/looking-glass-after-effects | 横移動ショットから quilt を組む考え方 |
| https://github.com/peterwilli/Liquilt | quilt を Web 配信しやすくする形式変換 |

## 深度（視差）推定モデルの候補

入力がステレオ 2 視点なので、**単眼深度推定ではなくステレオマッチング**を第一候補にする
（視差から直接求まり、スケールの曖昧さがない）。

| モデル | 位置づけ | URL |
| --- | --- | --- |
| Stereo Any Video | 動画向け。フレーム間の時間的一貫性を扱う | https://arxiv.org/html/2503.05549v1 |
| FoundationStereo | ゼロショット精度重視。1 枚あたりは重い | https://arxiv.org/pdf/2501.09898 |
| Fast-FoundationStereo | 上記を約 10 倍高速化（CVPR 2026） | https://github.com/NVlabs/Fast-FoundationStereo |

- **動画では単フレーム精度より時間的一貫性が効く。** 深度がフレーム間でブレると、
  再生時にちらつきとして見える
- **無地の面はどのステレオマッチングでも視差が決まらない**（同じ色がどこにでも合う）。
  既定の SGBM では背景の視差に潰れる。深層モデルに替えるときの主な動機はここ
- PyTorch は Python 3.10〜3.14 に対応する（https://pytorch.org/get-started/locally/ で確認）
