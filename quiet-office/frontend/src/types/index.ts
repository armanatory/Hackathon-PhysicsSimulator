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

export type Strategy = 'greedy' | 'exhaustive'
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
  /** How many Allsolve jobs each round of layouts is split into and run at the same time. */
  parallel_jobs: number
  source_height_m: number
  ear_height_m: number
  frequencies_hz: number[]
  strategy: Strategy
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

/** Where the numbers on screen came from. */
export type ResultSource = 'estimate' | 'allsolve'

/** A desk counts as "in earshot" of the conversation above this speech level. */
export const EARSHOT_DB = 45

/** Same demo office as backend default_office(), used when the backend is offline. */
export function defaultOffice(): Office {
  const desks: Point[] = []
  for (const [cx, cy] of [[5, 2], [10.5, 2], [4.4, 7], [10.5, 7]]) {
    for (const [dx, dy] of [[0, 0], [1.6, 0], [0, 1.4], [1.6, 1.4]]) {
      desks.push({ x: cx + dx, y: cy + dy })
    }
  }
  const slots: [number, number, 'h' | 'v', string][] = [
    [3.4, 5.0, 'v', 'Directly in front of the coffee point'],
    [3.4, 3.2, 'v', 'Beside the coffee point, north side'],
    [3.4, 6.8, 'v', 'Beside the coffee point, south side'],
    [5.8, 4.4, 'h', 'Along the aisle edge of the near north desks'],
    [5.2, 5.9, 'h', 'Along the aisle edge of the near south desks'],
    [8.4, 2.7, 'v', 'Centre aisle, north end'],
    [8.4, 5.0, 'v', 'Centre aisle, middle'],
    [8.4, 7.7, 'v', 'Centre aisle, south end'],
    [11.3, 4.5, 'h', 'Along the aisle edge of the far north desks'],
    [11.3, 5.9, 'h', 'Along the aisle edge of the far south desks'],
    [9.6, 2.7, 'v', 'In front of the far north desks'],
    [9.6, 7.7, 'v', 'In front of the far south desks'],
  ]
  return {
    outline: [
      { x: 0, y: 0 },
      { x: 16, y: 0 },
      { x: 16, y: 10 },
      { x: 0, y: 10 },
    ],
    ceiling_height_m: 2.7,
    sources: [{ x: 2.2, y: 5, level_db: 60, label: 'Conversation' }],
    desks,
    quiet_zones: [],
    slots: slots.map(([x, y, orientation, label], id) => ({ id, x, y, orientation, label })),
  }
}
