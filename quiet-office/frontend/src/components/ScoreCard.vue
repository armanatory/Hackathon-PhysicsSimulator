<script setup lang="ts">
import { computed } from 'vue'
import type { LayoutResult, QuietZone } from '@/types'

const props = defineProps<{
  baseline: LayoutResult
  best: LayoutResult
  zones: QuietZone[]
  earshotBefore: number
  earshotAfter: number
}>()

const hasDesks = computed(() => props.baseline.desk_levels_db.length > 0)
const loudestBefore = computed(() => Math.max(...props.baseline.desk_levels_db))
const loudestAfter = computed(() => Math.max(...props.best.desk_levels_db))
</script>

<template>
  <div class="panel">
    <h2>Noise score where it should be quiet</h2>
    <div class="score">
      <div><small>Before</small><span>100</span></div>
      <div class="arrow" aria-hidden="true">→</div>
      <div><small>After</small><span>{{ Math.round(best.score) }}</span></div>
    </div>
    <ul class="facts">
      <li v-for="(zone, i) in zones" :key="i">
        {{ zone.label || 'Quiet zone' }}
        <b>{{ (baseline.zone_levels_db[i] ?? 0).toFixed(0) }} → {{ (best.zone_levels_db[i] ?? 0).toFixed(0) }} dB</b>
      </li>
      <template v-if="hasDesks">
        <li>Desks in earshot <b>{{ earshotBefore }} → {{ earshotAfter }}</b></li>
        <li>Loudest desk <b>{{ loudestBefore.toFixed(0) }} → {{ loudestAfter.toFixed(0) }} dB</b></li>
      </template>
    </ul>
  </div>
</template>
