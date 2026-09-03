---
paths:
  - "converter/**/*.py"
---

# 変換 CLI（Python + uv）コーディング規約

検証はホストで実行する:

```bash
cd converter && uv run poe check    # ruff format --check → ruff check → mypy → pytest
cd converter && uv run poe format   # 整形の崩れを直す
```

依存の追加は `uv add`（開発用は `uv add --dev`）。`pyproject.toml` と `uv.lock` を手で書かない。

**Python 本体は uv が管理する（`uv python install`）。mise で python を入れない。**
mise の python は free-threaded ビルドを掴むことがあり、`lib` ディレクトリが無い状態で入って壊れる
（"Python installation is missing a lib directory" で落ちる）。uv は GIL 有りのビルドを選ぶ。

## 方針

- **型ヒントを付ける**（mypy が通る範囲で）。`Any` に逃げる場合は理由をコメントで書く
- **1 段階 = 1 モジュール**にする（視差推定 / 視点合成 / quilt レイアウト / エンコード）。
  段階ごとに中間成果（深度マップ・視点画像）をファイルに落とせる形を保つ。
  途中でやり直せないと、重い処理を毎回全部やり直すことになる
- **I/O 境界（動画の読み書き・ffmpeg 呼び出し・モデルの重みの読み込み）のエラーは厚く扱う。**
  失敗したら何が悪かったか（パス・コーデック・形状）をメッセージに含めて落とす。
  内部関数どうしの呼び出しは trust する
- **重い処理には進捗を出す。** フレーム単位のループは総フレーム数と現在位置を表示する
- モデルの重み・入出力の実データはリポジトリに入れない（`.gitignore` 済み）

## テスト（pytest）

- テスト対象は純ロジック（quilt のレイアウト計算、視点位置の割り当て、引数の検証）
- モデル推論そのものはテストしない（重みが必要で、実行時間も現実的でない）。
  推論を呼ぶ関数は入出力の形状（shape / dtype）だけを検証する
