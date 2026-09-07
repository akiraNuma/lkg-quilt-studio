import { onUnmounted, ref } from 'vue'
import { t } from '../i18n'
import type { Calibration } from '../lenticular'
import {
  viewCount,
  type DisplayQuilt,
  type QuiltLayout,
} from '../quilt'

export type BridgeStatus =
  'idle' | 'connecting' | 'connected' | 'unavailable'

export type BridgeDisplay = {
  index: number
  serial: string
  calibration: Calibration | null
  quilt: DisplayQuilt | null
  /** Bridge が Looking Glass 用の窓を置いている画面座標 */
  windowCoords: { x: number; y: number } | null
}

type BridgeModule = typeof import('@lookingglass/bridge')
type BridgeClient = ReturnType<
  BridgeModule['BridgeClient']['getInstance']
>

/**
 * Looking Glass Bridge との接続。キャリブレーション値の取得と、
 * quilt を Bridge の再生窓へ cast する経路の両方をここに集める。
 */
export function useBridge() {
  const status = ref<BridgeStatus>('idle')
  const message = ref<string | null>(null)
  const displays = ref<BridgeDisplay[]>([])
  let bridge: BridgeModule | null = null
  let client: BridgeClient | null = null

  async function load(): Promise<BridgeClient> {
    // navigator や WebSocket を触るライブラリなので、使うときだけ読み込む
    bridge ??= await import('@lookingglass/bridge')
    client ??= bridge.BridgeClient.getInstance()
    return client
  }

  async function connect(): Promise<void> {
    if (
      status.value === 'connecting' ||
      status.value === 'connected'
    ) {
      return
    }
    status.value = 'connecting'
    message.value = null
    try {
      const instance = await load()
      const connected = await instance.connect()
      if (!connected.success) {
        status.value = 'unavailable'
        message.value = t('bridge.unavailable')
        return
      }
      status.value = 'connected'
      await refresh()
    } catch (failure) {
      status.value = 'unavailable'
      message.value = t('bridge.loadFailed', {
        error: describe(failure),
      })
    }
  }

  async function refresh(): Promise<void> {
    if (client === null) return
    const found = await client.getDisplays()
    if (!found.success || found.response === null) {
      displays.value = []
      message.value = t('bridge.notFound')
      return
    }
    displays.value = found.response.map((display, order) => ({
      // 同梱の .d.ts は index / windowCoords を BridgeValue と宣言しているが、
      // 実装（tryParseDisplay）は全フィールドを unwrap して返す。上流の型バグ
      index: asNumber(display.index) ?? order,
      serial:
        display.calibration?.serial ?? t('bridge.unknownSerial'),
      calibration: display.calibration,
      quilt: display.defaultQuilt,
      windowCoords: asPoint(display.windowCoords),
    }))
    if (displays.value.length === 0) {
      message.value = t('bridge.notFound')
    }
  }

  /** quilt を Bridge の再生窓に渡す。uri は http(s) かローカルのファイルパス。 */
  async function cast(
    uri: string,
    layout: QuiltLayout
  ): Promise<boolean> {
    if (client === null || bridge === null) {
      message.value = t('bridge.needConnect')
      return false
    }
    const hologram = new bridge.QuiltHologram({
      uri,
      settings: {
        columns: layout.columns,
        rows: layout.rows,
        aspect: layout.aspect,
        viewCount: viewCount(layout),
      },
    })
    const result = await client.cast(hologram)
    message.value = result.success
      ? t('bridge.castOk', { uri })
      : t('bridge.castFailed', { uri })
    return result.success
  }

  async function disconnect(): Promise<void> {
    if (client === null) return
    await client.disconnect()
    status.value = 'idle'
    displays.value = []
    message.value = null
  }

  // WebSocket を開いたままにしないよう、画面を離れるときに必ず切る
  onUnmounted(() => void disconnect())

  return {
    status,
    message,
    displays,
    connect,
    refresh,
    cast,
    disconnect,
  }
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' ? value : null
}

function asPoint(value: unknown): { x: number; y: number } | null {
  if (value === null || typeof value !== 'object') return null
  const point = value as { x?: unknown; y?: unknown }
  return typeof point.x === 'number' && typeof point.y === 'number'
    ? { x: point.x, y: point.y }
    : null
}

function describe(failure: unknown): string {
  return failure instanceof Error ? failure.message : String(failure)
}
