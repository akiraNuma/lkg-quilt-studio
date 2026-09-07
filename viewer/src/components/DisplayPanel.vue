<script setup lang="ts">
import type {
  BridgeDisplay,
  BridgeStatus,
} from '../composables/useBridge'
import { t, type MessageKey } from '../i18n'

defineProps<{
  status: BridgeStatus
  message: string | null
  displays: BridgeDisplay[]
  castUri: string | null
}>()

defineEmits<{
  connect: []
  refresh: []
  disconnect: []
  cast: []
}>()

const selected = defineModel<number>('selected', { required: true })

const STATE_KEY: Record<BridgeStatus, MessageKey> = {
  idle: 'display.state.idle',
  connecting: 'display.state.connecting',
  connected: 'display.state.connected',
  unavailable: 'display.state.unavailable',
}
</script>

<template>
  <section class="panel">
    <h2>
      <span class="step">1</span>{{ t('display.title') }}
      <span class="state" :class="status">
        {{ t(STATE_KEY[status]) }}
      </span>
    </h2>

    <p class="row">
      <button
        v-if="status !== 'connected'"
        class="primary"
        :disabled="status === 'connecting'"
        @click="$emit('connect')"
      >
        {{ t('display.connect') }}
      </button>
      <template v-else>
        <button @click="$emit('refresh')">
          {{ t('display.refresh') }}
        </button>
        <button @click="$emit('disconnect')">
          {{ t('display.disconnect') }}
        </button>
      </template>
    </p>

    <p v-if="status !== 'connected'" class="note">
      {{ t('display.hint') }}
    </p>
    <p v-if="message" class="warn">{{ message }}</p>

    <ul v-if="displays.length" class="displays">
      <li v-for="display in displays" :key="display.index">
        <label>
          <input
            v-model="selected"
            type="radio"
            name="display"
            :value="display.index"
          />
          <span>
            {{ display.serial }}
            <span v-if="display.quilt" class="note">
              quilt {{ display.quilt.columns }}x{{
                display.quilt.rows
              }}
              <template v-if="display.calibration">
                / {{ display.calibration.screenW }}x{{
                  display.calibration.screenH
                }}
              </template>
            </span>
          </span>
        </label>
      </li>
    </ul>

    <p v-if="status === 'connected'" class="row">
      <button :disabled="castUri === null" @click="$emit('cast')">
        {{ t('display.cast') }}
      </button>
      <span v-if="castUri === null" class="note">
        {{ t('display.castHint') }}
      </span>
    </p>
  </section>
</template>

<style scoped>
.state {
  margin-left: auto;
  font-size: 0.75rem;
  font-weight: normal;
  color: var(--muted);
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  padding: 0 0.5rem;
}

.state.connected {
  color: var(--ok);
  border-color: var(--ok);
}

.state.unavailable {
  color: var(--warn);
  border-color: var(--warn);
}

.displays {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.displays label {
  align-items: baseline;
}
</style>
