<script setup lang="ts">
// 再生 UI はこれから作る。今は quilt 動画を選ばせる入口だけ置く
import { ref } from 'vue'
import { parseQuiltLayout, type QuiltLayout } from './quilt'

const layout = ref<QuiltLayout | null>(null)
const filename = ref('')

function onSelect(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  filename.value = file.name
  layout.value = parseQuiltLayout(file.name)
}
</script>

<template>
  <main>
    <h1>lkg-quilt-studio viewer</h1>
    <input type="file" accept="video/*" @change="onSelect" />
    <p v-if="filename">{{ filename }}</p>
    <p v-if="layout">
      {{ layout.columns }} 列 × {{ layout.rows }} 行 / アスペクト
      {{ layout.aspect }}
    </p>
    <p v-else-if="filename">
      ファイル名から quilt のレイアウトを読めなかった
    </p>
  </main>
</template>
