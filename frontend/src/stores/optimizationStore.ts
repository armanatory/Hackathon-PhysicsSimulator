/**
 * Pinia store for the layout search
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { Capabilities, LayoutResult, Office, OptimizationParams, ResultSource, Strategy } from '@/types'
import { EARSHOT_DB, defaultOffice } from '@/types'
import { optimizationApi } from '@/api/optimization'
import { bestOf, estimateSearch } from '@/physics/estimate'

const POLL_INTERVAL_MS = 2000

export const useOptimizationStore = defineStore('optimization', () => {
  // ============================================================================
  // STATE
  // ============================================================================

  const office = ref<Office>(defaultOffice())
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
  const best = computed(() => bestOf(layouts.value, nScreens.value))
  const canUseAllsolve = computed(
    () => backendOnline.value && !!capabilities.value?.sdk_installed && !!capabilities.value?.credentials_configured,
  )
  const allsolveBlockedReason = computed(() => {
    if (!backendOnline.value) return 'The backend is not running. Start it with uvicorn to run on Allsolve.'
    if (!capabilities.value?.sdk_installed) return 'The Allsolve SDK is not installed on the backend.'
    if (!capabilities.value?.credentials_configured) return 'Allsolve credentials are missing. Fill in .env and restart the backend.'
    return null
  })
  const plannedLayouts = computed(() => {
    const slots = office.value.slots.length, n = nScreens.value
    if (strategy.value === 'greedy') {
      let total = 1
      for (let k = 0; k < n; k++) total += slots - k
      return total
    }
    let combos = 1
    for (let k = 0; k < n; k++) combos = (combos * (slots - k)) / (k + 1)
    return 1 + Math.round(combos)
  })

  function inEarshot(layout: LayoutResult | null): number {
    return layout ? layout.desk_levels_db.filter((l) => l >= EARSHOT_DB).length : 0
  }

  // ============================================================================
  // ACTIONS
  // ============================================================================

  /** Ask the backend what it can do. A failed request just means it is offline. */
  async function init(): Promise<void> {
    try {
      capabilities.value = await optimizationApi.getCapabilities()
      office.value = await optimizationApi.getDefaultOffice()
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
      const response = await optimizationApi.start(params.value)
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
    params,
    isRunning,
    baseline,
    best,
    canUseAllsolve,
    allsolveBlockedReason,
    plannedLayouts,
    inEarshot,
    init,
    runEstimate,
    runOnAllsolve,
    abort,
    setScreens,
    setStrategy,
    toggleFrequency,
  }
})
