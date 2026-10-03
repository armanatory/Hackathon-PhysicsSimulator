<script setup lang="ts">
import { computed } from 'vue'
import { PANEL_TYPES } from '@/types'
import { useOptimizationStore } from '@/stores/optimizationStore'

const store = useOptimizationStore()
const BANDS = [250, 500, 1000, 2000]

function bandLabel(hz: number): string {
  return hz >= 1000 ? `${hz / 1000} kHz` : `${hz} Hz`
}

// Jobs Allsolve has not finished, and the machines they run on: one per sweep step.
const liveJobs = computed(() => store.cloudJobs.filter((job) => job.status === 'running'))
const liveMachines = computed(() => liveJobs.value.filter((job) => job.server_status === 'running').reduce((sum, job) => sum + job.steps, 0))

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
      <h2>How many panels</h2>
      <div class="seg" role="group" aria-label="Number of panels">
        <button v-for="n in [1, 2, 3, 4]" :key="n" type="button" :aria-pressed="store.nScreens === n" :disabled="store.isRunning" @click="store.setScreens(n)">
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

    <div class="run">
      <button v-if="!store.isRunning" class="btn" type="button" :disabled="!store.canUseAllsolve" @click="store.runOnAllsolve()">Find the best positions</button>
      <button v-else class="btn ghost" type="button" @click="store.abort()">Stop</button>
      <p v-if="!store.isRunning && store.allsolveBlockedReason" class="hint">{{ store.allsolveBlockedReason }}</p>
    </div>

    <div v-if="store.isRunning" class="progress" role="status">
      <div class="track"><i :style="{ width: `${store.progress}%` }"></i></div>
      <p class="hint">{{ store.message }}</p>
      <template v-if="liveJobs.length">
        <h2 class="live">
          On Allsolve now<template v-if="liveMachines > 1">: {{ liveMachines }} machines running at the same time</template>
        </h2>
        <ul class="jobs">
          <li v-for="job in liveJobs" :key="job.id">
            <span>
              {{ job.what }}
              <small>
                {{ job.steps }} {{ job.steps === 1 ? 'machine' : 'machines' }}<template v-if="job.steps_done !== null">, {{ job.steps_done }} done</template>
              </small>
            </span>
            <b>{{ job.server_status ?? 'sent' }}<template v-if="job.progress"> · {{ Math.round(job.progress * 100) }}%</template></b>
          </li>
        </ul>
        <p class="hint">Status and counts are read from Allsolve each time this page asks for progress.</p>
      </template>
    </div>
    <p v-if="store.error" class="error" role="alert">{{ store.error }}</p>

    <details class="advanced">
      <summary>Simulation settings</summary>
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
        <button type="button" :aria-pressed="store.strategy === 'fast'" :disabled="store.isRunning" @click="store.setStrategy('fast')">Fast, 30 s</button>
      </div>
      <p v-if="store.strategy === 'fast'" class="hint">
        The estimate ranks every combination; Allsolve then simulates the {{ Math.max(0, store.plannedLayouts - 1) }} most promising and the
        empty office, shared over the machines. 2D only.
      </p>
      <p v-else class="hint">{{ store.plannedLayouts }} layouts to simulate.</p>
    </div>

    <div class="field">
      <h2>Allsolve model</h2>
      <div class="seg" role="group" aria-label="Simulation model">
        <button type="button" :aria-pressed="store.model === '3d'" :disabled="store.isRunning" @click="store.setModel('3d')">3D room</button>
        <button type="button" :aria-pressed="store.model === '2d'" :disabled="store.isRunning" @click="store.setModel('2d')">2D slice</button>
      </div>
      <p class="hint">{{ sizeHint }}</p>
    </div>

    <div v-if="store.strategy === 'fast'" class="field">
      <h2>Allsolve machines</h2>
      <template v-if="store.machines">
        <p class="hint" style="margin-top: 0">Each cloud machine solves several layouts one after another, and each band has its own mesh. Booting the machines is the slow part.</p>
        <p v-if="store.machines.state === 'ready'" class="hint">
          <b>{{ store.machines.machines }} machines are running.</b> A search now simulates {{ store.machines.plan_now.layouts }} layouts in
          about {{ store.machines.plan_now.seconds }} s. They cost credits while they run, and are given back after
          {{ Math.round(store.machines.idle_limit_s / 60) }} minutes without a search. A second search of the same room skips the
          setup and simulates about {{ store.machines.plan_repeat.layouts }}.
        </p>
        <p v-else-if="store.machines.state === 'starting'" class="hint" role="status">
          Booting {{ store.machines.machines }} machines. This takes about half a minute.
        </p>
        <p v-else class="hint">
          No machines are running. A search started now boots its own and simulates {{ store.machines.plan_cold.layouts }} layouts in about
          {{ store.machines.plan_cold.seconds }} s, or longer when Allsolve is slow to boot them (14 to 32 s when measured). With {{ store.machines.warm_size }} machines started first it simulates
          {{ store.machines.plan_warm.layouts }} layouts in about {{ store.machines.plan_warm.seconds }} s.
        </p>
        <p v-if="store.machines.state === 'failed'" class="error" role="alert">Allsolve did not give the machines: {{ store.machines.error }}</p>
        <button
          v-if="store.machines.state === 'ready' || store.machines.state === 'starting'"
          class="btn ghost small"
          type="button"
          :disabled="store.machinesBusy || store.isRunning"
          @click="store.refreshMachines('release')"
        >
          Give the machines back
        </button>
        <button v-else class="btn ghost small" type="button" :disabled="store.machinesBusy || store.isRunning" @click="store.refreshMachines('warm')">
          Start {{ store.machines.warm_size }} machines
        </button>
      </template>
      <p v-else class="hint" style="margin-top: 0">Start the backend to see the Allsolve machines.</p>
    </div>

    </details>
  </div>
</template>
