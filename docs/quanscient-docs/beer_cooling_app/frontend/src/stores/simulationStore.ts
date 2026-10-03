/**
 * Pinia store for simulation state management
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type {
  SimulationParams,
  SimulationResults,
  TemperaturePoint,
  ContainerShape,
  CoolingMethod,
} from '@/types'
import { simulationApi } from '@/api/simulation'
import { COOLING_SPECS, CONTAINER_SPECS } from '@/types'

export const useSimulationStore = defineStore('simulation', () => {
  // ============================================================================
  // STATE
  // ============================================================================

  const params = ref<SimulationParams>({
    container_shape: 'can',
    cooling_method: 'ice_water',
    initial_temp_celsius: 20,
    target_temp_celsius: 4,
    immersion_level: 0.8,
    simulation_duration_minutes: 30,
  })

  const simulationId = ref<string | null>(null)
  const status = ref<'idle' | 'pending' | 'running' | 'completed' | 'failed'>('idle')
  const progress = ref(0)
  const message = ref('')
  const results = ref<SimulationResults | null>(null)
  const error = ref<string | null>(null)

  // For animated playback
  const playbackIndex = ref(0)
  const isPlaying = ref(false)

  // Demo mode toggle (false = use real Allsolve simulation)
  const useDemoMode = ref(false)

  // ============================================================================
  // GETTERS
  // ============================================================================

  const isRunning = computed(() => status.value === 'running' || status.value === 'pending')
  const isCompleted = computed(() => status.value === 'completed')
  const hasResults = computed(() => results.value !== null)

  const temperatureHistory = computed<TemperaturePoint[]>(() => {
    return results.value?.temperature_history ?? []
  })

  const currentTemperature = computed(() => {
    if (temperatureHistory.value.length > 0 && playbackIndex.value < temperatureHistory.value.length) {
      return temperatureHistory.value[playbackIndex.value].temperature_celsius
    }
    return params.value.initial_temp_celsius
  })

  const currentTime = computed(() => {
    if (temperatureHistory.value.length > 0 && playbackIndex.value < temperatureHistory.value.length) {
      return temperatureHistory.value[playbackIndex.value].time_seconds
    }
    return 0
  })

  const timeToTarget = computed(() => {
    return results.value?.time_to_target_seconds ?? null
  })

  const finalTemperature = computed(() => {
    return results.value?.final_temperature_celsius ?? params.value.initial_temp_celsius
  })

  const containerSpec = computed(() => {
    return CONTAINER_SPECS[params.value.container_shape]
  })

  const coolingSpec = computed(() => {
    return COOLING_SPECS[params.value.cooling_method]
  })

  // Temperature color (hot = red/orange, cold = blue)
  const temperatureColor = computed(() => {
    const temp = currentTemperature.value
    const min = coolingSpec.value.coolant_temp_celsius
    const max = params.value.initial_temp_celsius
    const normalized = Math.max(0, Math.min(1, (temp - min) / (max - min)))

    // HSL: 0 = red, 30 = orange, 200 = blue
    const hue = 200 - normalized * 170
    return `hsl(${hue}, 80%, 50%)`
  })

  // ============================================================================
  // ACTIONS
  // ============================================================================

  function setContainerShape(shape: ContainerShape) {
    params.value.container_shape = shape
  }

  function setCoolingMethod(method: CoolingMethod) {
    params.value.cooling_method = method
  }

  function setInitialTemp(temp: number) {
    params.value.initial_temp_celsius = temp
  }

  function setTargetTemp(temp: number) {
    params.value.target_temp_celsius = temp
  }

  function setImmersionLevel(level: number) {
    params.value.immersion_level = level
  }

  function setDuration(minutes: number) {
    params.value.simulation_duration_minutes = minutes
  }

  function setDemoMode(demo: boolean) {
    useDemoMode.value = demo
  }

  async function startSimulation() {
    status.value = 'pending'
    progress.value = 0
    error.value = null
    results.value = null
    playbackIndex.value = 0

    try {
      if (useDemoMode.value) {
        // Use demo mode for quick results without backend
        console.log('🎮 Running in DEMO mode (no Allsolve)')
        message.value = 'Running demo simulation...'
        status.value = 'running'

        // Simulate loading time
        for (let i = 0; i <= 100; i += 10) {
          progress.value = i
          await new Promise(resolve => setTimeout(resolve, 100))
        }

        const demoResults = await simulationApi.runDemo(params.value)
        results.value = demoResults
        simulationId.value = demoResults.simulation_id
        status.value = 'completed'
        message.value = 'Demo complete!'

        // Start playback
        startPlayback()
      } else {
        // Real simulation via Allsolve
        console.log('🚀 Running REAL simulation via Quanscient Allsolve!')
        message.value = 'Starting Allsolve simulation...'
        const response = await simulationApi.start(params.value)
        simulationId.value = response.simulation_id
        status.value = 'running'
        message.value = response.message

        // Poll for status or use WebSocket
        pollStatus()
      }
    } catch (e) {
      status.value = 'failed'
      error.value = e instanceof Error ? e.message : 'Unknown error'
      message.value = error.value
    }
  }

  async function pollStatus() {
    if (!simulationId.value) return

    try {
      const statusResponse = await simulationApi.getStatus(simulationId.value)
      console.log(`📊 Poll: status=${statusResponse.status}, progress=${statusResponse.progress?.toFixed(1)}%, msg=${statusResponse.message?.slice(0, 30)}`)

      progress.value = statusResponse.progress
      message.value = statusResponse.message ?? ''

      // Update status to match backend (but keep 'running' if pending)
      if (statusResponse.status === 'running' || statusResponse.status === 'pending') {
        status.value = 'running'
      }

      if (statusResponse.status === 'completed') {
        console.log('✅ Simulation completed, fetching results...')
        const resultsResponse = await simulationApi.getResults(simulationId.value)
        results.value = resultsResponse
        status.value = 'completed'
        startPlayback()
      } else if (statusResponse.status === 'failed') {
        console.log('❌ Simulation failed')
        status.value = 'failed'
        error.value = statusResponse.message ?? 'Simulation failed'
      } else {
        // Continue polling every 1 second for more responsive updates
        setTimeout(pollStatus, 1000)
      }
    } catch (e) {
      console.error('Poll error:', e)
      status.value = 'failed'
      error.value = e instanceof Error ? e.message : 'Failed to get status'
    }
  }

  function startPlayback() {
    if (!hasResults.value) return

    isPlaying.value = true
    playbackIndex.value = 0

    const animate = () => {
      if (!isPlaying.value) return

      if (playbackIndex.value < temperatureHistory.value.length - 1) {
        playbackIndex.value++
        requestAnimationFrame(animate)
      } else {
        isPlaying.value = false
      }
    }

    // Slow down playback
    const slowAnimate = () => {
      animate()
      if (isPlaying.value) {
        setTimeout(slowAnimate, 50)
      }
    }

    slowAnimate()
  }

  function pausePlayback() {
    isPlaying.value = false
  }

  function seekPlayback(index: number) {
    playbackIndex.value = Math.max(0, Math.min(index, temperatureHistory.value.length - 1))
  }

  async function abortSimulation() {
    console.log('🛑 Abort requested', { simulationId: simulationId.value, status: status.value, isRunning: isRunning.value })

    if (!isRunning.value) {
      console.log('   Not running, ignoring abort')
      return
    }

    if (!simulationId.value) {
      // No simulation ID yet, just reset to idle
      console.log('   No simulation ID yet, resetting to idle')
      status.value = 'idle'
      message.value = 'Aborted before simulation started'
      progress.value = 0
      return
    }

    try {
      message.value = 'Aborting simulation...'
      console.log('   Calling abort API...')
      await simulationApi.abort(simulationId.value)
      status.value = 'idle'
      message.value = 'Simulation aborted'
      progress.value = 0
      console.log('   Abort successful')
    } catch (e) {
      console.error('   Abort failed:', e)
      error.value = e instanceof Error ? e.message : 'Failed to abort'
      message.value = error.value
      // Still set to idle so user can retry
      status.value = 'idle'
    }
  }

  function reset() {
    status.value = 'idle'
    progress.value = 0
    message.value = ''
    results.value = null
    error.value = null
    simulationId.value = null
    playbackIndex.value = 0
    isPlaying.value = false
  }

  return {
    // State
    params,
    simulationId,
    status,
    progress,
    message,
    results,
    error,
    playbackIndex,
    isPlaying,
    useDemoMode,

    // Getters
    isRunning,
    isCompleted,
    hasResults,
    temperatureHistory,
    currentTemperature,
    currentTime,
    timeToTarget,
    finalTemperature,
    containerSpec,
    coolingSpec,
    temperatureColor,

    // Actions
    setContainerShape,
    setCoolingMethod,
    setInitialTemp,
    setTargetTemp,
    setImmersionLevel,
    setDuration,
    setDemoMode,
    startSimulation,
    abortSimulation,
    startPlayback,
    pausePlayback,
    seekPlayback,
    reset,
  }
})

