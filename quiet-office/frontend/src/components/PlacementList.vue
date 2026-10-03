<script setup lang="ts">
import { computed } from 'vue'
import type { LayoutResult, Office } from '@/types'

const props = defineProps<{
  office: Office
  best: LayoutResult
  screenLength: number
}>()

const placed = computed(() => props.best.slot_ids.map((id) => props.office.slots.find((s) => s.id === id)!))
</script>

<template>
  <div class="panel">
    <h2>Where they go</h2>
    <ul class="where">
      <li v-for="slot in placed" :key="slot.id">
        <span>
          {{ slot.label }}
          <small>{{ screenLength }} m screen at {{ slot.x.toFixed(1) }} m, {{ slot.y.toFixed(1) }} m</small>
        </span>
      </li>
    </ul>
  </div>
</template>
