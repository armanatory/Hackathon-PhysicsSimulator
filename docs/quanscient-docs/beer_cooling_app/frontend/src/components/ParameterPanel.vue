<script setup lang="ts">
import { computed } from 'vue'
import { useSimulationStore } from '@/stores/simulationStore'
import { CONTAINER_SPECS, COOLING_SPECS, type ContainerShape, type CoolingMethod } from '@/types'

const store = useSimulationStore()

const containerOptions = computed(() => {
  return (Object.entries(CONTAINER_SPECS) as [ContainerShape, typeof CONTAINER_SPECS[ContainerShape]][]).map(
    ([key, spec]) => ({
      value: key,
      label: spec.label,
    })
  )
})

const coolingOptions = computed(() => {
  return (Object.entries(COOLING_SPECS) as [CoolingMethod, typeof COOLING_SPECS[CoolingMethod]][]).map(
    ([key, spec]) => ({
      value: key,
      label: `${spec.emoji} ${spec.label} (${spec.coolant_temp_celsius}°C)`,
    })
  )
})

const immersionPercent = computed({
  get: () => Math.round(store.params.immersion_level * 100),
  set: (val) => store.setImmersionLevel(val / 100),
})

const showImmersion = computed(() => {
  return store.params.cooling_method === 'ice_water' || store.params.cooling_method === 'salt_ice'
})

async function handleStart() {
  await store.startSimulation()
}

async function handleAbort() {
  console.log('Abort button clicked!')
  await store.abortSimulation()
}

function handleReset() {
  store.reset()
}

function toggleMode() {
  store.setDemoMode(!store.useDemoMode)
}
</script>

<template>
  <div class="card p-6 space-y-5">
    <h2 class="text-base font-semibold text-grey-900 flex items-center gap-2">
      <svg class="w-5 h-5 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75"/>
      </svg>
      Simulation Parameters
    </h2>

    <!-- Container Shape -->
    <div class="space-y-2">
      <label class="text-sm font-medium text-grey-700">Container Type</label>
      <div class="grid grid-cols-3 gap-2">
        <button
          v-for="option in containerOptions"
          :key="option.value"
          @click="store.setContainerShape(option.value as ContainerShape)"
          :class="[
            'px-3 py-2 rounded-lg text-sm font-medium transition-all border',
            store.params.container_shape === option.value
              ? 'bg-primary-50 text-primary-700 border-primary-300'
              : 'bg-white text-grey-600 border-grey-200 hover:bg-grey-50',
          ]"
        >
          {{ option.value === 'can' ? '🥫' : option.value === 'bottle' ? '🍾' : '🍺' }}
          <span class="block text-xs mt-1">{{ option.value }}</span>
        </button>
      </div>
    </div>

    <!-- Cooling Method -->
    <div class="space-y-2">
      <label class="text-sm font-medium text-grey-700">Cooling Method</label>
      <select
        :value="store.params.cooling_method"
        @change="store.setCoolingMethod(($event.target as HTMLSelectElement).value as CoolingMethod)"
        class="w-full bg-white border border-grey-300 rounded-lg px-3 py-2 text-sm text-grey-800 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
      >
        <option v-for="option in coolingOptions" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
    </div>

    <!-- Initial Temperature -->
    <div class="space-y-2">
      <div class="flex justify-between">
        <label class="text-sm font-medium text-grey-700">Initial Temperature</label>
        <span class="text-sm text-primary-600 font-mono font-medium">{{ store.params.initial_temp_celsius }}°C</span>
      </div>
      <input
        type="range"
        :value="store.params.initial_temp_celsius"
        @input="store.setInitialTemp(Number(($event.target as HTMLInputElement).value))"
        min="-10"
        max="40"
        step="1"
        class="w-full"
      />
      <div class="flex justify-between text-xs text-grey-400">
        <span>-10°C</span>
        <span>Room temp (20°C)</span>
        <span>40°C</span>
      </div>
    </div>

    <!-- Target Temperature -->
    <div class="space-y-2">
      <div class="flex justify-between">
        <label class="text-sm font-medium text-grey-700">Target Temperature</label>
        <span class="text-sm text-primary-600 font-mono font-medium">{{ store.params.target_temp_celsius }}°C</span>
      </div>
      <input
        type="range"
        :value="store.params.target_temp_celsius"
        @input="store.setTargetTemp(Number(($event.target as HTMLInputElement).value))"
        min="-10"
        max="20"
        step="1"
        class="w-full"
      />
      <div class="flex justify-between text-xs text-grey-400">
        <span>-10°C</span>
        <span>Perfect drinking (4°C)</span>
        <span>20°C</span>
      </div>
    </div>

    <!-- Immersion Level -->
    <div v-if="showImmersion" class="space-y-2">
      <div class="flex justify-between">
        <label class="text-sm font-medium text-grey-700">Immersion Level</label>
        <span class="text-sm text-primary-600 font-mono font-medium">{{ immersionPercent }}%</span>
      </div>
      <input
        type="range"
        v-model="immersionPercent"
        min="0"
        max="100"
        step="5"
        class="w-full"
      />
      <div class="flex justify-between text-xs text-grey-400">
        <span>0% (floating)</span>
        <span>100% (fully submerged)</span>
      </div>
    </div>

    <!-- Duration -->
    <div class="space-y-2">
      <div class="flex justify-between">
        <label class="text-sm font-medium text-grey-700">Simulation Duration</label>
        <span class="text-sm text-grey-600 font-mono">{{ store.params.simulation_duration_minutes }} min</span>
      </div>
      <input
        type="range"
        :value="store.params.simulation_duration_minutes"
        @input="store.setDuration(Number(($event.target as HTMLInputElement).value))"
        min="5"
        max="60"
        step="5"
        class="w-full"
      />
    </div>

    <!-- Simulation Mode Toggle -->
    <div class="pt-3 border-t border-grey-200">
      <button
        @click="toggleMode"
        class="w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-all border"
        :class="store.useDemoMode
          ? 'bg-amber-50 text-amber-700 border-amber-200'
          : 'bg-green-50 text-green-700 border-green-200'"
      >
        <div class="flex items-center gap-2">
          <span>{{ store.useDemoMode ? '🎮' : '☁️' }}</span>
          <span class="font-medium">{{ store.useDemoMode ? 'Demo Mode' : 'Allsolve Cloud' }}</span>
        </div>
        <span class="text-xs opacity-80">{{ store.useDemoMode ? 'Local approximation' : 'Real FEM simulation' }}</span>
      </button>
      <p class="mt-1.5 text-xs text-grey-400 text-center">
        {{ store.useDemoMode
          ? 'Uses Newton\'s law approximation (instant)'
          : 'Runs on Quanscient Allsolve cloud (requires API key)' }}
      </p>
    </div>

    <!-- Action Buttons -->
    <div class="pt-3 space-y-3">
      <button
        v-if="!store.isRunning"
        @click="handleStart"
        class="w-full btn-primary flex items-center justify-center gap-2 py-3"
      >
        <span>🧊</span>
        <span>Start Cooling</span>
      </button>

      <button
        v-if="store.isRunning"
        @click="handleAbort"
        class="w-full btn-danger flex items-center justify-center gap-2 py-3"
      >
        <svg class="animate-spin w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path
            class="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
        <div class="flex flex-col items-center">
          <span class="font-semibold">{{ Math.round(store.progress) }}% — Click to Abort</span>
          <span class="text-xs opacity-80">{{ store.message }}</span>
        </div>
      </button>

      <button
        v-if="store.hasResults || store.status === 'failed'"
        @click="handleReset"
        class="w-full btn-secondary py-2.5"
      >
        Reset
      </button>
    </div>

    <!-- Status Message -->
    <div v-if="store.message" class="text-xs text-center" :class="store.status === 'failed' ? 'text-red-500' : 'text-grey-500'">
      {{ store.message }}
    </div>
  </div>
</template>
