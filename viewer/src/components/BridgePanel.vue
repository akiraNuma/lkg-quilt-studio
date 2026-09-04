<script setup lang="ts">
import type {
  BridgeDisplay,
  BridgeStatus,
} from '../composables/useBridge'

defineProps<{
  status: BridgeStatus
  message: string | null
  displays: BridgeDisplay[]
  selected: number
  castUri: string | null
}>()

defineEmits<{
  connect: []
  refresh: []
  disconnect: []
  select: [index: number]
  cast: []
}>()

const STATUS_LABEL: Record<BridgeStatus, string> = {
  idle: '未接続',
  connecting: '接続中',
  connected: '接続済み',
  unavailable: '接続できない',
}
</script>

<template>
  <section>
    <h2>Looking Glass Bridge</h2>
    <p class="row">
      <span>{{ STATUS_LABEL[status] }}</span>
      <button
        v-if="status !== 'connected'"
        :disabled="status === 'connecting'"
        @click="$emit('connect')"
      >
        接続する
      </button>
      <template v-else>
        <button @click="$emit('refresh')">再検出</button>
        <button @click="$emit('disconnect')">切断</button>
      </template>
    </p>
    <p v-if="message" class="message">{{ message }}</p>

    <ul v-if="displays.length" class="displays">
      <li v-for="display in displays" :key="display.index">
        <label>
          <input
            type="radio"
            name="display"
            :value="display.index"
            :checked="display.index === selected"
            @change="$emit('select', display.index)"
          />
          {{ display.serial }}
          <span v-if="display.quilt">
            / quilt {{ display.quilt.columns }}x{{
              display.quilt.rows
            }}
          </span>
          <span v-if="display.calibration">
            / {{ display.calibration.screenW }}x{{
              display.calibration.screenH
            }}
          </span>
        </label>
      </li>
    </ul>

    <h3>Bridge の再生窓に渡す</h3>
    <p class="note">
      Bridge は別プロセスなので、http(s) の URL
      かローカルのファイルパスで 指定した quilt
      だけを読める。ブラウザで選んだファイルは渡せない
    </p>
    <button
      :disabled="status !== 'connected' || castUri === null"
      @click="$emit('cast')"
    >
      cast する
    </button>
  </section>
</template>

<style scoped>
.row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.message {
  color: #b26500;
}

.note {
  color: #546e7a;
  font-size: 0.85rem;
}

.displays {
  list-style: none;
  padding: 0;
}
</style>
