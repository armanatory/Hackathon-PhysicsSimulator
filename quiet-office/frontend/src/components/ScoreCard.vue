<script setup lang="ts">
import { computed } from 'vue'
import type { LayoutResult } from '@/types'

const props = defineProps<{
  baseline: LayoutResult
  best: LayoutResult
  earshotBefore: number
  earshotAfter: number
}>()

const loudestBefore = computed(() => Math.max(...props.baseline.desk_levels_db))
const loudestAfter = computed(() => Math.max(...props.best.desk_levels_db))
</script>

<template>
  <div class="panel">
    <h2>Noise score at the desks</h2>
    <div class="score">
      <div><small>Before</small><span>100</span></div>
      <div class="arrow" aria-hidden="true">→</div>
      <div><small>After</small><span>{{ Math.round(best.score) }}</span></div>
    </div>
    <ul class="facts">
      <li>Desks in earshot <b>{{ earshotBefore }} → {{ earshotAfter }}</b></li>
      <li>Loudest desk <b>{{ loudestBefore.toFixed(0) }} → {{ loudestAfter.toFixed(0) }} dB</b></li>
    </ul>
  </div>
</template>
