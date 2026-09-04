import { onUnmounted, ref } from 'vue'
import { parseQuiltLayout, type QuiltLayout } from '../quilt'

export type QuiltSource = {
  name: string
  /** 動画か静止画か。プレビューは 1 フレームなので静止画で来る */
  kind: 'video' | 'image'
  /** <video> か <img> に渡す場所 */
  url: string
  layout: QuiltLayout
  /**
   * Bridge に cast できる場所にあるか。Bridge は別プロセスなので、
   * ブラウザ内だけで有効な blob: URL は取りに行けない
   */
  castUri: string | null
}

const NAMING_HINT =
  'ファイル名が quilt の規約（例: sample_qs5x9a1.777.mp4）になっていない。' +
  'converter が付ける名前のまま渡す'

/** quilt 動画の選択と、それに紐づく object URL の後片付けを持つ。 */
export function useQuiltSource() {
  const source = ref<QuiltSource | null>(null)
  const error = ref<string | null>(null)
  let objectUrl: string | null = null

  function releaseObjectUrl(): void {
    if (objectUrl === null) return
    URL.revokeObjectURL(objectUrl)
    objectUrl = null
  }

  function clear(): void {
    releaseObjectUrl()
    source.value = null
    error.value = null
  }

  function fromFile(file: File): void {
    const layout = parseQuiltLayout(file.name)
    if (layout === null) {
      error.value = NAMING_HINT
      return
    }
    releaseObjectUrl()
    objectUrl = URL.createObjectURL(file)
    error.value = null
    source.value = {
      name: file.name,
      kind: 'video',
      url: objectUrl,
      layout,
      castUri: null,
    }
  }

  function fromUri(uri: string): void {
    const trimmed = uri.trim()
    const layout = parseQuiltLayout(trimmed)
    if (trimmed === '' || layout === null) {
      error.value = NAMING_HINT
      return
    }
    releaseObjectUrl()
    error.value = null
    source.value = {
      name: trimmed.split(/[/\\]/).pop() ?? trimmed,
      kind: 'video',
      url: trimmed,
      layout,
      castUri: trimmed,
    }
  }

  /**
   * 1 フレームだけ変換した quilt を開く。レイアウトはファイル名から読めないので
   * 呼び出し側が渡す。object URL の後片付けはここが持つ
   */
  function fromImage(
    blob: Blob,
    name: string,
    layout: QuiltLayout
  ): void {
    releaseObjectUrl()
    objectUrl = URL.createObjectURL(blob)
    error.value = null
    source.value = {
      name,
      kind: 'image',
      url: objectUrl,
      layout,
      castUri: null,
    }
  }

  onUnmounted(clear)

  return { source, error, fromFile, fromUri, fromImage, clear }
}
