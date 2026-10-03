<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useOptimizationStore } from '@/stores/optimizationStore'
import OfficePlan from '@/components/OfficePlan.vue'
import ControlPanel from '@/components/ControlPanel.vue'
import ScoreCard from '@/components/ScoreCard.vue'
import PlacementList from '@/components/PlacementList.vue'
import SearchChart from '@/components/SearchChart.vue'

const store = useOptimizationStore()
onMounted(() => store.init())

const words = ['', 'one screen', 'two screens', 'three screens']
const improvement = computed(() => (store.best ? Math.round(100 - store.best.score) : 0))
const tested = computed(() => store.layouts.length)
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
      <div class="eyebrow">Open office, {{ store.office.desks.length }} desks · one conversation at the coffee point</div>
      <h1>Put the {{ words[store.nScreens] }} <b>here</b>.</h1>
      <p v-if="store.best && store.baseline" class="lead">
        Out of <b>{{ tested }} layouts</b> {{ store.source === 'allsolve' ? 'simulated on Allsolve' : 'estimated' }}, this one lowers the noise
        score at the desks by <b>{{ improvement }}%</b> and takes
        {{ store.inEarshot(store.baseline) - store.inEarshot(store.best) }} of {{ store.inEarshot(store.baseline) }} desks out of earshot.
      </p>
    </div>

    <div v-if="store.best && store.baseline" class="grid">
      <div class="col">
        <div class="panel">
          <OfficePlan :office="store.office" :params="store.params" :before="store.baseline" :after="store.best" />
          <div class="under">
            <div class="ramp">
              <i></i>
              <div><span>36 dB</span><span>48 dB</span><span>60 dB</span></div>
            </div>
          </div>
          <p class="cap">
            Drag the divider across the room. Dashed lines mark where the screens will stand. The number on each desk is the speech level there; bold
            means the conversation is still in earshot.
            <template v-if="store.source === 'allsolve'"> Desk numbers are from Allsolve; the coloured map is the quick estimate.</template>
          </p>
        </div>

        <div class="panel">
          <h2>Every layout tested</h2>
          <SearchChart :layouts="store.layouts" :n-screens="store.nScreens" />
          <p class="cap">
            Each dot is one layout. The line is the best score found so far. Lower is quieter; 100 is the office with no screens.
            <a v-if="store.projectUrl" :href="store.projectUrl" target="_blank" rel="noopener">Open the project in Allsolve</a>
          </p>
        </div>
      </div>

      <div class="col">
        <ControlPanel />
        <ScoreCard :baseline="store.baseline" :best="store.best" :earshot-before="store.inEarshot(store.baseline)" :earshot-after="store.inEarshot(store.best)" />
        <PlacementList :office="store.office" :best="store.best" :screen-length="store.screenLength" />
      </div>
    </div>

    <footer class="note">
      The score is a relative improvement inside the simulation model, not a certified real-world dB reduction. The quick estimate is a simple
      geometric model that runs in the browser; only results marked "Allsolve simulation" come from the solver.
    </footer>
  </main>
</template>
