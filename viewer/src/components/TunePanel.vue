<script setup lang="ts">
import { computed } from 'vue'
import ValueSlider from './ValueSlider.vue'
import { t } from '../i18n'
import type { ViewMode } from '../lenticular'

const props = defineProps<{
  /** Not adjustable until a source exists */
  disabled: boolean
  mode: ViewMode
  /** The displayed quilt's view count minus one */
  maxView: number
  fisheye: boolean
  lastFrame: number
  /** The automatically chosen convergence, used to break down the baked value */
  baseConvergence: number | null
}>()

const shift = defineModel<number>('shift', { required: true })
const singleView = defineModel<number>('singleView', {
  required: true,
})
const span = defineModel<number>('span', { required: true })
const fov = defineModel<number>('fov', { required: true })
const frameIndex = defineModel<number>('frameIndex', {
  required: true,
})

/** The convergence that goes into the video, **shown as a breakdown** (the number alone does
 * not explain itself)
 */
const baked = computed(() => {
  const base = props.baseConvergence
  if (base === null) return null
  return t('tune.baked', {
    total: (base + shift.value).toFixed(2),
    base: base.toFixed(2),
    shift: shift.value.toFixed(2),
  })
})
</script>

<template>
  <section class="panel">
    <h2><span class="step">3</span>{{ t('tune.title') }}</h2>

    <ValueSlider
      v-if="mode === 'single'"
      v-model="singleView"
      :label="t('tune.view')"
      :min="0"
      :max="maxView"
      :step="1"
      :disabled="disabled"
    />

    <ValueSlider
      v-model="shift"
      :label="t('tune.convergence')"
      :min="-24"
      :max="24"
      :step="0.5"
      :decimals="2"
      unit="px"
      :disabled="disabled"
    />
    <p class="note">{{ t('tune.convergenceHint') }}</p>
    <p v-if="baked" class="note">{{ baked }}</p>

    <p class="caption">{{ t('tune.redraw') }}</p>

    <!--
      The ceiling is set by hole-filling quality, which no calculation decides. It is opened to
      2.5x extrapolation so it can be tuned on hardware (1.0 spans the two cameras; beyond that
      extrapolates)
    -->
    <ValueSlider
      v-model="span"
      :label="t('tune.span')"
      :min="0.4"
      :max="6"
      :step="0.1"
      :decimals="2"
      :disabled="disabled"
    />
    <ValueSlider
      v-if="fisheye"
      v-model="fov"
      :label="t('tune.fov')"
      :min="20"
      :max="120"
      :step="5"
      unit="°"
      :disabled="disabled"
    />
    <ValueSlider
      v-model="frameIndex"
      :label="t('tune.frame')"
      :min="0"
      :max="lastFrame"
      :step="1"
      :disabled="disabled"
    />
    <p class="note">{{ t('tune.spanNote') }}</p>
  </section>
</template>

<style scoped>
.caption {
  color: var(--muted);
  font-size: 0.75rem;
  margin: 0.2rem 0 0;
  padding-top: 0.55rem;
  border-top: 1px solid var(--line);
}
</style>
