/**
 * Type definitions for the Beer Cooling Simulator
 */

export type ContainerShape = 'can' | 'bottle' | 'pint'
export type CoolingMethod = 'ice_water' | 'refrigerator' | 'freezer' | 'salt_ice'

export interface SimulationParams {
  container_shape: ContainerShape
  cooling_method: CoolingMethod
  initial_temp_celsius: number
  target_temp_celsius: number
  immersion_level: number
  simulation_duration_minutes: number
}

export interface TemperaturePoint {
  time_seconds: number
  temperature_celsius: number
}

export interface SimulationResponse {
  simulation_id: string
  project_id: string
  status: string
  message: string
}

export interface SimulationStatus {
  simulation_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  current_time_seconds?: number
  current_temperature_celsius?: number
  message?: string
}

export interface SimulationResults {
  simulation_id: string
  status: string
  temperature_history: TemperaturePoint[]
  time_to_target_seconds?: number
  final_temperature_celsius: number
  total_simulation_time_seconds: number
  parameters: SimulationParams
}

// Container specifications for visualization
export interface ContainerSpec {
  radius: number
  height: number
  wall_thickness: number
  volume_ml: number
  label: string
  color: string
}

export const CONTAINER_SPECS: Record<ContainerShape, ContainerSpec> = {
  can: {
    radius: 0.033,
    height: 0.122,
    wall_thickness: 0.0002,
    volume_ml: 330,
    label: 'Beer Can (330ml)',
    color: '#C0C0C0',
  },
  bottle: {
    radius: 0.035,
    height: 0.230,
    wall_thickness: 0.003,
    volume_ml: 500,
    label: 'Bottle (500ml)',
    color: '#8B4513',
  },
  pint: {
    radius: 0.042,
    height: 0.150,
    wall_thickness: 0.004,
    volume_ml: 568,
    label: 'Pint Glass (568ml)',
    color: '#F5F5DC',
  },
}

export interface CoolingSpec {
  h_submerged: number
  h_exposed: number
  coolant_temp_celsius: number
  label: string
  emoji: string
}

export const COOLING_SPECS: Record<CoolingMethod, CoolingSpec> = {
  ice_water: {
    h_submerged: 600,
    h_exposed: 10,
    coolant_temp_celsius: 0,
    label: 'Ice Water Bath',
    emoji: '🧊',
  },
  refrigerator: {
    h_submerged: 10,
    h_exposed: 10,
    coolant_temp_celsius: 4,
    label: 'Refrigerator',
    emoji: '❄️',
  },
  freezer: {
    h_submerged: 15,
    h_exposed: 15,
    coolant_temp_celsius: -18,
    label: 'Freezer',
    emoji: '🥶',
  },
  salt_ice: {
    h_submerged: 800,
    h_exposed: 10,
    coolant_temp_celsius: -5,
    label: 'Salt & Ice',
    emoji: '🧂',
  },
}

export function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export function formatTemperature(celsius: number): string {
  return `${celsius.toFixed(1)}°C`
}

