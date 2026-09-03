# lkg-quilt-studio

ステレオ動画（左右 2 視点）を [Looking Glass](https://lookingglassfactory.com/) 用の
**quilt 動画**に変換し、ブラウザで再生するツール。

## 仕組み

Looking Glass は視点ごとに数十枚の画像（quilt）を同時に表示し、見る角度で切り替えて視差を作る。
ステレオ動画は 2 視点しか持たないため、そのまま流しても裸眼立体の視差にならない。
そこで視差から深度を求め、足りない視点を合成してから quilt に焼き込む。

```
ステレオ動画 → 視差(深度)推定 → 視点合成(DIBR) → quilt レイアウト → quilt 動画 → ブラウザで再生
└──────────── converter（Python CLI・事前レンダリング） ────────────┘   └─ viewer（Vue 3 + three.js）─┘
```

変換を事前レンダリングにしているのは、深度推定と視点合成が重く、再生時の負荷をゼロにしたいため。

## 構成

| ディレクトリ | 役割 |
| --- | --- |
| `converter/` | 変換 CLI（視差推定 → 視点合成 → quilt エンコード） |
| `viewer/` | 再生 Web アプリ（quilt 動画を Looking Glass に表示） |

## 必要なもの

- [mise](https://mise.jdx.dev/)（node と uv のバージョンを管理する。`.mise.toml` が正本）
- ffmpeg（動画の入出力）
- Looking Glass 本体と Looking Glass Bridge（実機表示の確認用）

## セットアップ

```bash
mise install              # node と uv を入れる
uv python install 3.14    # Python 本体は uv が管理する
cd converter && uv sync   # 変換 CLI の依存
cd viewer && npm ci       # 再生アプリの依存
```

## 開発

```bash
cd converter && uv run poe check   # ruff format → ruff check → mypy → pytest
cd converter && uv run poe format  # 整形の崩れを直す

cd viewer && npm run dev           # 開発サーバー
cd viewer && npm run check         # format:check → typecheck → lint → test
cd viewer && npm run build         # .vue のテンプレートを触ったらこれも通す
```

AI エージェント向けの運用ルール・検証フロー・設計判断は [CLAUDE.md](CLAUDE.md) を参照。
`.claude/` は Claude Code 用の設定（レイヤ別の規約・レビュー観点・スキル）。
人が読むコントリビュートガイドとしても使えるように書いている。

## 状態

土台の整備まで完了。変換パイプラインと再生の描画は未実装。

- `converter/`: quilt のレイアウト計算（タイル座標・ファイル名規約）まで
- `viewer/`: quilt 動画を選んでレイアウトを判定する入口まで

視差推定・視点合成・quilt エンコード・Looking Glass への描画はこれから。

## ライセンス

[MIT License](LICENSE)

Looking Glass は Looking Glass Factory, Inc. の商標。本プロジェクトは同社とは無関係の非公式なツールで、同社による承認・支援を受けていない。
