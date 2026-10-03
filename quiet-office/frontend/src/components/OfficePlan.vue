<script setup lang="ts">
/**
 * Floor plan with the sound map. Before and after are stacked and split by a draggable divider.
 * The map is always the in-browser estimate; the desk numbers come from the results passed in.
 */
import { computed, onMounted, ref, watch } from 'vue'
import type { LayoutResult, Office, OptimizationParams } from '@/types'
import { EARSHOT_DB } from '@/types'
import { levelColor, paintField, segmentOf } from '@/physics/estimate'
import { boundsOf, polygonPath } from '@/physics/geometry'

const props = defineProps<{
  office: Office
  params: OptimizationParams
  before: LayoutResult
  after: LayoutResult
}>()

const U = 10 // drawing units per metre
const split = ref(50)
const beforeCanvas = ref<HTMLCanvasElement | null>(null)
const afterCanvas = ref<HTMLCanvasElement | null>(null)

// A little air round the room so the wall line is not cut off.
const view = computed(() => boundsOf(props.office.outline, 0.15))
const viewBox = computed(() => `${view.value.minX * U} ${view.value.minY * U} ${view.value.width * U} ${view.value.height * U}`)
const outlinePath = computed(() => polygonPath(props.office.outline, U))
const screens = computed(() =>
  props.after.slot_ids.map((id) => segmentOf(props.office.slots.find((s) => s.id === id)!, props.params.screen_length_m)),
)

function repaint(): void {
  if (beforeCanvas.value) paintField(beforeCanvas.value, props.office, [], props.params, view.value)
  if (afterCanvas.value) paintField(afterCanvas.value, props.office, props.after.slot_ids, props.params, view.value)
}
onMounted(repaint)
watch(() => [props.office, props.after.slot_ids.join(','), props.params.frequencies_hz.join(','), props.params.screen_length_m], repaint, { deep: true })
</script>

<template>
  <div class="plan" :style="{ aspectRatio: `${view.width} / ${view.height}` }">
    <div
      v-for="side in (['before', 'after'] as const)"
      :key="side"
      class="stack"
      :style="{ clipPath: side === 'before' ? `inset(0 ${100 - split}% 0 0)` : `inset(0 0 0 ${split}%)` }"
    >
      <canvas :ref="(el) => (side === 'before' ? (beforeCanvas = el as HTMLCanvasElement) : (afterCanvas = el as HTMLCanvasElement))" />
      <svg :viewBox="viewBox" aria-hidden="true">
        <g v-for="(desk, i) in office.desks" :key="i">
          <rect :x="desk.x * U - 6.5" :y="desk.y * U - 4.5" width="13" height="9" rx="1.6" fill="#fff" stroke="#17302b" stroke-width=".5" />
          <circle
            :cx="desk.x * U - 3.4"
            :cy="desk.y * U"
            r="1.5"
            :fill="levelColor((side === 'before' ? before : after).desk_levels_db[i] ?? 0)"
            stroke="#17302b"
            stroke-width=".4"
          />
          <text
            :x="desk.x * U + 1.9"
            :y="desk.y * U + 1.2"
            font-size="3.3"
            text-anchor="middle"
            fill="#17302b"
            :font-weight="((side === 'before' ? before : after).desk_levels_db[i] ?? 0) >= EARSHOT_DB ? 700 : 400"
          >
            {{ ((side === 'before' ? before : after).desk_levels_db[i] ?? 0).toFixed(0) }}
          </text>
        </g>

        <circle :cx="office.source.x * U" :cy="office.source.y * U" r="2.2" fill="#17302b" />
        <path
          v-for="r in [4.5, 7]"
          :key="r"
          :d="`M${office.source.x * U + r * 0.6} ${office.source.y * U - r * 0.8} A${r} ${r} 0 0 1 ${office.source.x * U + r * 0.6} ${office.source.y * U + r * 0.8}`"
          fill="none"
          stroke="#17302b"
          stroke-width=".7"
        />
        <text :x="office.source.x * U" :y="office.source.y * U + 11" font-size="3" text-anchor="middle" fill="#17302b">conversation</text>

        <g v-for="(g, i) in screens" :key="`s${i}`">
          <template v-if="side === 'after'">
            <line :x1="g.x1 * U" :y1="g.y1 * U" :x2="g.x2 * U" :y2="g.y2 * U" stroke="#17302b" stroke-width="2.4" stroke-linecap="round" />
            <line :x1="g.x1 * U" :y1="g.y1 * U" :x2="g.x2 * U" :y2="g.y2 * U" stroke="#d9a520" stroke-width=".9" stroke-linecap="round" />
          </template>
          <line v-else :x1="g.x1 * U" :y1="g.y1 * U" :x2="g.x2 * U" :y2="g.y2 * U" stroke="#17302b" stroke-width="1" stroke-dasharray="2 1.6" />
        </g>

        <path :d="outlinePath" fill="none" stroke="#17302b" stroke-width="1" stroke-linejoin="round" />
      </svg>
    </div>

    <div class="split" :style="{ left: `${split}%` }">
      <span>before</span><i></i><span>after</span>
    </div>
    <input v-model.number="split" class="split-input" type="range" min="0" max="100" aria-label="Slide to compare before and after" />
  </div>
</template>
