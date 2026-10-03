<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted } from 'vue'
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

const words = ['no screens', 'one screen', 'two screens', 'three screens']
const improvement = computed(() => (store.best ? Math.round(100 - store.best.score) : 0))
const tested = computed(() => store.layouts.length)
const hasResult = computed(() => !!store.best && !!store.baseline)
const summary = computed(() => {
  const o = store.office
  const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
  const parts = [count(o.sources.length, 'noise source', 'noise sources')]
  if (o.quiet_zones.length) parts.push(count(o.quiet_zones.length, 'quiet zone', 'quiet zones'))
  if (o.desks.length) parts.push(count(o.desks.length, 'desk', 'desks'))
  return parts.join(' · ')
})
const earshotGain = computed(() => store.inEarshot(store.baseline) - store.inEarshot(store.best))
</script>

<template>
  <header class="bar">
    <div class="wrap">
      <span class="brand"><i></i>QuietOffice</span>
      <span class="source" :data-source="store.source">
        {{ store.source === 'allsolve' ? 'Allsolve simulation' : 'Quick estimate, not yet simulated' }}
      </span>
    </div>
  </header>

  <main class="wrap">
    <div class="head">
      <div class="eyebrow">{{ summary }}</div>
      <h1 v-if="store.view === 'edit'">Draw <b>your</b> office.</h1>
      <h1 v-else-if="hasResult">Put the {{ words[store.placedScreens] }} <b>here</b>.</h1>
      <h1 v-else>Nothing to place <b>yet</b>.</h1>
      <p v-if="store.view === 'edit'" class="lead">
        Place the noise sources, mark the areas that should be quiet, and let the app suggest where screens could stand, or mark those places
        yourself. Open a phone scan to trace a real room. The result updates as you go.
      </p>
      <p v-else-if="store.best && store.baseline" class="lead">
        Out of <b>{{ tested }} layouts</b> {{ store.source === 'allsolve' ? 'simulated on Allsolve' : 'estimated' }}, this one lowers the noise
        score where it should be quiet by <b>{{ improvement }}%</b
        ><template v-if="store.office.desks.length"> and takes {{ earshotGain }} of {{ store.inEarshot(store.baseline) }} desks out of earshot</template>.
      </p>
      <p v-else class="lead">The office needs somewhere to listen (a desk or a quiet zone) and at least one screen position. Add them in the editor.</p>
    </div>

    <div class="tabs" role="tablist" aria-label="View">
      <button type="button" role="tab" :aria-selected="store.view === 'result'" @click="store.view = 'result'">Result</button>
      <button type="button" role="tab" :aria-selected="store.view === '3d'" @click="store.view = '3d'">3D view</button>
      <button type="button" role="tab" :aria-selected="store.view === 'edit'" :disabled="store.isRunning" @click="store.view = 'edit'">Edit office</button>
    </div>

    <div class="grid">
      <div class="col">
        <div v-if="store.view === 'edit'" class="panel">
          <OfficeEditor />
        </div>

        <div v-else-if="store.view === '3d'" class="panel">
          <Office3D :office="store.office" :params="store.params" :best="store.best" :scan="store.scan" :scan-placement="store.scanPlacement" />
          <div class="under">
            <div class="ramp">
              <i></i>
              <div><span>36 dB</span><span>48 dB</span><span>60 dB</span></div>
            </div>
          </div>
          <p class="cap">
            Drag to turn the room, scroll to zoom. Screens stand at the chosen panel height ({{ store.params.screen_height_m.toFixed(1) }} m under a
            {{ store.office.ceiling_height_m.toFixed(2) }} m ceiling); desk tops are coloured by the speech level left at each desk.
            <template v-if="store.scan"> The blue shape is your scan, placed as in the editor.</template>
          </p>
        </div>

        <template v-else-if="store.best && store.baseline">
          <div class="panel">
            <OfficePlan :office="store.office" :params="store.params" :before="store.baseline" :after="store.best" :faded-map="store.source === 'allsolve'" />
            <div class="under">
              <div class="ramp">
                <i></i>
                <div><span>36 dB</span><span>48 dB</span><span>60 dB</span></div>
              </div>
            </div>
            <p class="cap">
              Drag the divider across the room. Dashed lines mark where the screens will stand. The number on each desk is the speech level there;
              bold means the conversation is still in earshot.
              <template v-if="store.source === 'allsolve'">
                <b>The numbers on the desks and zones are from Allsolve.</b> The coloured map behind them is still the quick estimate, faded, because
                Allsolve returns values at the listening points only.
              </template>
            </p>
          </div>

          <div class="panel">
            <h2>Every layout tested</h2>
            <SearchChart :layouts="store.layouts" :n-screens="store.placedScreens" />
            <p class="cap">
              Each dot is one layout. The line is the best score found so far. Lower is quieter; 100 is the office with no screens.
              <a v-if="store.projectUrl" :href="store.projectUrl" target="_blank" rel="noopener">Open the project in Allsolve</a>
            </p>
          </div>
        </template>

        <RunLog v-if="store.view !== 'edit'" />

        <div v-if="store.view === 'result' && !(store.best && store.baseline)" class="panel">
          <p class="cap" style="margin: 0">Open <b>Edit office</b> to add desks or quiet zones, and screen positions.</p>
        </div>
      </div>

      <div class="col">
        <ControlPanel />
        <template v-if="store.best && store.baseline">
          <ScoreCard :baseline="store.baseline" :best="store.best" :zones="store.office.quiet_zones" :earshot-before="store.inEarshot(store.baseline)" :earshot-after="store.inEarshot(store.best)" />
          <PlacementList :office="store.office" :best="store.best" :screen-length="store.screenLength" />
        </template>
      </div>
    </div>

    <footer class="note">
      The score is a relative improvement inside the simulation model, not a certified real-world dB reduction. The quick estimate is a simple
      geometric model that runs in the browser; only results marked "Allsolve simulation" come from the solver.
    </footer>
  </main>
</template>
