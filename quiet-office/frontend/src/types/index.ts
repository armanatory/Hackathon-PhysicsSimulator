/**
 * Types shared with the backend (backend/app/models/office.py)
 */

export interface Point {
  x: number
  y: number
}

/** Something that makes noise: a conversation, a printer, a coffee machine. */
export interface NoiseSource extends Point {
  /** Level 1 m away. Normal speech is about 60 dB. */
  level_db: number
  label: string
}

/** A rectangular area that should be quiet. x, y is its top-left corner. */
export interface QuietZone {
  x: number
  y: number
  width: number
  height: number
  label: string
}

export interface Slot {
  id: number
  x: number
  y: number
  orientation: 'h' | 'v'
  label: string
}

export interface Office {
  /** Room corners in order, metres. The last corner joins back to the first. */
  outline: Point[]
  /** Floor to ceiling, metres. */
  ceiling_height_m: number
  sources: NoiseSource[]
  desks: Point[]
  quiet_zones: QuietZone[]
  slots: Slot[]
}

export type Strategy = 'greedy' | 'exhaustive' | 'fast'
export type SimulationModel = '2d' | '3d'

export interface PanelType {
  id: string
  name: string
  height_m: number
  note: string
}

/** The panels people actually buy differ mostly in height. */
export const PANEL_TYPES: PanelType[] = [
  { id: 'divider', name: 'Desk divider', height_m: 1.2, note: 'sits on or beside the desk' },
  { id: 'screen', name: 'Acoustic screen', height_m: 1.6, note: 'free-standing, head height when seated' },
  { id: 'partition', name: 'Tall partition', height_m: 2.0, note: 'blocks standing talkers too' },
]

export interface OptimizationParams {
  office: Office
  n_screens: number
  screen_length_m: number
  screen_thickness_m: number
  /** Panel height, metres. Sound passes over anything lower than the ceiling. */
  screen_height_m: number
  /** True: panel faces absorb sound. False: they reflect it. */
  screen_absorbing: boolean
  /** What the backend solves on Allsolve: a full 3D room, or a 2D top-down slice. */
  model: SimulationModel
  /** How many sweeps each round of layouts is split into. 1 is fastest; not used by the fast search. */
  parallel_jobs: number
  source_height_m: number
  ear_height_m: number
  frequencies_hz: number[]
  strategy: Strategy
  /** Fast search: layouts worth simulating, most promising first. */
  candidate_layouts?: number[][]
  /** Fast search: wall time to aim for, seconds. */
  time_budget_s?: number
}

/** What a fast search can do in the time budget on a given number of machines. */
export interface FastPlan {
  layouts: number
  machines: number
  seconds: number
}

/** Cloud machines held ready on Allsolve for the fast search. */
export interface Machines {
  state: 'off' | 'starting' | 'ready' | 'failed'
  machines: number
  boot_s: number | null
  error: string | null
  idle_limit_s: number
  warm_size: number
  plan_cold: FastPlan
  plan_warm: FastPlan
  /** Warm machines and a room that was searched before: its project and mesh are used again. */
  plan_repeat: FastPlan
  plan_now: FastPlan
}

export interface LayoutResult {
  slot_ids: number[]
  desk_levels_db: number[]
  /** Average level over each quiet zone, same order as office.quiet_zones. */
  zone_levels_db: number[]
  score: number
}

export interface OptimizationResponse {
  optimization_id: string
  status: string
  message: string
}

export interface OptimizationStatus {
  optimization_id: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'aborted'
  progress: number
  message: string | null
  layouts_done: number
  layouts_total: number
  best_score: number | null
  project_url: string | null
  log_size: number
}

export interface OptimizationResults {
  optimization_id: string
  status: string
  baseline: LayoutResult
  best: LayoutResult
  layouts: LayoutResult[]
  project_url: string | null
  parameters: OptimizationParams
  evidence: Evidence | null
}

export interface Capabilities {
  sdk_installed: boolean
  credentials_configured: boolean
  host: string
  ai_configured: boolean
}

/** One line of the run log: something sent to Allsolve, an answer, or a local step. */
export interface LogEntry {
  index: number
  time: string
  elapsed_s: number
  kind: 'sent' | 'received' | 'solver' | 'info' | 'error'
  step: string
  message: string
  data: Record<string, unknown> | null
}

export interface CloudJob {
  kind: 'mesh' | 'simulation'
  id: string
  what: string
  status: string
}

/** What ties a result to Allsolve. Pressures are [listening point][source][band], in pascal. */
export interface Evidence {
  host: string
  project_id: string
  project_url: string
  model: SimulationModel
  jobs: CloudJob[]
  solves: number
  frequencies_hz: number[]
  receivers: Point[]
  reference_pressures_pa: number[][]
  baseline_pressures_pa: number[][][]
  best_pressures_pa: number[][][]
}

/** The four steps of a job, in order. */
export type Step = 'room' | 'zones' | 'panels' | 'result'

/** A desk counts as "in earshot" of the conversation above this speech level. */
export const EARSHOT_DB = 45

const RECTANGLE = (width: number, height: number): Point[] => [
  { x: 0, y: 0 },
  { x: width, y: 0 },
  { x: width, y: height },
  { x: 0, y: height },
]

/** Demo office: a coffee point at one end, two areas that should be quiet at the other. */
export function defaultOffice(): Office {
  return {
    outline: RECTANGLE(16, 10),
    ceiling_height_m: 2.7,
    sources: [{ x: 2.2, y: 5, level_db: 60, label: 'Coffee point' }],
    desks: [],
    quiet_zones: [
      { x: 9.6, y: 1.2, width: 4, height: 2.8, label: 'Focus desks' },
      { x: 9.6, y: 6, width: 4, height: 2.8, label: 'Phone booths' },
    ],
    slots: [],
  }
}

/** An empty room to draw or trace into. */
export function blankOffice(): Office {
  return { outline: RECTANGLE(8, 6), ceiling_height_m: 2.7, sources: [], desks: [], quiet_zones: [], slots: [] }
}
