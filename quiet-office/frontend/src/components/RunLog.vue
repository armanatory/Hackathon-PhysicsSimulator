<script setup lang="ts">
/**
 * Proof of where the numbers come from: the live log of every request sent to Allsolve and
 * every answer, the cloud jobs, and the raw pressures the solver returned next to the quick
 * estimate for the same layout.
 */
import { computed, ref } from 'vue'
import { useOptimizationStore } from '@/stores/optimizationStore'

const store = useOptimizationStore()
const showSolver = ref(false)

const KIND_LABEL: Record<string, string> = { sent: 'sent', received: 'received', solver: 'solver', info: 'local', error: 'error' }

const entries = computed(() => (showSolver.value ? store.logEntries : store.logEntries.filter((e) => e.kind !== 'solver')))
const solverLines = computed(() => store.logEntries.filter((e) => e.kind === 'solver').length)

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60), s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

/** Raw pressure at a listening point: source 0, each band, in millipascal. */
function pressure(values: number[][] | undefined): string {
  if (!values?.length) return '–'
  return values[0].map((v) => (v * 1000).toFixed(1)).join(' / ')
}
</script>

<template>
  <div class="panel runlog">
    <h2>Where these numbers come from</h2>

    <p v-if="!store.hasResult && !store.logEntries.length" class="cap" style="margin-top: 0">
      Nothing has been sent to Allsolve yet. Every request and answer of a simulation will be listed here.
    </p>

    <template v-else>
      <p class="cap" style="margin-top: 0">
        <template v-if="store.isRunning">Running on Allsolve now. Each line is a request this app sent or an answer it received.</template>
        <template v-else-if="store.hasResult">
          The levels on this page are calculated from pressures returned by <b>Allsolve</b>. The record below shows every step.
        </template>
        <template v-else>The last Allsolve run did not finish, so there is no result. The record shows how far it got.</template>
      </p>

      <ul v-if="store.evidence" class="facts">
        <li>
          Allsolve project
          <b
            ><a :href="store.evidence.project_url" target="_blank" rel="noopener">{{ store.evidence.project_id }}</a></b
          >
        </li>
        <li>Model <b>{{ store.evidence.model === '3d' ? '3D room' : '2D slice' }}</b></li>
        <li>Solves on Allsolve <b>{{ store.evidence.solves }}</b></li>
        <li>
          Cloud jobs
          <b>{{ store.evidence.jobs.filter((j) => j.kind === 'mesh').length }} mesh, {{ store.evidence.jobs.filter((j) => j.kind === 'simulation').length }} simulation</b>
        </li>
      </ul>

      <div v-if="store.comparison.length" class="compare">
        <h3>Allsolve against the quick estimate, for the chosen layout</h3>
        <table class="t">
          <thead>
            <tr>
              <th>Listening point</th>
              <th>Estimate</th>
              <th>Allsolve</th>
              <th>Difference</th>
              <th title="Pressure amplitude returned by the solver, per speech band">Solver pressure, mPa</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in store.comparison" :key="row.label">
              <td>{{ row.label }}</td>
              <td>{{ row.estimate.toFixed(1) }} dB</td>
              <td><b>{{ row.allsolve.toFixed(1) }} dB</b></td>
              <td>{{ row.allsolve - row.estimate >= 0 ? '+' : '' }}{{ (row.allsolve - row.estimate).toFixed(1) }}</td>
              <td>{{ pressure(row.pressures) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="cap">
          Noise score for this layout: estimate <b>{{ store.estimateScoreForBest?.toFixed(0) ?? '–' }}</b>, Allsolve
          <b>{{ store.best?.score.toFixed(0) }}</b
          >. The two differ because the estimate is a rule of thumb and Allsolve solves the wave equation.
        </p>
      </div>

      <div class="logbar">
        <h3>Record of the run</h3>
        <label v-if="solverLines"><input v-model="showSolver" type="checkbox" /> show {{ solverLines }} lines from the cloud jobs</label>
        <button type="button" class="btn ghost small" @click="store.downloadLog()">Download the whole log</button>
      </div>
      <ol class="log" aria-live="polite">
        <li v-for="entry in entries" :key="entry.index" :data-kind="entry.kind">
          <span class="time">{{ clock(entry.elapsed_s) }}</span>
          <span class="kind">{{ KIND_LABEL[entry.kind] ?? entry.kind }}</span>
          <span class="message">
            {{ entry.message }}
            <details v-if="entry.data">
              <summary>data</summary>
              <pre>{{ JSON.stringify(entry.data, null, 1) }}</pre>
            </details>
          </span>
        </li>
      </ol>
    </template>

    <div class="explain">
      <div class="logbar">
        <h3>In plain language</h3>
        <button type="button" class="btn small" :disabled="!store.canExplain || store.explaining" @click="store.explain()">
          {{ store.explaining ? 'Writing…' : store.explanation ? 'Explain again' : store.explainsEarlierRun ? 'Explain the last Allsolve run' : 'Explain this run' }}
        </button>
      </div>
      <p v-if="store.explanation" class="explanation">{{ store.explanation }}</p>
      <p v-if="store.explanation" class="cap">Written by an AI model ({{ store.explanationModel }}) from the figures and the record above. It explains; it does not calculate.</p>
      <p v-else-if="store.explainBlockedReason" class="cap">{{ store.explainBlockedReason }}</p>
      <p v-else-if="store.explainsEarlierRun" class="cap">
        This explains the Allsolve run that finished at
        {{ new Date(store.explainsEarlierRun).toLocaleTimeString() }}; the office or the settings have changed since.
      </p>
      <p v-else class="cap">An AI model reads the Allsolve result and the record above and explains them without jargon.</p>
      <p v-if="store.explainError" class="error" role="alert">{{ store.explainError }}</p>
    </div>
  </div>
</template>
