<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { clampRound, parseNumber, trim } from '../format'
import { t } from '../i18n'

const props = defineProps<{
  label: string
  min: number
  max: number
  step: number
  /** Decimals a typed value is rounded to; the display drops trailing zeros */
  decimals?: number
  unit?: string
  disabled?: boolean
}>()

const value = defineModel<number>({ required: true })

const id = useId()
const digits = computed(() => props.decimals ?? 0)
const text = ref(format(value.value))
const invalid = ref(false)

// A dragged value also shows in the field; two different numbers would leave neither credible
watch(value, current => {
  invalid.value = false
  text.value = format(current)
})

/** Accept only a committed field value; writing back mid-typing makes digits impossible to erase */
function commit(): void {
  const parsed = parseNumber(text.value)
  if (parsed === null) {
    invalid.value = true
    return
  }
  invalid.value = false
  // Clamp to the slider range. Letting only the field leave it would make the picture and the
  // slider position disagree
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
  <!-- Keep a single root. Several roots become direct children of the parent grid and shift the
       columns -->
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
  /* Fixed column widths: each row is its own grid, so auto would give every row a different width */
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
