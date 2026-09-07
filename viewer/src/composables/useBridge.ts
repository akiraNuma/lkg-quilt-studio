import { onUnmounted, ref } from 'vue'
import { t } from '../i18n'
import type { Calibration } from '../lenticular'
import type { DisplayQuilt } from '../quilt'

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
 * Looking Glass Bridge との接続。実機のキャリブレーション値と、Bridge が
 * Looking Glass 用の窓を置いている画面座標を取るために使う。
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

  /**
   * 繋がっている Bridge から画面を取り直す。取得に失敗したら 1 度だけ繋ぎ直す。
   *
   * bridge.js の `connect()` は `isConnected` が立っていると orchestration を
   * 取り直さず、`getDisplays()` は保存済みの orchestration を送るだけ。だから
   * Bridge 側で orchestration が無効になると（Bridge の再起動、他のクライアントの
   * 接続）取得が失敗し続け、再検出を押しても永久に直らない
   */
  async function refresh(): Promise<void> {
    if (client === null) return
    if (await readDisplays()) return
    await client.disconnect()
    const again = await client.connect()
    if (!again.success) {
      displays.value = []
      status.value = 'unavailable'
      message.value = t('bridge.unavailable')
      return
    }
    status.value = 'connected'
    if (!(await readDisplays())) {
      displays.value = []
      message.value = t('bridge.unavailable')
    }
  }

  /**
   * 画面の一覧を取れたら true。**繋がっているのに 1 台も無い場合も true。**
   * 通信の失敗（繋ぎ直せば直る）と、実機が無いこと（繋ぎ直しても直らない）を分ける
   */
  async function readDisplays(): Promise<boolean> {
    if (client === null) return false
    const found = await client.getDisplays()
    if (!found.success || found.response === null) return false
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
    // 前回の失敗を残すと、繋がった後も警告が居座る
    message.value =
      displays.value.length === 0 ? t('bridge.notFound') : null
    return true
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
