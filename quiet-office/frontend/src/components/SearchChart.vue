<script setup lang="ts">
/** Every tested layout as a dot, with the best score found so far as a line. */
import { computed } from 'vue'
import type { LayoutResult } from '@/types'

const props = defineProps<{
  layouts: LayoutResult[]
  nScreens: number
}>()

const W = 720, H = 260
const M = { l: 40, r: 14, t: 12, b: 30 }

const tested = computed(() => props.layouts.filter((l) => l.slot_ids.length > 0))
const lo = computed(() => Math.max(0, Math.floor((Math.min(100, ...tested.value.map((l) => l.score)) - 10) / 20) * 20))
const ticks = computed(() => {
  const out: number[] = []
  for (let s = lo.value; s <= 100; s += 20) out.push(s)
  return out
})

function x(i: number): number {
  const n = Math.max(tested.value.length - 1, 1)
  return M.l + (i / n) * (W - M.l - M.r)
}
function y(score: number): number {
  return H - M.b - ((Math.min(score, 105) - lo.value) / (105 - lo.value)) * (H - M.t - M.b)
}

const bestLine = computed(() => {
  let best = Infinity, d = ''
  tested.value.forEach((l, i) => {
    if (l.score < best) {
      best = l.score
      d += (d ? `H${x(i).toFixed(1)}V` : `M${x(i).toFixed(1)} `) + y(l.score).toFixed(1)
    }
  })
  return d && tested.value.length ? `${d}H${x(tested.value.length - 1).toFixed(1)}` : ''
})
const bestIndex = computed(() => {
  let best = Infinity, index = -1
  tested.value.forEach((l, i) => {
    if (l.slot_ids.length === props.nScreens && l.score < best) {
      best = l.score
      index = i
    }
  })
  return index
})
</script>

<template>
  <svg :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="Noise score of every tested layout, with the best so far">
    <g v-for="s in ticks" :key="s">
      <line :x1="M.l" :x2="W - M.r" :y1="y(s)" :y2="y(s)" stroke="#cbd3c8" :stroke-dasharray="s === 100 ? '4 4' : undefined" />
      <text :x="M.l - 8" :y="y(s) + 4" font-size="12" text-anchor="end" fill="#5a6d67">{{ s }}</text>
    </g>
    <text :x="M.l" :y="H - 8" font-size="12" fill="#5a6d67">layout 1</text>
    <text :x="W - M.r" :y="H - 8" font-size="12" text-anchor="end" fill="#5a6d67">layout {{ tested.length }}</text>
    <circle v-for="(l, i) in tested" :key="i" :cx="x(i)" :cy="y(l.score)" r="3" fill="#17302b" fill-opacity=".3" />
    <path v-if="bestLine" :d="bestLine" fill="none" stroke="#2a7a5f" stroke-width="2.5" />
    <circle v-if="bestIndex >= 0" :cx="x(bestIndex)" :cy="y(tested[bestIndex].score)" r="6" fill="#2a7a5f" stroke="#f8f9f5" stroke-width="2" />
  </svg>
</template>
