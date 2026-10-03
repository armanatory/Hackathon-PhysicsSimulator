<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
import type { Step } from '@/types'
import { useOptimizationStore } from '@/stores/optimizationStore'
import OfficePlan from '@/components/OfficePlan.vue'
import OfficeEditor from '@/components/OfficeEditor.vue'
import ControlPanel from '@/components/ControlPanel.vue'
import ScoreCard from '@/components/ScoreCard.vue'
import PlacementList from '@/components/PlacementList.vue'
import SearchChart from '@/components/SearchChart.vue'
import RunLog from '@/components/RunLog.vue'

// The 3D library is large, so it is only fetched when the 3D view is opened.
const Office3D = defineAsyncComponent(() => import('@/components/Office3D.vue'))

const store = useOptimizationStore()
onMounted(() => store.init())

const STEPS: { id: Step; name: string }[] = [
  { id: 'room', name: 'Room' },
  { id: 'zones', name: 'Noise and quiet zones' },
  { id: 'panels', name: 'Panels' },
  { id: 'result', name: 'Result' },
]
const words = ['no panels', 'one panel', 'two panels', 'three panels', 'four panels']
const show3d = ref(false)
const scanInput = ref<HTMLInputElement | null>(null)

/** Why a step cannot be opened yet, or null when it can. */
function blocked(step: Step): string | null {
  if (store.isRunning) return step === store.step ? null : 'Wait for the simulation to finish, or stop it.'
  if (step === 'panels') return store.officeBlockedReason
  if (step === 'result') return store.hasResult ? null : 'Nothing has been simulated yet.'
  return null
}

function go(step: Step): void {
  if (blocked(step)) return
  store.selection = null
  store.step = step
}

/** The 3D view shows only the panels that were chosen, never the places the app considered. */
const office3d = computed(() => {
  const chosen = new Set(store.best?.slot_ids ?? [])
  return { ...store.office, slots: store.office.slots.filter((slot) => chosen.has(slot.id)) }
})

async function importScan(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  store.startJob('blank')
  await store.loadScan(file)
}
</script>

<template>
  <header class="bar">
    <div class="wrap">
      <span class="brand"><i></i>QuietOffice</span>
      <button v-if="store.started" type="button" class="btn ghost small" :disabled="store.isRunning" @click="store.newJob()">New job</button>
    </div>
  </header>

  <main v-if="!store.started" class="wrap">
    <div class="head">
      <h1>Where should the panels <b>go</b>?</h1>
      <p class="lead">Bring the room, mark where the noise is and where it should be quiet, and say how many panels you have. The app simulates the room and shows where to put them.</p>
    </div>
    <div class="start">
      <button type="button" @click="scanInput?.click()">
        <b>Import a scan</b>
        <span>A .glb file from a phone scan of the room.</span>
      </button>
      <button type="button" @click="store.startJob('blank')">
        <b>Draw the room</b>
        <span>Start from a rectangle and drag the walls.</span>
      </button>
      <button type="button" @click="store.startJob('demo')">
        <b>Open the demo office</b>
        <span>A 16 × 10 m office with a coffee point and two quiet zones.</span>
      </button>
      <input ref="scanInput" type="file" accept=".glb,model/gltf-binary" hidden @change="importScan" />
    </div>
    <p v-if="store.scanError" class="error" role="alert">{{ store.scanError }}</p>
  </main>

  <main v-else class="wrap">
    <ol class="steps" aria-label="Steps">
      <li v-for="(s, i) in STEPS" :key="s.id">
        <button type="button" :aria-current="store.step === s.id ? 'step' : undefined" :disabled="!!blocked(s.id)" :title="blocked(s.id) ?? undefined" @click="go(s.id)">
          <i>{{ i + 1 }}</i>{{ s.name }}
        </button>
      </li>
    </ol>

    <div class="head">
      <template v-if="store.step === 'room'">
        <h1>Start with the <b>room</b>.</h1>
        <p class="lead">Open a scan and trace the walls on top of it, or drag the corners until the outline matches the room.</p>
      </template>
      <template v-else-if="store.step === 'zones'">
        <h1>Where is the noise, and where should it be <b>quiet</b>?</h1>
        <p class="lead">Add each noise source and each area that should be quiet, then drag them into place.</p>
      </template>
      <template v-else-if="store.step === 'panels'">
        <h1>How many <b>panels</b>?</h1>
        <p class="lead">Choose the panels you have. The app simulates the room with them in different places and keeps the quietest layout.</p>
      </template>
      <template v-else>
        <h1>Put the {{ words[store.placedScreens] }} <b>here</b>.</h1>
        <p class="lead">
          Out of <b>{{ store.layouts.length }} layouts</b> simulated on Allsolve, this one leaves
          {{ store.office.quiet_zones.length ? 'the quiet zones' : 'the desks' }} quietest.
        </p>
      </template>
    </div>

    <div class="grid">
      <div class="col">
        <div class="panel">
          <div class="seg viewswitch" role="group" aria-label="View">
            <button type="button" :aria-pressed="!show3d" @click="show3d = false">Plan</button>
            <button type="button" :aria-pressed="show3d" @click="show3d = true">3D</button>
          </div>

          <template v-if="show3d">
            <Office3D :office="office3d" :params="store.params" :best="store.best" :scan="store.scan" :scan-placement="store.scanPlacement" />
            <p class="cap">
              Drag to turn the room, scroll to zoom.
              <template v-if="store.scan"> The blue shape is your scan.</template>
            </p>
          </template>
          <template v-else-if="store.step === 'result' && store.best && store.baseline">
            <OfficePlan :office="store.office" :params="store.params" :before="store.baseline" :after="store.best" />
            <p class="cap">Each panel is numbered and measured from its centre to the nearer walls. The levels in the quiet zones are before → after.</p>
          </template>
          <OfficeEditor v-else />
        </div>

        <details v-if="store.step === 'result' || store.logEntries.length" class="panel more">
          <summary>Details of the simulation</summary>
          <template v-if="store.hasResult">
            <h2>Every layout tested</h2>
            <SearchChart :layouts="store.layouts" :n-screens="store.placedScreens" />
            <p class="cap">
              Each dot is one layout. The line is the best noise score found so far. Lower is quieter; 100 is the room with no panels.
              <a v-if="store.projectUrl" :href="store.projectUrl" target="_blank" rel="noopener">Open the project in Allsolve</a>
            </p>
          </template>
          <RunLog />
        </details>
      </div>

      <div class="col">
        <div v-if="store.step === 'room'" class="panel">
          <h2>1. Room</h2>
          <p class="hint">A scan is drawn to scale under the plan. Choose <b>Trace the room</b> and click each corner in turn.</p>
          <p class="hint">Without a scan, drag the corners. The length of each wall is shown beside it.</p>
          <button type="button" class="btn next" @click="go('zones')">Next: noise and quiet zones</button>
        </div>

        <div v-else-if="store.step === 'zones'" class="panel">
          <h2>2. Noise and quiet zones</h2>
          <ul class="facts">
            <li>Noise sources <b>{{ store.office.sources.length }}</b></li>
            <li>Quiet zones <b>{{ store.office.quiet_zones.length }}</b></li>
          </ul>
          <p class="hint">Select a noise source to set how loud it is. Drag the corner of a quiet zone to resize it.</p>
          <button type="button" class="btn next" :disabled="!!blocked('panels')" @click="go('panels')">Next: panels</button>
          <p v-if="store.officeBlockedReason" class="hint">{{ store.officeBlockedReason }}</p>
        </div>

        <ControlPanel v-else-if="store.step === 'panels'" />

        <template v-else-if="store.best && store.baseline">
          <ScoreCard :baseline="store.baseline" :best="store.best" :zones="store.office.quiet_zones" />
          <PlacementList :office="store.office" :best="store.best" :screen-length="store.screenLength" />
          <button type="button" class="btn ghost" @click="go('panels')">Change the panels</button>
        </template>
      </div>
    </div>

    <footer v-if="store.step === 'result'" class="note">
      The levels are simulated for this model of the room. They compare layouts with each other and are not a certified measurement of the real room.
    </footer>
  </main>
</template>
