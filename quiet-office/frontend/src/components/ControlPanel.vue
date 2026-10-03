<script setup lang="ts">
import { useOptimizationStore } from '@/stores/optimizationStore'

const store = useOptimizationStore()
const BANDS = [250, 500, 1000, 2000]

function bandLabel(hz: number): string {
  return hz >= 1000 ? `${hz / 1000} kHz` : `${hz} Hz`
}
</script>

<template>
  <div class="panel">
    <div class="field">
      <h2>Screens to place</h2>
      <div class="seg" role="group" aria-label="Number of screens">
        <button v-for="n in [1, 2, 3]" :key="n" type="button" :aria-pressed="store.nScreens === n" :disabled="store.isRunning" @click="store.setScreens(n)">
          {{ n }}
        </button>
      </div>
    </div>

    <div class="field">
      <h2>Speech bands</h2>
      <div class="seg" role="group" aria-label="Speech bands to simulate">
        <button
          v-for="hz in BANDS"
          :key="hz"
          type="button"
          :aria-pressed="store.frequencies.includes(hz)"
          :disabled="store.isRunning"
          @click="store.toggleFrequency(hz)"
        >
          {{ bandLabel(hz) }}
        </button>
      </div>
      <p class="hint">Higher bands need a finer mesh and take longer on Allsolve.</p>
    </div>

    <div class="field">
      <h2>Search</h2>
      <div class="seg" role="group" aria-label="Search strategy">
        <button type="button" :aria-pressed="store.strategy === 'greedy'" :disabled="store.isRunning" @click="store.setStrategy('greedy')">One at a time</button>
        <button type="button" :aria-pressed="store.strategy === 'exhaustive'" :disabled="store.isRunning" @click="store.setStrategy('exhaustive')">Every combination</button>
      </div>
      <p class="hint">{{ store.plannedLayouts }} layouts to simulate.</p>
    </div>

    <div class="run">
      <button v-if="!store.isRunning" class="btn" type="button" :disabled="!store.canUseAllsolve" @click="store.runOnAllsolve()">Run on Allsolve</button>
      <button v-else class="btn ghost" type="button" @click="store.abort()">Stop the run</button>
      <p v-if="!store.isRunning && store.allsolveBlockedReason" class="hint">{{ store.allsolveBlockedReason }}</p>
    </div>

    <div v-if="store.isRunning" class="progress" role="status">
      <div class="track"><i :style="{ width: `${store.progress}%` }"></i></div>
      <p class="hint">{{ store.message }}</p>
    </div>
    <p v-if="store.error" class="error" role="alert">{{ store.error }}</p>
  </div>
</template>
