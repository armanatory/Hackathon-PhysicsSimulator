<script setup lang="ts">
/**
 * Floor-plan editor: drag room corners, desks, the conversation and the places a screen may
 * stand. A phone scan (.glb) can be opened as a to-scale underlay and traced into a room.
 */
import { computed, ref } from 'vue'
import type { Point } from '@/types'
import { useOptimizationStore } from '@/stores/optimizationStore'
import type { Selection } from '@/stores/optimizationStore'
import { boundsOf, pointInPolygon, polygonPath, snap } from '@/physics/geometry'
import type { Bounds } from '@/physics/geometry'
import { segmentOf } from '@/physics/estimate'

const store = useOptimizationStore()
const U = 10 // drawing units per metre
const CLOSE_DISTANCE_M = 0.4

const svg = ref<SVGSVGElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const tracing = ref(false)
const trace = ref<Point[]>([])
const hover = ref<Point | null>(null)

// While dragging, the view is frozen so the plan does not slide under the pointer.
let dragOffset: Point | null = null
const frozenView = ref<Bounds | null>(null)

const liveView = computed<Bounds>(() => {
  const points: Point[] = [...store.office.outline, ...trace.value]
  const placement = store.scanPlacement
  if (placement) points.push({ x: 0, y: 0 }, { x: placement.width, y: placement.height })
  return boundsOf(points, 1)
})
const view = computed(() => frozenView.value ?? liveView.value)
const viewBox = computed(() => `${view.value.minX * U} ${view.value.minY * U} ${view.value.width * U} ${view.value.height * U}`)

const outlinePath = computed(() => polygonPath(store.office.outline, U))
const walls = computed(() =>
  store.office.outline.map((a, i) => {
    const b = store.office.outline[(i + 1) % store.office.outline.length]
    const length = Math.hypot(b.x - a.x, b.y - a.y) || 1
    // The length label sits beside the wall, not on top of the add-corner dot.
    const ox = (-(b.y - a.y) / length) * 8, oy = ((b.x - a.x) / length) * 5 + 0.9
    return { index: i, mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2, length: Math.hypot(b.x - a.x, b.y - a.y), ox, oy }
  }),
)
const slotLines = computed(() => store.office.slots.map((slot) => segmentOf(slot, store.screenLength)))
const scanPath = computed(() => {
  const s = store.scanSegments
  if (!s) return ''
  let d = ''
  for (let i = 0; i < s.length; i += 4) d += `M${(s[i] * U).toFixed(1)} ${(s[i + 1] * U).toFixed(1)}L${(s[i + 2] * U).toFixed(1)} ${(s[i + 3] * U).toFixed(1)}`
  return d
})
const tracePath = computed(() => {
  const points = hover.value && tracing.value ? [...trace.value, hover.value] : trace.value
  return points.map((p, i) => `${i ? 'L' : 'M'}${p.x * U} ${p.y * U}`).join('')
})
const roomSize = computed(() => {
  const b = boundsOf(store.office.outline)
  return `${b.width.toFixed(1)} × ${b.height.toFixed(1)} m`
})

function isOutside(p: Point): boolean {
  return !pointInPolygon(p.x, p.y, store.office.outline)
}

function isSelected(kind: NonNullable<Selection>['kind'], index: number): boolean {
  return store.selection?.kind === kind && store.selection.index === index
}

function toMetres(event: PointerEvent | MouseEvent): Point {
  const el = svg.value!
  const p = el.createSVGPoint()
  p.x = event.clientX
  p.y = event.clientY
  const local = p.matrixTransform(el.getScreenCTM()!.inverse())
  return { x: local.x / U, y: local.y / U }
}

function startDrag(event: PointerEvent, selection: NonNullable<Selection>, at: Point): void {
  if (tracing.value) return
  event.stopPropagation()
  store.selection = selection
  const pointer = toMetres(event)
  dragOffset = { x: at.x - pointer.x, y: at.y - pointer.y }
  frozenView.value = liveView.value
  svg.value?.setPointerCapture(event.pointerId)
}

function onPointerMove(event: PointerEvent): void {
  const pointer = toMetres(event)
  if (tracing.value) {
    hover.value = { x: snap(pointer.x, 0.05), y: snap(pointer.y, 0.05) }
    return
  }
  if (dragOffset) store.moveSelected({ x: pointer.x + dragOffset.x, y: pointer.y + dragOffset.y })
}

function endDrag(event: PointerEvent): void {
  if (!dragOffset) return
  dragOffset = null
  frozenView.value = null
  svg.value?.releasePointerCapture(event.pointerId)
}

function onBackgroundDown(event: PointerEvent): void {
  if (!tracing.value) {
    store.selection = null
    return
  }
  const pointer = toMetres(event)
  const p = { x: snap(pointer.x, 0.05), y: snap(pointer.y, 0.05) }
  const first = trace.value[0]
  if (trace.value.length >= 3 && Math.hypot(p.x - first.x, p.y - first.y) < CLOSE_DISTANCE_M) finishTrace()
  else trace.value.push(p)
}

function startTrace(): void {
  tracing.value = true
  trace.value = []
  store.selection = null
  store.notice = 'Click each corner of the room in order. Click the first corner again, or Finish, to close it.'
}
function finishTrace(): void {
  if (trace.value.length < 3) return
  store.setOutline(trace.value)
  cancelTrace(false)
}
function cancelTrace(clearNotice = true): void {
  tracing.value = false
  trace.value = []
  hover.value = null
  if (clearNotice) store.notice = ''
}

function onKeydown(event: KeyboardEvent): void {
  if (tracing.value) {
    if (event.key === 'Escape') cancelTrace()
    else if (event.key === 'Enter') finishTrace()
    else if (event.key === 'Backspace') trace.value.pop()
    return
  }
  const step = event.shiftKey ? 0.5 : 0.1
  const moves: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }
  if (moves[event.key] && store.selection) {
    event.preventDefault()
    store.nudgeSelected(...moves[event.key])
  } else if (event.key === 'Delete' || event.key === 'Backspace') {
    store.deleteSelected()
  } else if (event.key.toLowerCase() === 'r') {
    store.rotateSelectedSlot()
  }
}

async function onFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) await store.loadScan(file)
  input.value = ''
}
</script>

<template>
  <div class="editor">
    <div class="toolbar" role="toolbar" aria-label="Edit the office">
      <button type="button" :disabled="tracing" @click="store.addDesk()">Add desk</button>
      <button type="button" :disabled="tracing" @click="store.addSlot()">Add screen position</button>
      <button type="button" :disabled="tracing || store.selection?.kind !== 'slot'" @click="store.rotateSelectedSlot()">Rotate</button>
      <button type="button" :disabled="tracing || !store.canDeleteSelected" @click="store.deleteSelected()">Delete</button>
      <span class="gap"></span>
      <template v-if="!tracing">
        <button type="button" @click="fileInput?.click()">Open scan (.glb)</button>
        <button type="button" @click="startTrace()">Trace room</button>
        <button type="button" @click="store.resetOffice()">Reset to demo office</button>
      </template>
      <template v-else>
        <button type="button" class="primary" :disabled="trace.length < 3" @click="finishTrace()">Finish ({{ trace.length }} corners)</button>
        <button type="button" :disabled="!trace.length" @click="trace.pop()">Undo corner</button>
        <button type="button" @click="cancelTrace()">Cancel</button>
      </template>
      <input ref="fileInput" type="file" accept=".glb,model/gltf-binary" hidden @change="onFile" />
    </div>

    <div v-if="store.scan" class="scanbar">
      <span class="file">{{ store.scanName }} · {{ Math.round(store.scan.triangles / 1000) }}k triangles</span>
      <label>
        Cut height <output>{{ store.sliceHeight.toFixed(2) }} m</output>
        <input v-model.number="store.sliceHeight" type="range" min="0.2" max="2.4" step="0.05" />
      </label>
      <label>
        Rotate scan <output>{{ store.scanAngle }}°</output>
        <input v-model.number="store.scanAngle" type="range" min="-180" max="180" step="1" />
      </label>
      <button type="button" @click="store.clearScan()">Remove scan</button>
    </div>
    <p v-if="store.scanError" class="error" role="alert">{{ store.scanError }}</p>

    <svg
      ref="svg"
      class="canvas"
      :class="{ tracing }"
      :viewBox="viewBox"
      tabindex="0"
      role="application"
      aria-label="Floor plan editor. Select an item and use the arrow keys to move it."
      @pointerdown="onBackgroundDown"
      @pointermove="onPointerMove"
      @pointerup="endDrag"
      @pointercancel="endDrag"
      @pointerleave="hover = null"
      @keydown="onKeydown"
    >
      <defs>
        <pattern id="grid" :width="U" :height="U" patternUnits="userSpaceOnUse">
          <path :d="`M${U} 0H0V${U}`" fill="none" stroke="#17302b" stroke-opacity=".08" stroke-width=".2" />
        </pattern>
      </defs>
      <rect :x="view.minX * U" :y="view.minY * U" :width="view.width * U" :height="view.height * U" fill="url(#grid)" />

      <path :d="outlinePath" class="room" :class="{ ghost: tracing }" />
      <path v-if="scanPath" :d="scanPath" class="scan" />

      <template v-if="!tracing">
        <g v-for="w in walls" :key="`w${w.index}`">
          <text :x="w.mx * U + w.ox" :y="w.my * U + w.oy" class="dim">{{ w.length.toFixed(1) }} m</text>
          <circle :cx="w.mx * U" :cy="w.my * U" r="1.3" class="addcorner" @pointerdown.stop="store.splitWall(w.index)">
            <title>Add a corner here</title>
          </circle>
        </g>

        <g
          v-for="(slot, i) in store.office.slots"
          :key="`s${slot.id}`"
          class="item slot"
          :class="{ on: isSelected('slot', i), out: isOutside(slot) }"
          tabindex="0"
          role="button"
          :aria-label="`Screen position ${i + 1}`"
          @focus="store.selection = { kind: 'slot', index: i }"
          @pointerdown="startDrag($event, { kind: 'slot', index: i }, slot)"
        >
          <line :x1="slotLines[i].x1 * U" :y1="slotLines[i].y1 * U" :x2="slotLines[i].x2 * U" :y2="slotLines[i].y2 * U" />
          <line class="hit" :x1="slotLines[i].x1 * U" :y1="slotLines[i].y1 * U" :x2="slotLines[i].x2 * U" :y2="slotLines[i].y2 * U" />
        </g>

        <g
          v-for="(desk, i) in store.office.desks"
          :key="`d${i}`"
          class="item desk"
          :class="{ on: isSelected('desk', i), out: isOutside(desk) }"
          tabindex="0"
          role="button"
          :aria-label="`Desk ${i + 1}`"
          @focus="store.selection = { kind: 'desk', index: i }"
          @pointerdown="startDrag($event, { kind: 'desk', index: i }, desk)"
        >
          <rect :x="desk.x * U - 6" :y="desk.y * U - 3.5" width="12" height="7" rx="1.4" />
        </g>

        <g
          class="item source"
          :class="{ on: isSelected('source', 0) }"
          tabindex="0"
          role="button"
          aria-label="Conversation"
          @focus="store.selection = { kind: 'source', index: 0 }"
          @pointerdown="startDrag($event, { kind: 'source', index: 0 }, store.office.source)"
        >
          <circle :cx="store.office.source.x * U" :cy="store.office.source.y * U" r="6" class="halo" />
          <circle :cx="store.office.source.x * U" :cy="store.office.source.y * U" r="2.4" />
          <text :x="store.office.source.x * U" :y="store.office.source.y * U + 10" class="label">conversation</text>
        </g>

        <rect
          v-for="(corner, i) in store.office.outline"
          :key="`c${i}`"
          class="item corner"
          :class="{ on: isSelected('corner', i) }"
          :x="corner.x * U - 1.6"
          :y="corner.y * U - 1.6"
          width="3.2"
          height="3.2"
          tabindex="0"
          role="button"
          :aria-label="`Room corner ${i + 1}`"
          @focus="store.selection = { kind: 'corner', index: i }"
          @pointerdown="startDrag($event, { kind: 'corner', index: i }, corner)"
        />
      </template>

      <template v-else>
        <path :d="tracePath" class="trace" />
        <circle v-for="(p, i) in trace" :key="`t${i}`" :cx="p.x * U" :cy="p.y * U" :r="i === 0 ? 2 : 1.2" class="tracepoint" :class="{ first: i === 0 }" />
      </template>
    </svg>

    <p class="cap">
      <b>{{ roomSize }}</b> · {{ store.office.desks.length }} desks · {{ store.office.slots.length }} screen positions.
      <template v-if="store.notice"> {{ store.notice }}</template>
      <template v-else>
        Drag anything to move it. The dot in the middle of a wall adds a corner. Arrow keys move the selected item, Delete removes it, R turns a
        screen position.
      </template>
    </p>
  </div>
</template>
