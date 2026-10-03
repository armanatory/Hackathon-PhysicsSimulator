/**
 * Pinia store: the office being designed, the layout search, and an optional scan underlay
 */

import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'
import type { Capabilities, CloudJob, Evidence, LayoutResult, LogEntry, Machines, Office, OptimizationParams, Point, SimulationModel, Step, Strategy } from '@/types'
import { EARSHOT_DB, PANEL_TYPES, blankOffice, defaultOffice } from '@/types'
import { optimizationApi } from '@/api/optimization'
import { bestOf, estimateLayout, estimateSearch, suggestSlots } from '@/physics/estimate'
import { boundsOf, interiorPoint, pointInPolygon, snap } from '@/physics/geometry'
import type { Orientation, ScanMesh } from '@/scan/glb'
import { dominantAngle, orient, parseGlb, placeSegments, placementOf, sliceAt } from '@/scan/glb'

// Same rule of thumb as the backend: second-order tetrahedra at six elements per wavelength.
const UNKNOWNS_PER_CUBIC_MESH_SIZE = 11.5
const ELEMENTS_PER_WAVELENGTH = 6
const SPEED_OF_SOUND = 343

const POLL_INTERVAL_MS = 2000
const FAST_POLL_INTERVAL_MS = 700
const FAST_BUDGET_S = 30
const MAX_CANDIDATES = 3000 // the most the backend accepts; it simulates as many as fit the time

/** An Allsolve run that finished, kept so it can still be explained after the page moves on. */
interface FinishedRun {
  id: string
  finishedAt: string
  context: Record<string, unknown>
}
const STORAGE_KEY = 'quietoffice.office.v1'
// Places a panel may stand are worked out from the noise sources and the quiet zones. Twelve keeps a
// one-at-a-time search at 34 layouts for three panels and 43 for four.
const CANDIDATE_POSITIONS = 12

/** 'zone' moves a quiet zone; 'zonesize' drags its bottom-right corner to resize it. */
export type Selection = { kind: 'corner' | 'desk' | 'slot' | 'source' | 'zone' | 'zonesize'; index: number } | null

/** The run in progress or on screen, kept so a page reload can pick it up again from the backend. */
interface SavedRun {
  id: string
  startedAt: number
  /** How long the run took, once it has finished */
  seconds: number | null
  settings: { nScreens: number; strategy: Strategy; frequencies: number[]; panelTypeId: string; screenAbsorbing: boolean; model: SimulationModel }
}
const RUN_KEY = 'quietoffice.run.v1'

function loadSavedRun(): SavedRun | null {
  try {
    const saved = JSON.parse(localStorage.getItem(RUN_KEY) ?? 'null')
    return saved && typeof saved.id === 'string' && saved.settings ? (saved as SavedRun) : null
  } catch {
    return null
  }
}

function saveRun(run: SavedRun | null): void {
  try {
    if (run) localStorage.setItem(RUN_KEY, JSON.stringify(run))
    else localStorage.removeItem(RUN_KEY)
  } catch {
    // storage blocked: the run simply is not picked up after a reload
  }
}

function loadSavedOffice(): Office | null {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null')
    if (saved && Array.isArray(saved.outline) && saved.outline.length >= 3 && Array.isArray(saved.desks) && Array.isArray(saved.slots)) {
      if (typeof saved.ceiling_height_m !== 'number') saved.ceiling_height_m = 2.7
      // Offices saved before several noise sources and quiet zones existed
      if (!Array.isArray(saved.sources)) {
        saved.sources = saved.source ? [{ x: saved.source.x, y: saved.source.y, level_db: 60, label: 'Conversation' }] : []
        delete saved.source
      }
      if (!Array.isArray(saved.quiet_zones)) saved.quiet_zones = []
      return saved as Office
    }
  } catch {
    // storage blocked or corrupt: start a new job
  }
  return null
}

export const useOptimizationStore = defineStore('optimization', () => {
  // ============================================================================
  // STATE
  // ============================================================================

  const savedOffice = loadSavedOffice()
  const office = ref<Office>(savedOffice ?? blankOffice())
  // A job is started by importing a scan, drawing a room or opening the demo office.
  const started = ref(!!savedOffice)
  const step = ref<Step>('room')
  const nScreens = ref(3)
  const strategy = ref<Strategy>('greedy')
  const frequencies = ref<number[]>([250, 500])
  const screenLength = ref(1.8)
  const panelTypeId = ref('screen')
  const screenAbsorbing = ref(false)
  const model = ref<SimulationModel>('3d')

  const capabilities = ref<Capabilities | null>(null)
  const backendOnline = ref(false)

  const optimizationId = ref<string | null>(null)
  const status = ref<'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'aborted'>('idle')
  const progress = ref(0)
  const message = ref('')
  const layoutsTotal = ref(0)
  const error = ref<string | null>(null)
  const projectUrl = ref<string | null>(null)
  const projectName = ref<string | null>(null)
  // Seconds since the search was started; it stops counting when the run ends
  const elapsedS = ref(0)

  // Every layout Allsolve simulated. Empty until a run finishes: nothing is shown as a result before that.
  const layouts = ref<LayoutResult[]>([])

  // Proof of the Allsolve run: its log and the raw solver output
  const logEntries = ref<LogEntry[]>([])
  // The mesh and simulation jobs of the run in progress, as Allsolve reports them
  const cloudJobs = ref<CloudJob[]>([])
  const evidence = ref<Evidence | null>(null)

  // Cloud machines held ready for the fast search
  const machines = ref<Machines | null>(null)
  const machinesBusy = ref(false)
  const lastRun = ref<FinishedRun | null>(null)

  // Plain-language explanation
  const explanation = ref('')
  const explanationModel = ref('')
  const explaining = ref(false)
  const explainError = ref<string | null>(null)

  // Editing
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

  const panelType = computed(() => PANEL_TYPES.find((t) => t.id === panelTypeId.value) ?? PANEL_TYPES[1])

  const params = computed<OptimizationParams>(() => ({
    office: office.value,
    n_screens: nScreens.value,
    screen_length_m: screenLength.value,
    screen_thickness_m: 0.1,
    screen_height_m: Math.min(panelType.value.height_m, office.value.ceiling_height_m),
    screen_absorbing: screenAbsorbing.value,
    model: model.value,
    parallel_jobs: 1,
    source_height_m: 1.5,
    ear_height_m: 1.2,
    frequencies_hz: frequencies.value,
    strategy: strategy.value,
  }))

  const isRunning = computed(() => status.value === 'running' || status.value === 'pending')
  const hasListeners = computed(() => office.value.desks.length > 0 || office.value.quiet_zones.length > 0)
  const baseline = computed(() => layouts.value.find((l) => l.slot_ids.length === 0) ?? null)
  const placedScreens = computed(() => Math.min(nScreens.value, office.value.slots.length))
  const best = computed(() => bestOf(layouts.value, placedScreens.value))
  const hasResult = computed(() => !!best.value && !!baseline.value)
  const canUseAllsolve = computed(
    () => backendOnline.value && !!capabilities.value?.sdk_installed && !!capabilities.value?.credentials_configured && officeBlockedReason.value === null,
  )
  /** What is still missing on the plan before panels can be placed. */
  const officeBlockedReason = computed(() => {
    if (!office.value.sources.length) return 'Mark at least one noise source first.'
    if (!hasListeners.value) return 'Mark at least one quiet zone first.'
    if (!office.value.slots.length) return 'There is no place for a panel between the noise and the quiet zones. Move them further apart.'
    return null
  })
  const allsolveBlockedReason = computed(() => {
    if (officeBlockedReason.value) return officeBlockedReason.value
    if (!backendOnline.value) return 'The backend is not running. Start it to simulate.'
    if (!capabilities.value?.sdk_installed) return 'The Allsolve SDK is not installed on the backend.'
    if (!capabilities.value?.credentials_configured) return 'Allsolve credentials are missing. Fill in .env and restart the backend.'
    return null
  })
  const plannedLayouts = computed(() => {
    const slots = office.value.slots.length, n = placedScreens.value
    if (strategy.value === 'fast') {
      // Every combination is ranked by the estimate; Allsolve simulates as many as fit the time.
      const fit = machines.value?.plan_now.layouts ?? 2
      let every = 1
      for (let k = 0; k < n; k++) every = (every * (slots - k)) / (k + 1)
      return Math.min(1 + Math.round(every), fit)
    }
    if (strategy.value === 'greedy') {
      let total = 1
      for (let k = 0; k < n; k++) total += slots - k
      return total
    }
    let combos = 1
    for (let k = 0; k < n; k++) combos = (combos * (slots - k)) / (k + 1)
    return 1 + Math.round(combos)
  })

  /** Rough size of one 3D solve on Allsolve at the highest chosen band. */
  const unknowns3d = computed(() => {
    const b = boundsOf(office.value.outline)
    const meshSize = SPEED_OF_SOUND / (Math.max(...frequencies.value) * ELEMENTS_PER_WAVELENGTH)
    return (UNKNOWNS_PER_CUBIC_MESH_SIZE * b.width * b.height * office.value.ceiling_height_m) / meshSize ** 3
  })

  const scanPlacement = computed(() => (scan.value ? placementOf(scan.value, scanAngle.value) : null))
  /** The scan cut at the chosen height, placed on the floor plan: x1, y1, x2, y2 per segment. */
  const scanSegments = computed(() =>
    scan.value && scanPlacement.value ? placeSegments(sliceAt(scan.value, sliceHeight.value), scanPlacement.value) : null,
  )

  /** The quick estimate for the layout Allsolve chose, to set beside the solver's numbers. */
  const estimateForBest = computed(() => (best.value ? estimateLayout(office.value, best.value.slot_ids, params.value) : null))
  const estimateScoreForBest = computed(() => estimateForBest.value?.score ?? null)
  const comparison = computed(() => {
    const allsolve = best.value, estimate = estimateForBest.value
    if (!allsolve || !estimate) return []
    const pressures = evidence.value?.best_pressures_pa ?? []
    const rows = office.value.quiet_zones.map((zone, i) => ({
      label: zone.label || `Quiet zone ${i + 1}`,
      estimate: estimate.zone_levels_db[i] ?? 0,
      allsolve: allsolve.zone_levels_db[i] ?? 0,
      pressures: undefined as number[][] | undefined,
    }))
    allsolve.desk_levels_db.forEach((level, i) => {
      rows.push({ label: `Desk ${i + 1}`, estimate: estimate.desk_levels_db[i] ?? 0, allsolve: level, pressures: pressures[i] })
    })
    return rows
  })

  /**
   * The Allsolve run an explanation would be about. The quick estimate is never explained as
   * if it were a simulation: with no run on screen, this is the last run that finished.
   */
  const explainTarget = computed<{ id: string; earlier: FinishedRun | null } | null>(() => {
    if (optimizationId.value && logEntries.value.length) return { id: optimizationId.value, earlier: null }
    return lastRun.value ? { id: lastRun.value.id, earlier: lastRun.value } : null
  })
  const canExplain = computed(() => backendOnline.value && !!capabilities.value?.ai_configured && !isRunning.value && !!explainTarget.value)
  const explainBlockedReason = computed(() => {
    if (!backendOnline.value) return 'The backend is not running, so the explanation is not available.'
    if (!capabilities.value?.ai_configured) return 'Add OPENAI_API_KEY to .env and restart the backend to get an explanation in plain language.'
    if (!explainTarget.value) return 'Nothing has been simulated yet.'
    return null
  })
  /** When the explanation would be about an earlier run and not what is on screen: when that run finished. */
  const explainsEarlierRun = computed(() => explainTarget.value?.earlier?.finishedAt ?? null)

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
    syncSlots()
    void refreshMachines()
    const saved = loadSavedRun()
    if (saved && backendOnline.value) resume(saved)
  }

  /** After a page reload: show the run that was going on, or its result, again. The backend kept it. */
  function resume(saved: SavedRun): void {
    nScreens.value = saved.settings.nScreens
    strategy.value = saved.settings.strategy
    frequencies.value = saved.settings.frequencies
    panelTypeId.value = saved.settings.panelTypeId
    screenAbsorbing.value = saved.settings.screenAbsorbing
    model.value = saved.settings.model
    optimizationId.value = saved.id
    status.value = 'running'
    message.value = 'Reconnecting to the run...'
    started.value = true
    step.value = 'panels'
    void follow(saved.id, saved.startedAt, saved.seconds)
  }

  /** Ask the backend whether machines are held ready, and what fits the time budget. */
  async function refreshMachines(action?: 'warm' | 'release'): Promise<void> {
    if (!backendOnline.value || !capabilities.value?.sdk_installed || !capabilities.value?.credentials_configured) return
    if (action) machinesBusy.value = true
    try {
      const b = boundsOf(office.value.outline)
      machines.value = await optimizationApi.machines(
        office.value.sources.length,
        frequencies.value,
        FAST_BUDGET_S,
        b.width * b.height,
        action,
      )
      if (machines.value.state === 'starting') setTimeout(() => void refreshMachines(), 2000)
    } catch {
      machines.value = null
    } finally {
      machinesBusy.value = false
    }
  }

  /** Changing the room or a choice makes the result on screen out of date, so it is taken away. */
  function clearResult(): void {
    if (isRunning.value) return
    layouts.value = []
    saveRun(null)
    if (step.value === 'result') step.value = 'panels'
    layoutsTotal.value = 0
    status.value = 'idle'
    progress.value = 0
    message.value = ''
    error.value = null
    projectUrl.value = null
    projectName.value = null
    elapsedS.value = 0
    logEntries.value = []
    evidence.value = null
    explanation.value = ''
    explainError.value = null
  }

  /** Run the search on Allsolve through the backend and poll until it finishes. */
  async function runOnAllsolve(): Promise<void> {
    if (isRunning.value || !canUseAllsolve.value) return
    error.value = null
    status.value = 'pending'
    progress.value = 0
    message.value = 'Starting...'
    logEntries.value = []
    cloudJobs.value = []
    evidence.value = null
    explanation.value = ''
    const startedAt = Date.now()
    elapsedS.value = 0
    let id: string
    try {
      const request: OptimizationParams = { ...params.value, n_screens: placedScreens.value }
      if (strategy.value === 'fast') {
        // The estimate has scored every combination: send the most promising ones, best first.
        request.candidate_layouts = estimateSearch(office.value, request)
          .filter((l) => l.slot_ids.length === placedScreens.value)
          .sort((a, b) => a.score - b.score)
          .slice(0, MAX_CANDIDATES)
          .map((l) => l.slot_ids)
        request.time_budget_s = FAST_BUDGET_S
      }
      id = (await optimizationApi.start(request)).optimization_id
    } catch (e) {
      status.value = 'failed'
      error.value = e instanceof Error ? e.message : String(e)
      return
    }
    optimizationId.value = id
    status.value = 'running'
    saveRun({
      id,
      startedAt,
      seconds: null,
      settings: {
        nScreens: nScreens.value,
        strategy: strategy.value,
        frequencies: frequencies.value,
        panelTypeId: panelTypeId.value,
        screenAbsorbing: screenAbsorbing.value,
        model: model.value,
      },
    })
    await follow(id, startedAt, null)
  }

  /**
   * Poll a run until it ends, with the clock running. `seconds` is given for a run that had
   * already finished before the page was reloaded: its time is known and the clock stays off.
   */
  async function follow(id: string, startedAt: number, seconds: number | null): Promise<void> {
    const tick = () => (elapsedS.value = Math.round((Date.now() - startedAt) / 1000))
    const clock = seconds === null ? setInterval(tick, 1000) : null
    if (seconds === null) tick()
    else elapsedS.value = seconds
    try {
      await poll(id)
    } catch (e) {
      status.value = 'failed'
      error.value = e instanceof Error ? e.message : String(e)
      if (error.value === 'Optimization not found') error.value = 'The backend no longer has this run. It was probably restarted while the run was going on.'
    } finally {
      if (clock) {
        clearInterval(clock)
        tick()
      }
      // A finished run stays findable, so a reload shows its result again. Anything else is forgotten.
      const saved = loadSavedRun()
      if (status.value !== 'completed') saveRun(null)
      else if (saved?.id === id && saved.seconds === null) saveRun({ ...saved, seconds: elapsedS.value })
    }
  }

  /** Everything known about the run on screen, as a file: settings, every log line with its data, raw solver output. */
  function downloadLog(): void {
    const record = {
      downloaded_at: new Date().toISOString(),
      optimization_id: optimizationId.value,
      status: status.value,
      error: error.value,
      seconds: elapsedS.value,
      project_name: projectName.value,
      project_url: projectUrl.value,
      request: params.value,
      cloud_jobs: cloudJobs.value,
      log: logEntries.value,
      layouts: layouts.value,
      evidence: evidence.value,
    }
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: 'application/json' }))
    link.download = `quietoffice-run-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`
    link.click()
    URL.revokeObjectURL(link.href)
  }

  async function poll(id: string): Promise<void> {
    for (;;) {
      const s = await optimizationApi.getStatus(id)
      progress.value = s.progress
      message.value = s.message ?? ''
      layoutsTotal.value = s.layouts_total
      projectUrl.value = s.project_url
      projectName.value = s.project_name
      cloudJobs.value = s.jobs ?? []
      if (s.log_size > logEntries.value.length) {
        const log = await optimizationApi.getLog(id, logEntries.value.length)
        logEntries.value.push(...log.entries)
      }
      if (s.status === 'completed') {
        const results = await optimizationApi.getResults(id)
        layouts.value = results.layouts
        evidence.value = results.evidence
        step.value = 'result'
        projectUrl.value = results.project_url
        projectName.value = results.project_name
        status.value = 'completed'
        lastRun.value = { id, finishedAt: new Date().toISOString(), context: explainContext() }
        void refreshMachines()
        return
      }
      if (s.status === 'failed' || s.status === 'aborted') {
        status.value = s.status
        error.value = s.message ?? 'The run did not finish'
        return
      }
      await new Promise((resolve) => setTimeout(resolve, strategy.value === 'fast' ? FAST_POLL_INTERVAL_MS : POLL_INTERVAL_MS))
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

  /** The facts of the run on screen, for the AI model to put into words. */
  function explainContext(): Record<string, unknown> {
    const o = office.value, b = baseline.value, w = best.value
    const round = (values: number[]) => values.map((v) => Math.round(v * 10) / 10)
    return {
      source_of_numbers: 'allsolve',
      run_status: status.value,
      run_error: error.value,
      office: {
        room_size_m: boundsOf(o.outline),
        ceiling_height_m: o.ceiling_height_m,
        noise_sources: o.sources.map((s) => ({ name: s.label, level_db_at_1m: s.level_db })),
        quiet_zones: o.quiet_zones.map((z) => z.label),
        desks: o.desks.length,
        candidate_screen_positions: o.slots.length,
      },
      settings: {
        screens_to_place: placedScreens.value,
        panel: panelType.value.name,
        panel_height_m: panelType.value.height_m,
        panel_surface: screenAbsorbing.value ? 'absorbing' : 'hard',
        speech_bands_hz: frequencies.value,
        search:
          strategy.value === 'greedy'
            ? 'one screen at a time'
            : strategy.value === 'fast'
              ? `as many of the most promising layouts as fit ${FAST_BUDGET_S} seconds, shared over the machines`
              : 'every combination',
        noise_minimised_at: o.quiet_zones.length ? 'the quiet zones' : 'the desks',
        allsolve_model: model.value,
      },
      result:
        b && w
          ? {
              layouts_tested: layouts.value.length,
              noise_score_before: 100,
              noise_score_after: Math.round(w.score * 10) / 10,
              chosen_positions: w.slot_ids.map((id) => o.slots.find((s) => s.id === id)?.label ?? `position ${id}`),
              desk_levels_db_before: round(b.desk_levels_db),
              desk_levels_db_after: round(w.desk_levels_db),
              zone_levels_db_before: round(b.zone_levels_db),
              zone_levels_db_after: round(w.zone_levels_db),
              desks_in_earshot_before: inEarshot(b),
              desks_in_earshot_after: inEarshot(w),
            }
          : null,
      allsolve: evidence.value
        ? { project_url: evidence.value.project_url, solves: evidence.value.solves, cloud_jobs: evidence.value.jobs.length }
        : null,
      quick_estimate_score_for_same_layout: estimateScoreForBest.value === null ? null : Math.round(estimateScoreForBest.value * 10) / 10,
    }
  }

  /** Ask the AI model to explain an Allsolve run: the one on screen, or else the last one that finished. */
  async function explain(): Promise<void> {
    const target = explainTarget.value
    if (!canExplain.value || explaining.value || !target) return
    explaining.value = true
    explainError.value = null
    const context = target.earlier
      ? { ...target.earlier.context, run_finished_at: target.earlier.finishedAt, page_changed_since_run: true }
      : { ...explainContext(), page_changed_since_run: false }
    try {
      const answer = await optimizationApi.explain(context, target.id)
      explanation.value = answer.text
      explanationModel.value = answer.model
    } catch (e) {
      explainError.value = e instanceof Error ? e.message : String(e)
    } finally {
      explaining.value = false
    }
  }

  function setScreens(n: number): void {
    nScreens.value = n
    clearResult()
  }
  function setStrategy(s: Strategy): void {
    strategy.value = s
    if (s === 'fast') model.value = '2d' // one 3D layout takes minutes to mesh
    clearResult()
  }
  function setPanelType(id: string): void {
    panelTypeId.value = id
    clearResult()
  }
  function setAbsorbing(absorbing: boolean): void {
    screenAbsorbing.value = absorbing
    clearResult()
  }
  function setModel(value: SimulationModel): void {
    model.value = value
    if (value === '3d' && strategy.value === 'fast') strategy.value = 'greedy'
    clearResult()
  }
  function toggleFrequency(hz: number): void {
    const has = frequencies.value.includes(hz)
    if (has && frequencies.value.length === 1) return
    frequencies.value = has ? frequencies.value.filter((f) => f !== hz) : [...frequencies.value, hz].sort((a, b) => a - b)
    clearResult()
    void refreshMachines()
  }

  // ============================================================================
  // EDITING THE OFFICE
  // ============================================================================

  /** Work out again where a panel may stand. Returns true when the positions changed. */
  function syncSlots(): boolean {
    const slots = suggestSlots(office.value, screenLength.value, CANDIDATE_POSITIONS).map((slot, i) => ({ ...slot, label: `Position ${i + 1}` }))
    if (JSON.stringify(slots) === JSON.stringify(office.value.slots)) return false
    office.value.slots = slots
    return true
  }

  // Any change to the office takes the result away and is remembered in this browser.
  watch(
    office,
    (value) => {
      if (isRunning.value) return
      if (syncSlots()) return // the watcher runs again with the new positions
      clearResult()
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
    else if (s.kind === 'source') Object.assign(o.sources[s.index], p)
    else if (s.kind === 'zone') Object.assign(o.quiet_zones[s.index], p)
    else {
      // The handle is the zone's bottom-right corner.
      const zone = o.quiet_zones[s.index]
      zone.width = Math.max(0.6, snap(p.x - zone.x))
      zone.height = Math.max(0.6, snap(p.y - zone.y))
    }
  }

  function positionOf(s: NonNullable<Selection>): Point {
    const o = office.value
    if (s.kind === 'corner') return o.outline[s.index]
    if (s.kind === 'desk') return o.desks[s.index]
    if (s.kind === 'slot') return o.slots[s.index]
    if (s.kind === 'source') return o.sources[s.index]
    const zone = o.quiet_zones[s.index]
    return s.kind === 'zone' ? zone : { x: zone.x + zone.width, y: zone.y + zone.height }
  }

  function nudgeSelected(dx: number, dy: number): void {
    if (!selection.value) return
    const p = positionOf(selection.value)
    moveSelected({ x: p.x + dx, y: p.y + dy })
  }

  /** A free spot for a new item: inside the room, away from what is already there. */
  function freeSpot(): Point {
    const o = office.value, b = boundsOf(o.outline)
    const taken = [...o.desks, ...o.sources]
    for (let y = b.minY + 1; y < b.maxY; y += 1) {
      for (let x = b.minX + 1; x < b.maxX; x += 1) {
        if (pointInPolygon(x, y, o.outline) && taken.every((t) => Math.hypot(t.x - x, t.y - y) > 1.2)) return { x: snap(x), y: snap(y) }
      }
    }
    return interiorPoint(o.outline)
  }

  function addSource(): void {
    const sources = office.value.sources
    if (sources.length >= 6) return
    sources.push({ ...freeSpot(), level_db: 60, label: `Source ${sources.length + 1}` })
    selection.value = { kind: 'source', index: sources.length - 1 }
  }

  function addZone(): void {
    const zones = office.value.quiet_zones
    if (zones.length >= 10) return
    const spot = freeSpot()
    zones.push({ x: spot.x, y: spot.y, width: 3, height: 2, label: `Quiet zone ${zones.length + 1}` })
    selection.value = { kind: 'zone', index: zones.length - 1 }
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
    if (!s) return false
    return s.kind !== 'corner' || office.value.outline.length > 3
  })

  function deleteSelected(): void {
    const s = selection.value
    if (!s || !canDeleteSelected.value) return
    const o = office.value
    if (s.kind === 'corner') o.outline.splice(s.index, 1)
    else if (s.kind === 'desk') o.desks.splice(s.index, 1)
    else if (s.kind === 'slot') o.slots.splice(s.index, 1)
    else if (s.kind === 'source') o.sources.splice(s.index, 1)
    else o.quiet_zones.splice(s.index, 1)
    selection.value = null
  }

  /** Start a job: on the demo office, or on an empty room to draw or trace into. */
  function startJob(kind: 'demo' | 'blank'): void {
    office.value = kind === 'demo' ? defaultOffice() : blankOffice()
    selection.value = null
    notice.value = ''
    scan.value = null
    scanName.value = ''
    scanError.value = null
    started.value = true
    step.value = 'room'
  }

  /** Throw the job away and go back to the start. */
  function newJob(): void {
    startJob('blank')
    started.value = false
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
    const quiet_zones = o.quiet_zones.filter((z) => inside({ x: z.x + z.width / 2, y: z.y + z.height / 2 }))
    let sources = o.sources.filter(inside)
    if (!sources.length && o.sources.length) sources = [{ ...o.sources[0], ...interiorPoint(outline) }]
    const removed = o.desks.length - desks.length + (o.quiet_zones.length - quiet_zones.length)
    office.value = { ...o, outline, sources, desks, quiet_zones, slots }
    selection.value = null
    notice.value = removed
      ? `New room set. ${removed} quiet zones were outside it and have been removed.`
      : 'New room set.'
  }

  // ============================================================================
  // SCAN UNDERLAY
  // ============================================================================

  /** Put a freshly parsed or re-oriented model on the plan and square it up. */
  function showScan(mesh: ScanMesh, what: string): void {
    scanAngle.value = -Math.round(dominantAngle(sliceAt(mesh, 1.2)))
    scan.value = mesh
    const o = office.value
    if (mesh.ceilingHeight) o.ceiling_height_m = mesh.ceilingHeight
    // Until something is marked on the plan, the room is the footprint of the scan.
    const footprint = placementOf(mesh, scanAngle.value)
    const untouched = !o.sources.length && !o.quiet_zones.length && !o.desks.length && footprint.width > 1 && footprint.height > 1
    if (untouched) {
      const w = snap(footprint.width), h = snap(footprint.height)
      o.outline = [{ x: 0, y: 0 }, { x: w, y: 0 }, { x: w, y: h }, { x: 0, y: h }]
    }
    const { up, unitScale } = mesh.orientation
    const units = unitScale === 1 ? 'metres' : unitScale === 0.01 ? 'centimetres' : 'millimetres'
    notice.value =
      `${what}: read as ${up.toUpperCase()}-up, in ${units}` +
      (mesh.ceilingHeight ? `, ceiling ${mesh.ceilingHeight.toFixed(2)} m. ` : '. ') +
      'If it looks wrong, change the up axis or units above the plan. ' +
      (untouched ? 'The room is set to the outer size of the scan: trace it if the room is not a rectangle.' : 'Then trace the room.')
  }

  async function loadScan(file: File): Promise<void> {
    scanError.value = null
    try {
      const mesh = parseGlb(await file.arrayBuffer())
      scanName.value = file.name
      sliceHeight.value = 1.2
      // A new scan is a new room: nothing of the room before it is kept.
      office.value = blankOffice()
      selection.value = null
      showScan(mesh, 'Model loaded')
    } catch (e) {
      scan.value = null
      scanName.value = ''
      scanError.value = e instanceof Error ? e.message : String(e)
    }
  }

  /** Change which way is up, or the units, when the automatic guess was wrong. */
  function orientScan(change: Partial<Orientation>): void {
    const mesh = scan.value
    if (!mesh) return
    showScan(orient(mesh.raw, mesh.indices, { ...mesh.orientation, ...change }), 'Model re-read')
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
    panelTypeId,
    panelType,
    screenAbsorbing,
    model,
    hasListeners,
    unknowns3d,
    capabilities,
    backendOnline,
    status,
    progress,
    message,
    layoutsTotal,
    error,
    projectUrl,
    projectName,
    elapsedS,
    downloadLog,
    layouts,
    hasResult,
    logEntries,
    cloudJobs,
    evidence,
    explanation,
    explanationModel,
    explaining,
    explainError,
    comparison,
    estimateScoreForBest,
    canExplain,
    explainsEarlierRun,
    machines,
    machinesBusy,
    refreshMachines,
    explainBlockedReason,
    explain,
    started,
    step,
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
    officeBlockedReason,
    allsolveBlockedReason,
    plannedLayouts,
    scanPlacement,
    scanSegments,
    canDeleteSelected,
    inEarshot,
    init,
    runOnAllsolve,
    abort,
    setScreens,
    setStrategy,
    toggleFrequency,
    setPanelType,
    setAbsorbing,
    setModel,
    moveSelected,
    nudgeSelected,
    addSource,
    addZone,
    splitWall,
    deleteSelected,
    startJob,
    newJob,
    setOutline,
    loadScan,
    orientScan,
    clearScan,
  }
})
