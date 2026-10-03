<script setup lang="ts">
/**
 * The result on the floor plan: where each panel goes, measured from the walls, and the level in
 * each quiet zone before and after. Every number comes from the results passed in.
 */
import { computed } from 'vue'
import type { LayoutResult, Office, OptimizationParams } from '@/types'
import { segmentOf } from '@/physics/estimate'
import { boundsOf, polygonPath, wallDistances } from '@/physics/geometry'

const props = defineProps<{
  office: Office
  params: OptimizationParams
  before: LayoutResult
  after: LayoutResult
}>()

const U = 10 // drawing units per metre

// A little air round the room so the wall line is not cut off.
const view = computed(() => boundsOf(props.office.outline, 0.3))
const viewBox = computed(() => `${view.value.minX * U} ${view.value.minY * U} ${view.value.width * U} ${view.value.height * U}`)
const outlinePath = computed(() => polygonPath(props.office.outline, U))

const panels = computed(() =>
  props.after.slot_ids.map((id, i) => {
    const slot = props.office.slots.find((s) => s.id === id)!
    const d = wallDistances(slot, props.office.outline)
    // One measure across and one down, each to the nearer wall.
    const across = d.left <= d.right ? -d.left : d.right
    const down = d.top <= d.bottom ? -d.top : d.bottom
    return { number: i + 1, slot, line: segmentOf(slot, props.params.screen_length_m), across, down }
  }),
)
</script>

<template>
  <svg class="resultplan" :viewBox="viewBox" role="img" aria-label="Floor plan with the panels in place">
    <path :d="outlinePath" class="room" />

    <g v-for="(zone, i) in office.quiet_zones" :key="`z${i}`">
      <rect class="zone" :x="zone.x * U" :y="zone.y * U" :width="zone.width * U" :height="zone.height * U" rx="1.5" />
      <text :x="zone.x * U + 1.6" :y="zone.y * U + 4.4" class="small">{{ zone.label || 'Quiet zone' }}</text>
      <text :x="zone.x * U + 1.6" :y="zone.y * U + 10" class="level">
        {{ (before.zone_levels_db[i] ?? 0).toFixed(0) }} → {{ (after.zone_levels_db[i] ?? 0).toFixed(0) }} dB
      </text>
    </g>

    <g v-for="(desk, i) in office.desks" :key="`d${i}`">
      <rect class="desk" :x="desk.x * U - 6.5" :y="desk.y * U - 4.5" width="13" height="9" rx="1.6" />
      <text :x="desk.x * U" :y="desk.y * U + 1.2" class="small" text-anchor="middle">{{ (after.desk_levels_db[i] ?? 0).toFixed(0) }}</text>
    </g>

    <g v-for="(source, i) in office.sources" :key="`n${i}`">
      <circle :cx="source.x * U" :cy="source.y * U" r="6" class="halo" />
      <circle :cx="source.x * U" :cy="source.y * U" r="2.2" class="ink" />
      <text :x="source.x * U" :y="source.y * U + 10.5" class="small" text-anchor="middle">{{ source.label || 'Noise' }}</text>
    </g>

    <g v-for="p in panels" :key="p.number">
      <line class="measure" :x1="p.slot.x * U" :y1="p.slot.y * U" :x2="(p.slot.x + p.across) * U" :y2="p.slot.y * U" />
      <text class="dim" :x="(p.slot.x + p.across / 2) * U" :y="p.slot.y * U - 1.2" text-anchor="middle">{{ Math.abs(p.across).toFixed(1) }} m</text>
      <line class="measure" :x1="p.slot.x * U" :y1="p.slot.y * U" :x2="p.slot.x * U" :y2="(p.slot.y + p.down) * U" />
      <text class="dim" :x="p.slot.x * U + 1.2" :y="(p.slot.y + p.down / 2) * U">{{ Math.abs(p.down).toFixed(1) }} m</text>
    </g>
    <g v-for="p in panels" :key="`p${p.number}`">
      <line class="panelline" :x1="p.line.x1 * U" :y1="p.line.y1 * U" :x2="p.line.x2 * U" :y2="p.line.y2 * U" />
      <circle :cx="p.slot.x * U" :cy="p.slot.y * U" r="3.4" class="badge" />
      <text :x="p.slot.x * U" :y="p.slot.y * U + 1.4" class="badgetext" text-anchor="middle">{{ p.number }}</text>
    </g>
  </svg>
</template>
