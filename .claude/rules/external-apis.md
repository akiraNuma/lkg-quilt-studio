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
- 高解像度の quilt 動画はブラウザや OS 標準プレーヤーで再生できない場合がある（コーデック制約）。
  エンコード設定を決めるときは上記「quilt 動画のエンコード規約」を確認する
- **Bridge.js の公式ドキュメントに動画（mp4）の例は無い。** 静止画（jpg）の `QuiltHologram` を `cast` する例のみ。
  quilt 動画を Bridge 経由で再生できるかは実機で確かめてから設計に組み込む

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
- PyTorch は Python 3.10〜3.14 に対応する（https://pytorch.org/get-started/locally/ で確認）
