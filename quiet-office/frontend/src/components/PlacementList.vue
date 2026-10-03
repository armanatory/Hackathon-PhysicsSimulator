<script setup lang="ts">
import { computed } from 'vue'
import type { LayoutResult, Office } from '@/types'
import { wallDistances } from '@/physics/geometry'

const props = defineProps<{
  office: Office
  best: LayoutResult
  screenLength: number
}>()

// Each panel's centre, measured from the nearer wall across and the nearer wall down the plan.
const placed = computed(() =>
  props.best.slot_ids.map((id, i) => {
    const slot = props.office.slots.find((s) => s.id === id)!
    const d = wallDistances(slot, props.office.outline)
    const across = d.left <= d.right ? `${d.left.toFixed(1)} m from the left wall` : `${d.right.toFixed(1)} m from the right wall`
    const down = d.top <= d.bottom ? `${d.top.toFixed(1)} m from the top wall` : `${d.bottom.toFixed(1)} m from the bottom wall`
    return { number: i + 1, where: `${across}, ${down}`, runs: slot.orientation === 'v' ? 'top to bottom' : 'left to right' }
  }),
)
</script>

<template>
  <div class="panel">
    <h2>Where they go</h2>
    <ol class="where">
      <li v-for="p in placed" :key="p.number">
        <b>{{ p.number }}</b>
        <span>
          Centre {{ p.where }}
          <small>{{ screenLength }} m panel, running {{ p.runs }} on the plan</small>
        </span>
      </li>
    </ol>
  </div>
</template>
