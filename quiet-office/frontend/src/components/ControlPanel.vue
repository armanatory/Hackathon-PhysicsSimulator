<script setup lang="ts">
import { computed } from 'vue'
import { PANEL_TYPES } from '@/types'
import { useOptimizationStore } from '@/stores/optimizationStore'

const store = useOptimizationStore()
const BANDS = [250, 500, 1000, 2000]

function bandLabel(hz: number): string {
  return hz >= 1000 ? `${hz / 1000} kHz` : `${hz} Hz`
}

const solves = computed(() => store.plannedLayouts * store.office.sources.length * store.frequencies.length)

const sizeHint = computed(() => {
  if (store.model === '2d') return 'Top-down slice. Fast, but every panel counts as floor-to-ceiling and the material is ignored.'
  const millions = store.unknowns3d / 1e6
  const size = millions >= 1 ? `${millions.toFixed(1)} million` : `${Math.round(store.unknowns3d / 1000)} thousand`
  return `Full room with heights. About ${size} unknowns per layout at ${bandLabel(Math.max(...store.frequencies))}; each higher band is eight times larger.`
})
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
      <h2>Panel</h2>
      <div class="seg stackable" role="group" aria-label="Panel type">
        <button
          v-for="type in PANEL_TYPES"
          :key="type.id"
          type="button"
          :aria-pressed="store.panelTypeId === type.id"
          :disabled="store.isRunning"
          @click="store.setPanelType(type.id)"
        >
          {{ type.name }}<small>{{ type.height_m.toFixed(1) }} m</small>
        </button>
      </div>
      <div class="seg" role="group" aria-label="Panel surface" style="margin-top: 6px">
        <button type="button" :aria-pressed="!store.screenAbsorbing" :disabled="store.isRunning" @click="store.setAbsorbing(false)">Hard surface</button>
        <button type="button" :aria-pressed="store.screenAbsorbing" :disabled="store.isRunning" @click="store.setAbsorbing(true)">Absorbing</button>
      </div>
      <p class="hint">{{ store.panelType.name }}: {{ store.panelType.note }}. Ears are at 1.2 m seated, the talker's mouth at 1.5 m.</p>
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
    </div>

    <div class="field">
      <h2>Search</h2>
      <div class="seg" role="group" aria-label="Search strategy">
        <button type="button" :aria-pressed="store.strategy === 'greedy'" :disabled="store.isRunning" @click="store.setStrategy('greedy')">One at a time</button>
        <button type="button" :aria-pressed="store.strategy === 'exhaustive'" :disabled="store.isRunning" @click="store.setStrategy('exhaustive')">Every combination</button>
      </div>
      <p class="hint">{{ store.plannedLayouts }} layouts to simulate.</p>
    </div>

    <div class="field">
      <h2>Allsolve model</h2>
      <div class="seg" role="group" aria-label="Simulation model">
        <button type="button" :aria-pressed="store.model === '3d'" :disabled="store.isRunning" @click="store.setModel('3d')">3D room</button>
        <button type="button" :aria-pressed="store.model === '2d'" :disabled="store.isRunning" @click="store.setModel('2d')">2D slice</button>
      </div>
      <p class="hint">{{ sizeHint }}</p>
    </div>

    <div class="field">
      <h2>Parallel jobs</h2>
      <div class="seg" role="group" aria-label="Allsolve jobs run at the same time">
        <button v-for="n in [1, 2, 4, 8]" :key="n" type="button" :aria-pressed="store.parallelJobs === n" :disabled="store.isRunning" @click="store.parallelJobs = n">
          {{ n }}
        </button>
      </div>
      <p class="hint">
        Each round of layouts is split into this many Allsolve jobs that mesh and solve at the same time:
        {{ solves }} solves in total ({{ store.plannedLayouts }} layouts × {{ store.office.sources.length }}
        {{ store.office.sources.length === 1 ? 'source' : 'sources' }} × {{ store.frequencies.length }} {{ store.frequencies.length === 1 ? 'band' : 'bands' }}).
      </p>
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
