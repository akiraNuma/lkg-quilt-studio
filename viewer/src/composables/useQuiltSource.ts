import { onUnmounted, ref } from 'vue'
import { t } from '../i18n'
import { parseQuiltLayout, type QuiltLayout } from '../quilt'

export type QuiltSource = {
  name: string
  /** Video or still image. A preview is a single frame, so it arrives as an image */
  kind: 'video' | 'image'
  /** The location handed to <video> or <img> */
  url: string
  /** Which frame a single-frame preview shows, or null for a video */
  frameIndex: number | null
  layout: QuiltLayout
}

/** Owns the selected quilt video and the cleanup of its object URL. */
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
      error.value = t('quilt.naming')
      return
    }
    releaseObjectUrl()
    objectUrl = URL.createObjectURL(file)
    error.value = null
    source.value = {
      name: file.name,
      kind: 'video',
      url: objectUrl,
      frameIndex: null,
      layout,
    }
  }

  function fromUri(uri: string): void {
    const trimmed = uri.trim()
    const layout = parseQuiltLayout(trimmed)
    if (trimmed === '' || layout === null) {
      error.value = t('quilt.naming')
      return
    }
    releaseObjectUrl()
    error.value = null
    source.value = {
      name: trimmed.split(/[/\\]/).pop() ?? trimmed,
      kind: 'video',
      url: trimmed,
      frameIndex: null,
      layout,
    }
  }

  /**
   * Open a quilt converted from a single frame. The layout cannot be read from a filename, so
   * the caller passes it. Cleanup of the object URL stays here
   */
  function fromImage(
    blob: Blob,
    name: string,
    frameIndex: number,
    layout: QuiltLayout
  ): void {
    releaseObjectUrl()
    objectUrl = URL.createObjectURL(blob)
    error.value = null
    source.value = {
      name,
      kind: 'image',
      url: objectUrl,
      frameIndex,
      layout,
    }
  }

  onUnmounted(clear)

  return { source, error, fromFile, fromUri, fromImage, clear }
}
