<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { clampRound, parseNumber, trim } from '../format'
import { t } from '../i18n'

const props = defineProps<{
  label: string
  min: number
  max: number
  step: number
  /** 欄に入れた値を丸める桁数。表示は末尾の 0 を落とす */
  decimals?: number
  unit?: string
  disabled?: boolean
}>()

const value = defineModel<number>({ required: true })

const id = useId()
const digits = computed(() => props.decimals ?? 0)
const text = ref(format(value.value))
const invalid = ref(false)

// つまんで動かした値は欄にも出す。2 か所に違う数が見えるとどちらが本物か分からない
watch(value, current => {
  invalid.value = false
  text.value = format(current)
})

/** 欄で確定したときだけ受ける。打っている途中に書き戻すと桁を消せない */
function commit(): void {
  const parsed = parseNumber(text.value)
  if (parsed === null) {
    invalid.value = true
    return
  }
  invalid.value = false
  // スライダーの範囲へ丸める。欄だけ範囲外に出せると、絵とスライダーの位置が食い違う
  const rounded = clampRound(
    parsed,
    props.min,
    props.max,
    digits.value
  )
  text.value = format(rounded)
  value.value = rounded
}

function format(current: number): string {
  return trim(current, digits.value)
}
</script>

<template>
  <!-- ルートは 1 つにする。複数だと親のグリッドの直下に並んで列がずれる -->
  <div>
    <div class="slider">
      <label :for="id">{{ label }}</label>
      <input
        :id="id"
        v-model.number="value"
        type="range"
        :min="min"
        :max="max"
        :step="step"
        :disabled="disabled"
      />
      <span class="field">
        <input
          v-model="text"
          type="text"
          inputmode="decimal"
          :class="{ bad: invalid }"
          :disabled="disabled"
          @change="commit"
          @blur="commit"
        />
        <span v-if="unit" class="unit">{{ unit }}</span>
      </span>
    </div>
    <p v-if="invalid" class="error">
      {{ t('tune.range', { min, max }) }}
    </p>
  </div>
</template>

<style scoped>
.slider {
  display: grid;
  /* 列幅は固定にする。各行が別のグリッドなので、auto にすると行ごとに幅がずれる */
  grid-template-columns: 6.2rem 1fr 4.8rem;
  align-items: center;
  gap: 0.5rem;
}

label {
  font-size: 0.85rem;
}

input[type='range'] {
  width: 100%;
  min-width: 0;
}

.field {
  display: inline-flex;
  align-items: baseline;
  gap: 0.15rem;
  font-size: 0.85rem;
  min-width: 0;
}

.field input {
  width: 100%;
  min-width: 0;
  padding: 0.1rem 0.35rem;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.bad {
  border-color: var(--danger);
}

.unit {
  color: var(--muted);
}
</style>
