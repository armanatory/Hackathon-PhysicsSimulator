<script setup lang="ts">
import { computed } from 'vue'
import type { LayoutResult, QuietZone } from '@/types'

const props = defineProps<{
  baseline: LayoutResult
  best: LayoutResult
  zones: QuietZone[]
}>()

// The headline is the level where it should be quiet: the zones, or the desks of an office without zones.
const before = computed(() => (props.zones.length ? props.baseline.zone_levels_db : props.baseline.desk_levels_db))
const after = computed(() => (props.zones.length ? props.best.zone_levels_db : props.best.desk_levels_db))
const mean = (levels: number[]) => levels.reduce((sum, l) => sum + l, 0) / (levels.length || 1)
const change = computed(() => mean(after.value) - mean(before.value))
</script>

<template>
  <div class="panel">
    <h2>{{ zones.length ? 'Level in the quiet zones' : 'Level at the desks' }}</h2>
    <div class="score">
      <div><small>Before</small><span>{{ mean(before).toFixed(0) }}</span></div>
      <div class="arrow" aria-hidden="true">→</div>
      <div><small>After</small><span>{{ mean(after).toFixed(0) }} <em>dB</em></span></div>
    </div>
    <p class="hint">{{ change <= 0 ? `${Math.abs(change).toFixed(1)} dB quieter` : `${change.toFixed(1)} dB louder` }} on average, simulated on Allsolve.</p>
    <ul v-if="zones.length > 1" class="facts">
      <li v-for="(zone, i) in zones" :key="i">
        {{ zone.label || 'Quiet zone' }}
        <b>{{ (baseline.zone_levels_db[i] ?? 0).toFixed(0) }} → {{ (best.zone_levels_db[i] ?? 0).toFixed(0) }} dB</b>
      </li>
    </ul>
  </div>
</template>
