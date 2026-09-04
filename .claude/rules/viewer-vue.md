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

**`npm run typecheck` は `vue-tsc -b --force`。** `tsconfig.json` は `files: []` の solution 形式なので、
`vue-tsc --noEmit` だと 1 ファイルも検査しない（緑になっても意味が無い）。

## localhost のポートを他プロジェクトと共有する罠（実際に踏んだ）

**別プロジェクトが登録した Service Worker は、ポートが同じなら生き残ってこのアプリの fetch を横取りする。**
`localhost:5173` に残っていた `sw.js` が `/api/projects` を毎秒 500 回叩き、プレビューが届かなくなった。
このアプリは Service Worker を使わないので、`main.ts` で起動時に全部 unregister する。

症状は「API が遅い・返らない」で、コードを見ても原因が出ない。**api のログに身に覚えのない
パスの 404 が並んでいたら、まず Service Worker を疑う**（DevTools の Application で確認できる）。

## ルートが複数の SFC を flex の中に置かない（実際に踏んだ）

**`<template>` のルートが複数あると、その全部が親のレイアウトの直下の要素として並ぶ**
（Fragment は箱を作らない）。親が `display: flex` の行だと、テクスチャ供給元として置いた
4092 px の `<video>` がそこへ張り出し、画面が横へ崩れた。ルートは 1 つにまとめる。

テクスチャの供給元にする `<video>` / `<img>` は**見せない**（1 px にして隠す）。
`<video controls>` を並べると 4092² の生の絵が場所を取る。再生・一時停止・シークは
自前のボタンとスライダーで出す（`QuiltStage.vue` の `.transport`）。

## 数値の入力欄に `type="number"` を使わない（実際に踏んだ）

**`<input type="number">` は全角数字・`1,000`・末尾の空白を黙って捨てて `value` を空文字にする。**
IME が有効なら簡単に起きる。**空欄に意味を持たせている欄では、捨てられた入力が既定の挙動に化ける**
（「フレーム数 1000」の指定が「空＝動画の最後まで」になり、58,735 フレームの変換が走った）。

`type="text"` + `inputmode="numeric"` で受け、全角を半角へ直してから自分で検証する。
読めない値は**弾いて赤く見せる**（黙って既定へ落とさない）。実行前に「何をするか」を
文章で出して確認できるようにする（`QuiltWorkbench.vue` の `parseCount` / `rangeNote`）。

## 自前シェーダーを書くときの罠

- **`ShaderMaterial` ではなく `RawShaderMaterial` を使う。** 前者は `position` / `uv` の宣言と
  フラグメントの出力変数を自動で足すので、自前のシェーダーと二重定義になってコンパイルが落ちる
  （症状は console の `'uv' : redefinition` と `no valid shader program in use`）
- **シェーダーのコンパイルエラーは console にしか出ない。** `npm run check` も `npm run build` も通る
- **シェーダーのコメントにバッククォートを書かない。** GLSL はテンプレートリテラルの中にあるので、
  バッククォートで文字列が途切れる。症状は Prettier が出す GLSL 行の `SyntaxError: ';' expected`
- **quilt のテクスチャはミップマップを作らせない**（`generateMipmaps = false` と `minFilter = LinearFilter`）。
  レンチキュラー表示は隣り合う画素が別のタイルを掴むので、GPU は「極端に縮小されている」と見て
  粗いミップを引き、画面が quilt の平均色一色になる（実測でコントラストが 標準偏差 48 → 9 に潰れた）。
  **`VideoTexture` は既定でミップを作らないので動画では出ず、静止画のプレビューだけで出る**

## WebXR ポリフィルを使う場合の既知の罠（実機で検証済み）

**この節は今の実装では使わない。** 表示は Bridge から較正値を取って自前のシェーダーで描く
（`CLAUDE.md` の設計判断）。`@lookingglass/webxr` に切り替えたときのために残している。

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
