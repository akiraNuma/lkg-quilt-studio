---
paths:
  - "viewer/**/*.ts"
  - "viewer/**/*.vue"
  - "viewer/**/*.css"
---

# 再生 Web アプリ（Vue 3 + Vite）コーディング規約

検証はホストで実行する:

```bash
cd viewer && npm run check   # format:check → typecheck → lint → build → test
cd viewer && npm run format  # 整形の崩れを直す
```

**`build` を `check` に入れてあるのは、`<style>` の構文エラーを他の誰も見ないから**
（実測: 壊れた CSS は format:check も lint も素通りし、`vite build` だけが落ちる）。
テンプレート式の構文エラーと閉じタグの不一致は lint が捕まえる（`vue/no-parsing-error`）。

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

## 状態の持ち主とレイヤ

- **状態は composable が持ち、`App.vue` は結線とレイアウトだけ**を持つ。
  素材・変換の設定・プレビューの自動描画は `composables/usePreview.ts`、
  ジョブの進捗は `useConvertJob.ts`、再生する quilt は `useQuiltSource.ts`
- **HTTP は `src/api.ts` に集める**（Vue 非依存・失敗は例外で投げる）。
  画面に出す文言への変換は composable 側で `api.describe()` を通す
- **パネルは設定を 1 項目ずつ `defineModel` で受ける。** 設定のオブジェクトをまるごと
  `v-model` で渡して子で `settings.value.layout = x` と書くと、`update:settings` が
  飛ばないまま親のオブジェクトを直接書き換えることになり、v-model が名ばかりになる
  （親が computed や凍結オブジェクトを渡した瞬間に黙って壊れる）

## 見た目は `src/styles.css` に寄せる

**色を scoped CSS に直書きしない。** 配色は `:root` の CSS 変数にあり、ボタン・入力欄・
スライダーの見た目もそこで一度だけ当てている。画面はダーク一本（`color-scheme: dark`）。

`.panel` / `.row` / `.note` / `.warn` / `.error` は全画面で共通の並べ方なので
グローバルに置いてある。scoped 側にはそのコンポーネント固有の配置だけを書く。

ライブラリの小見出しと空の状態文は、同じ文字サイズ・色にしない。
小見出しを明るく太くし、空の状態文は独立した余白のある領域へ置く。
素材の取り込みは、ボタン選択とドラッグ＆ドロップの両方を維持する。

## 文言は `src/i18n.ts` に置く（日本語 / 英語）

**画面に出る文字をコンポーネントへ直書きしない。** `t('キー')` で引く。
`{name}` を含むキーは `t('キー', { name })` で埋める。

- **キーは `ja` に足す。`en` は `Record<keyof typeof ja, string>` なので、
  足し忘れると typecheck が落ちる**（英語だけ抜けるのを機械で止める。
  vue-i18n を採らなかったのはこれが効くから。判断の経緯は `CLAUDE.md`）
- ステータスや種別からキーを引くときは `Record<型, MessageKey>` の表を作る
  （文字列連結でキーを組むと型が効かない）
- `.ts` からも呼べる（`format.ts` の単位、`quilt.ts` の食い違いの文、`useBridge.ts` の状態）
- **テストは locale を明示する。** 既定は `navigator.language` で決まるので、
  文言を照合するテストは `beforeEach(() => setLocale('ja'))` を置く
  （置かないと環境の言語で落ちる。実際に落ちた）
- **`<input type="file">` の見た目と文言はブラウザの言語で決まる。** 訳せないので、
  自前のボタンから `input.click()` で開く（`SourcePanel.vue`）
- **文言は文として読める形にする。**「まだ無い」のような語の切れ端を置かない（指摘を受けた）。
  空の一覧は**「まだありません」の形**にする（行動の指示に置き換えるのも直しすぎ。
  「書き出すとここに並ぶ」は差し戻された）
- **`t()` の結果を ref に持ち回さない。** 言語を切り替えても戻らない文言が残る
  （プレビューの「N フレーム目」で踏んだ）。表示する側の computed で組む
- 変換 API が返す失敗の文はサーバー側の日本語。ここでは訳さない

## dev サーバーがファイルの変更を拾わないとき

**エージェントのサンドボックスから起動した `npm run dev` は FSEvents が届かず、HMR が黙る。**
症状は「直したのに画面が変わらない」で、`touch` しても vite のログに `hmr update` が出ない。
`VITE_USE_POLLING=1 npm run dev` で起動すれば拾う（`vite.config.ts` が見る環境変数）。

## localhost のポートを他プロジェクトと共有する罠（実際に踏んだ）

ブラウザ検証は専用の独立した Chromium プロファイルを使う。
Playwright MCP の共有プロファイルは、別セッションの使用中にロックで起動できない。

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
文章で出して確認できるようにする（`format.ts` の `parseCount`、`ExportPanel.vue` の `plan`）。

## WebGL の canvas は使い回さない（実際に踏んだ）

**`WebGLRenderer.dispose()` の前に `forceContextLoss()` を呼んだ canvas では、二度と
context を取れない。** 同じ `<canvas>` に新しい `WebGLRenderer` を作ると
`Cannot read properties of null (reading 'precision')` で落ち、絵が真っ白になる。
プレビュー（静止画）から変換結果（動画）へ移るときに必ず通る道。

**canvas ごと作り直す**（`QuiltStage.vue` の `:key="source.kind"` と `restart()`）。
別窓へ移している最中なら、作り直した canvas をその窓へ入れ直す。

## 自前シェーダーを書くときの罠

- **`ShaderMaterial` ではなく `RawShaderMaterial` を使う。** 前者は `position` / `uv` の宣言と
  フラグメントの出力変数を自動で足すので、自前のシェーダーと二重定義になってコンパイルが落ちる
  （症状は console の `'uv' : redefinition` と `no valid shader program in use`）
- **シェーダーのコンパイルエラーは console にしか出ない。** `npm run check`（build を含む）でも落ちない
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
