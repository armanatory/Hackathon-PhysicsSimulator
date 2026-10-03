<script setup lang="ts">
import { computed } from 'vue'
import { useSimulationStore } from '@/stores/simulationStore'
import { formatTime, formatTemperature } from '@/types'

const store = useSimulationStore()

const displayTemp = computed(() => formatTemperature(store.currentTemperature))
const displayTime = computed(() => formatTime(store.currentTime))

const timeToTargetFormatted = computed(() => {
  if (store.timeToTarget === null) return 'N/A'
  return formatTime(store.timeToTarget)
})

const progressPercent = computed(() => {
  if (!store.hasResults || store.temperatureHistory.length === 0) return 0
  return (store.playbackIndex / (store.temperatureHistory.length - 1)) * 100
})

const targetReached = computed(() => {
  return store.currentTemperature <= store.params.target_temp_celsius
})
</script>

<template>
  <div class="card p-6">
    <!-- Current Temperature -->
    <div class="text-center mb-5">
      <div class="text-xs uppercase tracking-wider text-grey-500 mb-1">Current Temperature</div>
      <div
        class="text-4xl font-bold transition-colors duration-300 font-mono"
        :style="{ color: store.temperatureColor }"
      >
        {{ displayTemp }}
      </div>
      <div class="text-sm text-grey-500 mt-1">
        Time: {{ displayTime }}
      </div>
    </div>

    <!-- Target indicator -->
    <div
      v-if="store.hasResults"
      class="flex items-center justify-center gap-2 py-2 rounded-lg mb-4 text-sm"
      :class="targetReached ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-grey-50 text-grey-600 border border-grey-200'"
    >
      <span v-if="targetReached">✓</span>
      <span v-else>🎯</span>
      <span>
        Target: {{ store.params.target_temp_celsius }}°C
        <template v-if="store.timeToTarget !== null">
          (reached in {{ timeToTargetFormatted }})
        </template>
      </span>
    </div>

    <!-- Playback Controls -->
    <div v-if="store.hasResults" class="space-y-3">
      <div class="flex items-center gap-2">
        <button
          @click="store.isPlaying ? store.pausePlayback() : store.startPlayback()"
          class="p-2 rounded-lg bg-grey-100 hover:bg-grey-200 text-grey-700 transition-colors"
        >
          <svg v-if="store.isPlaying" class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <rect x="6" y="5" width="4" height="14" />
            <rect x="14" y="5" width="4" height="14" />
          </svg>
          <svg v-else class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
            <path d="M8 5v14l11-7z" />
          </svg>
        </button>

        <input
          type="range"
          :value="store.playbackIndex"
          @input="store.seekPlayback(Number(($event.target as HTMLInputElement).value))"
          :min="0"
          :max="store.temperatureHistory.length - 1"
          class="flex-1"
        />
      </div>

      <div class="w-full h-1 bg-grey-200 rounded-full overflow-hidden">
        <div
          class="h-full bg-primary-500 transition-all duration-100 rounded-full"
          :style="{ width: `${progressPercent}%` }"
        />
      </div>
    </div>

    <!-- Stats -->
    <div v-if="store.hasResults" class="grid grid-cols-2 gap-4 mt-5 pt-4 border-t border-grey-200">
      <div class="text-center">
        <div class="text-xs text-grey-500">Final Temp</div>
        <div class="font-mono text-lg text-primary-600">{{ formatTemperature(store.finalTemperature) }}</div>
      </div>
      <div class="text-center">
        <div class="text-xs text-grey-500">Time to Target</div>
        <div class="font-mono text-lg" :class="store.timeToTarget !== null ? 'text-green-600' : 'text-grey-400'">
          {{ timeToTargetFormatted }}
        </div>
      </div>
    </div>
  </div>
</template>
