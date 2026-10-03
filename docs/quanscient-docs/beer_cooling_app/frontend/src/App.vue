<script setup lang="ts">
import { computed } from 'vue'
import { useSimulationStore } from '@/stores/simulationStore'
import ParameterPanel from '@/components/ParameterPanel.vue'
import GeometryViewer from '@/components/GeometryViewer.vue'
import ResultsChart from '@/components/ResultsChart.vue'
import TemperatureDisplay from '@/components/TemperatureDisplay.vue'

const store = useSimulationStore()

const showResults = computed(() => store.hasResults)
</script>

<template>
  <div class="min-h-screen text-grey-900">
    <!-- Header -->
    <header class="bg-white border-b border-grey-200 sticky top-0 z-50">
      <div class="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <svg viewBox="0 0 32 32" class="w-8 h-8" fill="none">
            <rect width="32" height="32" rx="6" fill="#6644D8"/>
            <path d="M8 22V10l8 6-8 6z" fill="white"/>
            <path d="M16 22V10l8 6-8 6z" fill="white" opacity="0.6"/>
          </svg>
          <div>
            <h1 class="text-xl font-semibold text-grey-900">
              Beer Cooling Simulator
            </h1>
            <p class="text-xs text-grey-500 tracking-wide">Powered by Quanscient Allsolve</p>
          </div>
        </div>

        <a
          href="https://quanscient.com"
          target="_blank"
          class="text-sm text-primary-500 hover:text-primary-700 font-medium transition-colors"
        >
          quanscient.com →
        </a>
      </div>
    </header>

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-6 py-6">
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Left Panel: Parameters -->
        <div class="lg:col-span-1">
          <ParameterPanel />
        </div>

        <!-- Center Panel: 3D View & Temperature -->
        <div class="lg:col-span-1 space-y-6">
          <div class="card p-4 h-[400px]">
            <GeometryViewer />
          </div>
          <TemperatureDisplay />
        </div>

        <!-- Right Panel: Results Chart -->
        <div class="lg:col-span-1">
          <div class="card p-6 h-full min-h-[500px]">
            <h2 class="text-base font-semibold text-grey-900 mb-4 flex items-center gap-2">
              <svg class="w-5 h-5 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
              </svg>
              Temperature vs Time
            </h2>

            <div v-if="showResults">
              <ResultsChart />
            </div>

            <div v-else class="h-[400px] flex items-center justify-center text-grey-400">
              <div class="text-center">
                <svg class="w-12 h-12 mx-auto mb-3 text-grey-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"/>
                </svg>
                <p class="text-sm font-medium text-grey-500">Run a simulation to see results</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Info Section -->
      <section class="mt-8 card p-8">
        <h2 class="text-lg font-semibold text-grey-900 mb-6 flex items-center gap-2">
          <svg class="w-5 h-5 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5"/>
          </svg>
          The Physics
        </h2>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-8 text-sm">
          <div>
            <h3 class="font-semibold text-primary-600 mb-2">Governing Equation</h3>
            <div class="font-mono bg-grey-50 border border-grey-200 p-3 rounded-lg text-grey-800">
              ρ Cₚ ∂T/∂t = ∇ · (k ∇T)
            </div>
            <p class="mt-2 text-grey-600">
              Transient heat conduction equation solved using finite element method.
            </p>
          </div>

          <div>
            <h3 class="font-semibold text-primary-600 mb-2">Boundary Conditions</h3>
            <div class="font-mono bg-grey-50 border border-grey-200 p-3 rounded-lg text-grey-800">
              q = h (T_surface - T_coolant)
            </div>
            <p class="mt-2 text-grey-600">
              Convective heat transfer at the can/bottle surface with different coefficients for submerged and exposed areas.
            </p>
          </div>

          <div>
            <h3 class="font-semibold text-primary-600 mb-2">Heat Transfer Coefficients</h3>
            <ul class="space-y-1 text-grey-600">
              <li><span class="text-grey-900 font-medium">Ice water:</span> h = 600 W/(m²·K)</li>
              <li><span class="text-grey-900 font-medium">Air (fridge):</span> h = 10 W/(m²·K)</li>
              <li><span class="text-grey-900 font-medium">Freezer:</span> h = 15 W/(m²·K)</li>
            </ul>
          </div>
        </div>
      </section>
    </main>

    <!-- Footer -->
    <footer class="border-t border-grey-200 mt-8 py-5 bg-white">
      <div class="max-w-7xl mx-auto px-6 text-center text-xs text-grey-500">
        <p>
          Built with Vue 3, TresJS, and the Quanscient Allsolve SDK
        </p>
      </div>
    </footer>
  </div>
</template>
