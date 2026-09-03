---
paths:
  - "viewer/**/*.ts"
  - "viewer/**/*.vue"
---

# 再生 Web アプリ（Vue 3 + Vite）コーディング規約

検証はホストで実行する:

```bash
cd viewer && npm run check   # format:check → typecheck → lint → test
cd viewer && npm run format  # 整形の崩れを直す
```

## 既存パターンに従う

- **`<script setup lang="ts">` + Composition API**。Options API は使わない
- Props は `defineProps<T>()`、Emit は `defineEmits<T>()` で型定義する
- **fire-and-forget な非同期呼び出しは `void` を付けて明示する**。
  付け忘れは lint（`no-floating-promises`）で落ちる
- `onUnmounted` で後片付けする（`requestAnimationFrame` / イベントリスナー /
  WebGL リソース / `URL.revokeObjectURL`）
- **テンプレートの属性に 2 文以上書かない**（`@click="a(); b()"`）。Prettier が改行して
  `;` を落とし、テンプレートのパースが壊れる。処理は `<script setup>` の関数にまとめて呼ぶ

## WebXR ポリフィルを使う場合の既知の罠（実機で検証済み）

表示経路の第一候補は Bridge.js（`CLAUDE.md` の設計判断）で、この節は使わない。
経路を `@lookingglass/webxr` に切り替えたときのために残している。

ポリフィルは `navigator.xr` を差し替えて動く。three.js 側は本物の WebXR と区別しないので、
three.js のドキュメントには載らない制約がある。

- **ポリフィルの import は表示を開始するときだけ動的に行う。** `navigator.xr` を差し替えるので、
  常時 import すると通常表示にも影響する
- **`requestSession` の前に Bridge のキャリブレーションを待つ。** ポリフィルは非同期で取りに行き、
  届く前にセッションを開くと canvas が既定解像度で固まる（初回だけ像が崩れ、2 回目から直る症状）
- **`requestSession` の前に `isSessionSupported()` を 1 回呼ぶ。** ポリフィル固有の制約で、
  呼ばないと "Must call navigator.xr.isSessionSupported()..." で失敗する
- **`optionalFeatures: ['local-floor']` を付ける。** three.js の既定の参照空間は `local-floor` だが、
  要求しないとセッションで有効にならず `NotSupportedError` になる
- **`renderer.xr.setSession()` の間だけ `window.XRWebGLBinding` を隠す。** three.js はこれがあると
  XRProjectionLayer 経路に入るが、ポリフィルの XRSession はネイティブの `XRWebGLBinding` に渡せない
  （ポリフィルが差し替えるのは `XRWebGLLayer` だけ）
- **XR 終了後にアプリ側のカメラを設定し直す。** three.js は XR 中にカメラの位置と fov を
  書き換えるが、終了しても戻さない
- **XR 終了後は 1 フレーム待ってから canvas を元のサイズに戻す**（終了処理の中で quilt 解像度のまま残る）
- **ポリフィルの設定（右下パネル・ウィンドウ内ドラッグ）はアプリ側の状態を通らずに書き換わる。**
  `on-config-changed` を聞いてアプリ側へ書き戻さないと、UI が古い値のまま残る

## テスト（Vitest）

- テスト対象は純ロジック（quilt のタイル座標計算、動画メタデータの解釈、引数検証）
- WebGL / WebXR の描画経路はテストしない。実機で確認する
