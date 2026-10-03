/**
 * Pinia store: the office being designed, the layout search, and an optional scan underlay
 */

import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'
import type { Capabilities, LayoutResult, Office, OptimizationParams, Point, ResultSource, Strategy } from '@/types'
import { EARSHOT_DB, defaultOffice } from '@/types'
import { optimizationApi } from '@/api/optimization'
import { bestOf, estimateSearch } from '@/physics/estimate'
import { boundsOf, interiorPoint, pointInPolygon, snap } from '@/physics/geometry'
import type { ScanMesh } from '@/scan/glb'
import { dominantAngle, parseGlb, placeSegments, placementOf, sliceAt } from '@/scan/glb'

const POLL_INTERVAL_MS = 2000
const STORAGE_KEY = 'quietoffice.office.v1'

export type Selection = { kind: 'corner' | 'desk' | 'slot' | 'source'; index: number } | null

function loadSavedOffice(): Office | null {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null')
    if (saved && Array.isArray(saved.outline) && saved.outline.length >= 3 && saved.source && Array.isArray(saved.desks) && Array.isArray(saved.slots)) {
      return saved as Office
    }
  } catch {
    // storage blocked or corrupt: fall back to the demo office
  }
  return null
}

export const useOptimizationStore = defineStore('optimization', () => {
  // ============================================================================
  // STATE
  // ============================================================================

  const savedOffice = loadSavedOffice()
  const office = ref<Office>(savedOffice ?? defaultOffice())
  const nScreens = ref(3)
  const strategy = ref<Strategy>('greedy')
  const frequencies = ref<number[]>([250, 500])
  const screenLength = ref(1.8)

  const capabilities = ref<Capabilities | null>(null)
  const backendOnline = ref(false)

  const optimizationId = ref<string | null>(null)
  const status = ref<'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'aborted'>('idle')
  const progress = ref(0)
  const message = ref('')
  const layoutsTotal = ref(0)
  const error = ref<string | null>(null)
  const projectUrl = ref<string | null>(null)

  // What is on screen: every layout tested, and where the numbers came from.
  const layouts = ref<LayoutResult[]>([])
  const source = ref<ResultSource>('estimate')

  // Editing
  const view = ref<'result' | 'edit'>('result')
  const selection = ref<Selection>(null)
  const notice = ref('')

  // Scan underlay. The mesh is large, so it is kept out of deep reactivity.
  const scan = shallowRef<ScanMesh | null>(null)
  const scanName = ref('')
  const scanAngle = ref(0)
  const sliceHeight = ref(1.2)
  const scanError = ref<string | null>(null)

  // ============================================================================
  // GETTERS
  // ============================================================================

  const params = computed<OptimizationParams>(() => ({
    office: office.value,
    n_screens: nScreens.value,
    screen_length_m: screenLength.value,
    screen_thickness_m: 0.1,
    frequencies_hz: frequencies.value,
    strategy: strategy.value,
  }))

  const isRunning = computed(() => status.value === 'running' || status.value === 'pending')
  const baseline = computed(() => layouts.value.find((l) => l.slot_ids.length === 0) ?? null)
  const placedScreens = computed(() => Math.min(nScreens.value, office.value.slots.length))
  const best = computed(() => bestOf(layouts.value, placedScreens.value))
  const canUseAllsolve = computed(
    () => backendOnline.value && !!capabilities.value?.sdk_installed && !!capabilities.value?.credentials_configured && office.value.desks.length > 0,
  )
  const allsolveBlockedReason = computed(() => {
    if (!backendOnline.value) return 'The backend is not running. Start it to run on Allsolve.'
    if (!capabilities.value?.sdk_installed) return 'The Allsolve SDK is not installed on the backend.'
    if (!capabilities.value?.credentials_configured) return 'Allsolve credentials are missing. Fill in .env and restart the backend.'
    if (!office.value.desks.length) return 'Add at least one desk first.'
    return null
  })
  const plannedLayouts = computed(() => {
    const slots = office.value.slots.length, n = placedScreens.value
    if (strategy.value === 'greedy') {
      let total = 1
      for (let k = 0; k < n; k++) total += slots - k
      return total
    }
    let combos = 1
    for (let k = 0; k < n; k++) combos = (combos * (slots - k)) / (k + 1)
    return 1 + Math.round(combos)
  })

  const scanPlacement = computed(() => (scan.value ? placementOf(scan.value, scanAngle.value) : null))
  /** The scan cut at the chosen height, placed on the floor plan: x1, y1, x2, y2 per segment. */
  const scanSegments = computed(() =>
    scan.value && scanPlacement.value ? placeSegments(sliceAt(scan.value, sliceHeight.value), scanPlacement.value) : null,
  )

  function inEarshot(layout: LayoutResult | null): number {
    return layout ? layout.desk_levels_db.filter((l) => l >= EARSHOT_DB).length : 0
  }

  // ============================================================================
  // SEARCH
  // ============================================================================

  /** Ask the backend what it can do. A failed request just means it is offline. */
  async function init(): Promise<void> {
    try {
      capabilities.value = await optimizationApi.getCapabilities()
      backendOnline.value = true
    } catch {
      capabilities.value = null
      backendOnline.value = false
    }
    runEstimate()
  }

  /** Instant answer from the in-browser estimate. */
  function runEstimate(): void {
    if (isRunning.value) return
    layouts.value = estimateSearch(office.value, params.value)
    layoutsTotal.value = layouts.value.length
    source.value = 'estimate'
    status.value = 'idle'
    progress.value = 0
    message.value = ''
    error.value = null
    projectUrl.value = null
  }

  /** Run the search on Allsolve through the backend and poll until it finishes. */
  async function runOnAllsolve(): Promise<void> {
    if (isRunning.value || !canUseAllsolve.value) return
    error.value = null
    status.value = 'pending'
    progress.value = 0
    message.value = 'Starting...'
    try {
      const response = await optimizationApi.start({ ...params.value, n_screens: placedScreens.value })
      optimizationId.value = response.optimization_id
      status.value = 'running'
      await poll(response.optimization_id)
    } catch (e) {
      status.value = 'failed'
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  async function poll(id: string): Promise<void> {
    for (;;) {
      const s = await optimizationApi.getStatus(id)
      progress.value = s.progress
      message.value = s.message ?? ''
      layoutsTotal.value = s.layouts_total
      projectUrl.value = s.project_url
      if (s.status === 'completed') {
        const results = await optimizationApi.getResults(id)
        layouts.value = results.layouts
        source.value = 'allsolve'
        projectUrl.value = results.project_url
        status.value = 'completed'
        return
      }
      if (s.status === 'failed' || s.status === 'aborted') {
        status.value = s.status
        error.value = s.message ?? 'The run did not finish'
        return
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS))
    }
  }

  async function abort(): Promise<void> {
    if (!optimizationId.value || !isRunning.value) return
    try {
      await optimizationApi.abort(optimizationId.value)
      message.value = 'Stopping...'
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    }
  }

  /** Changing a choice invalidates what is on screen, so re-run the estimate. */
  function setScreens(n: number): void {
    nScreens.value = n
    runEstimate()
  }
  function setStrategy(s: Strategy): void {
    strategy.value = s
    runEstimate()
  }
  function toggleFrequency(hz: number): void {
    const has = frequencies.value.includes(hz)
    if (has && frequencies.value.length === 1) return
    frequencies.value = has ? frequencies.value.filter((f) => f !== hz) : [...frequencies.value, hz].sort((a, b) => a - b)
    runEstimate()
  }

  // ============================================================================
  // EDITING THE OFFICE
  // ============================================================================

  // Any change to the office re-runs the estimate and is remembered in this browser.
  watch(
    office,
    (value) => {
      runEstimate()
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
      } catch {
        // storage blocked: the office simply is not remembered
      }
    },
    { deep: true },
  )

  function moveSelected(to: Point): void {
    const s = selection.value
    if (!s) return
    const p = { x: snap(to.x), y: snap(to.y) }
    const o = office.value
    if (s.kind === 'corner') Object.assign(o.outline[s.index], p)
    else if (s.kind === 'desk') Object.assign(o.desks[s.index], p)
    else if (s.kind === 'slot') Object.assign(o.slots[s.index], p)
    else Object.assign(o.source, p)
  }

  function positionOf(s: NonNullable<Selection>): Point {
    const o = office.value
    return s.kind === 'corner' ? o.outline[s.index] : s.kind === 'desk' ? o.desks[s.index] : s.kind === 'slot' ? o.slots[s.index] : o.source
  }

  function nudgeSelected(dx: number, dy: number): void {
    if (!selection.value) return
    const p = positionOf(selection.value)
    moveSelected({ x: p.x + dx, y: p.y + dy })
  }

  /** A free spot for a new item: inside the room, away from what is already there. */
  function freeSpot(): Point {
    const o = office.value, b = boundsOf(o.outline)
    const taken = [...o.desks, ...o.slots, o.source]
    for (let y = b.minY + 1; y < b.maxY; y += 1) {
      for (let x = b.minX + 1; x < b.maxX; x += 1) {
        if (pointInPolygon(x, y, o.outline) && taken.every((t) => Math.hypot(t.x - x, t.y - y) > 1.2)) return { x: snap(x), y: snap(y) }
      }
    }
    return interiorPoint(o.outline)
  }

  function addDesk(): void {
    office.value.desks.push(freeSpot())
    selection.value = { kind: 'desk', index: office.value.desks.length - 1 }
  }

  function addSlot(): void {
    const slots = office.value.slots
    const id = slots.reduce((max, s) => Math.max(max, s.id), -1) + 1
    slots.push({ id, ...freeSpot(), orientation: 'v', label: `Position ${id + 1}` })
    selection.value = { kind: 'slot', index: slots.length - 1 }
  }

  function rotateSelectedSlot(): void {
    const s = selection.value
    if (s?.kind !== 'slot') return
    const slot = office.value.slots[s.index]
    slot.orientation = slot.orientation === 'v' ? 'h' : 'v'
  }

  /** Add a room corner in the middle of the wall that starts at corner `index`. */
  function splitWall(index: number): void {
    const outline = office.value.outline
    const a = outline[index], b = outline[(index + 1) % outline.length]
    outline.splice(index + 1, 0, { x: snap((a.x + b.x) / 2), y: snap((a.y + b.y) / 2) })
    selection.value = { kind: 'corner', index: index + 1 }
  }

  const canDeleteSelected = computed(() => {
    const s = selection.value
    if (!s || s.kind === 'source') return false
    return s.kind !== 'corner' || office.value.outline.length > 3
  })

  function deleteSelected(): void {
    const s = selection.value
    if (!s || !canDeleteSelected.value) return
    const o = office.value
    if (s.kind === 'corner') o.outline.splice(s.index, 1)
    else if (s.kind === 'desk') o.desks.splice(s.index, 1)
    else if (s.kind === 'slot') o.slots.splice(s.index, 1)
    selection.value = null
  }

  function resetOffice(): void {
    office.value = defaultOffice()
    selection.value = null
    notice.value = 'Back to the demo office.'
  }

  /**
   * Replace the room with a traced outline. Desks and screen positions that end up outside
   * are removed, and the conversation is moved inside if needed.
   */
  function setOutline(points: Point[]): void {
    const outline = points.map((p) => ({ x: snap(p.x), y: snap(p.y) }))
    const o = office.value
    const inside = (p: Point) => pointInPolygon(p.x, p.y, outline)
    const desks = o.desks.filter(inside), slots = o.slots.filter(inside)
    const removed = o.desks.length - desks.length + (o.slots.length - slots.length)
    office.value = { outline, source: inside(o.source) ? o.source : interiorPoint(outline), desks, slots }
    selection.value = null
    notice.value = removed
      ? `New room set. ${removed} desks and screen positions were outside it and have been removed. Add new ones.`
      : 'New room set.'
  }

  // ============================================================================
  // SCAN UNDERLAY
  // ============================================================================

  async function loadScan(file: File): Promise<void> {
    scanError.value = null
    try {
      const mesh = parseGlb(await file.arrayBuffer())
      scanAngle.value = -Math.round(dominantAngle(sliceAt(mesh, 1.2)))
      scan.value = mesh
      scanName.value = file.name
      sliceHeight.value = 1.2
      notice.value = 'Scan loaded. Square it up with the rotation slider if needed, then trace the room.'
    } catch (e) {
      scan.value = null
      scanName.value = ''
      scanError.value = e instanceof Error ? e.message : String(e)
    }
  }

  function clearScan(): void {
    scan.value = null
    scanName.value = ''
    scanError.value = null
  }

  return {
    office,
    nScreens,
    strategy,
    frequencies,
    screenLength,
    capabilities,
    backendOnline,
    status,
    progress,
    message,
    layoutsTotal,
    error,
    projectUrl,
    layouts,
    source,
    view,
    selection,
    notice,
    scan,
    scanName,
    scanAngle,
    sliceHeight,
    scanError,
    params,
    isRunning,
    baseline,
    best,
    placedScreens,
    canUseAllsolve,
    allsolveBlockedReason,
    plannedLayouts,
    scanPlacement,
    scanSegments,
    canDeleteSelected,
    inEarshot,
    init,
    runEstimate,
    runOnAllsolve,
    abort,
    setScreens,
    setStrategy,
    toggleFrequency,
    moveSelected,
    nudgeSelected,
    addDesk,
    addSlot,
    rotateSelectedSlot,
    splitWall,
    deleteSelected,
    resetOffice,
    setOutline,
    loadScan,
    clearScan,
  }
})
