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
  /** The screen coordinates where Bridge places its window for the Looking Glass */
  windowCoords: { x: number; y: number } | null
}

type BridgeModule = typeof import('@lookingglass/bridge')
type BridgeClient = ReturnType<
  BridgeModule['BridgeClient']['getInstance']
>

/**
 * The connection to Looking Glass Bridge, used to read the hardware's calibration values and the
 * screen coordinates where Bridge places its window for the Looking Glass.
 */
export function useBridge() {
  const status = ref<BridgeStatus>('idle')
  const message = ref<string | null>(null)
  const displays = ref<BridgeDisplay[]>([])
  let bridge: BridgeModule | null = null
  let client: BridgeClient | null = null

  async function load(): Promise<BridgeClient> {
    // The library touches navigator and WebSocket, so load it only when it is used
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
   * Re-read the displays from a connected Bridge, reconnecting once if the read fails.
   *
   * bridge.js's `connect()` does not renew the orchestration while `isConnected` is set, and
   * `getDisplays()` merely sends the stored one. So once Bridge invalidates the orchestration
   * (a Bridge restart, another client connecting), the read keeps failing and rescanning never
   * recovers
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
   * True when the display list was read, **including when the connection works but no device is
   * present**. This separates a failed exchange (which reconnecting fixes) from absent hardware
   * (which it does not)
   */
  async function readDisplays(): Promise<boolean> {
    if (client === null) return false
    const found = await client.getDisplays()
    if (!found.success || found.response === null) return false
    displays.value = found.response.map((display, order) => ({
      // The bundled .d.ts declares index / windowCoords as BridgeValue, but the implementation
      // (tryParseDisplay) unwraps every field before returning. An upstream typing bug
      index: asNumber(display.index) ?? order,
      serial:
        display.calibration?.serial ?? t('bridge.unknownSerial'),
      calibration: display.calibration,
      quilt: display.defaultQuilt,
      windowCoords: asPoint(display.windowCoords),
    }))
    // Leaving the previous failure in place keeps a warning around after it connects
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

  // Always disconnect when leaving the screen, so no WebSocket is left open
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
