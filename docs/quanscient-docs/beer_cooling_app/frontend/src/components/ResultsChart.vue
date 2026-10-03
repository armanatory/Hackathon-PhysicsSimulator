<script setup lang="ts">
import { computed, ref, watch, onMounted } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
  type ChartOptions,
  type ChartData,
} from 'chart.js'
import { useSimulationStore } from '@/stores/simulationStore'

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
)

const store = useSimulationStore()

const chartData = computed<ChartData<'line'>>(() => {
  const history = store.temperatureHistory
  const playbackIdx = store.playbackIndex

  const playedData = history.slice(0, playbackIdx + 1).map(p => p.temperature_celsius)
  const remainingData = history.slice(playbackIdx).map(p => p.temperature_celsius)

  const paddedPlayed = [...playedData, ...Array(history.length - playedData.length).fill(null)]
  const paddedRemaining = [...Array(playbackIdx).fill(null), ...remainingData]

  return {
    labels: history.map(p => Math.round(p.time_seconds / 60).toString()),
    datasets: [
      {
        label: 'Temperature (played)',
        data: paddedPlayed,
        borderColor: '#6644D8',
        backgroundColor: 'rgba(102, 68, 216, 0.08)',
        borderWidth: 2.5,
        fill: true,
        tension: 0.4,
        pointRadius: 0,
        pointHoverRadius: 5,
      },
      {
        label: 'Temperature (remaining)',
        data: paddedRemaining,
        borderColor: 'rgba(189, 189, 189, 0.4)',
        backgroundColor: 'transparent',
        borderWidth: 1.5,
        borderDash: [5, 5],
        fill: false,
        tension: 0.4,
        pointRadius: 0,
      },
      {
        label: 'Target',
        data: Array(history.length).fill(store.params.target_temp_celsius),
        borderColor: '#22c55e',
        backgroundColor: 'transparent',
        borderWidth: 1,
        borderDash: [10, 5],
        fill: false,
        pointRadius: 0,
      },
    ],
  }
})

const chartOptions = computed<ChartOptions<'line'>>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  animation: {
    duration: 0,
  },
  interaction: {
    mode: 'index',
    intersect: false,
  },
  plugins: {
    legend: {
      display: false,
    },
    tooltip: {
      backgroundColor: 'rgba(33, 33, 33, 0.9)',
      titleColor: '#fff',
      bodyColor: '#E0E0E0',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      borderWidth: 1,
      padding: 10,
      displayColors: false,
      titleFont: { family: 'Inter' },
      bodyFont: { family: 'Inter' },
      callbacks: {
        title: (items) => `Time: ${items[0].label} min`,
        label: (item) => {
          if (item.dataset.label?.includes('Target')) {
            return `Target: ${item.raw}°C`
          }
          if (item.raw === null) return ''
          return `Temperature: ${(item.raw as number).toFixed(1)}°C`
        },
      },
    },
  },
  scales: {
    x: {
      title: {
        display: true,
        text: 'Time (minutes)',
        color: '#757575',
        font: { family: 'Inter', size: 11 },
      },
      grid: {
        color: 'rgba(224, 224, 224, 0.5)',
      },
      ticks: {
        color: '#757575',
        maxTicksLimit: 10,
        font: { family: 'Inter', size: 10 },
      },
    },
    y: {
      title: {
        display: true,
        text: 'Temperature (°C)',
        color: '#757575',
        font: { family: 'Inter', size: 11 },
      },
      grid: {
        color: 'rgba(224, 224, 224, 0.5)',
      },
      ticks: {
        color: '#757575',
        font: { family: 'Inter', size: 10 },
      },
      min: Math.min(store.coolingSpec.coolant_temp_celsius - 5, -10),
      max: Math.max(store.params.initial_temp_celsius + 5, 30),
    },
  },
}))
</script>

<template>
  <div class="h-[400px]">
    <Line :data="chartData" :options="chartOptions" />
  </div>
</template>
