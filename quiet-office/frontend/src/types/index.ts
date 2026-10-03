/**
 * Types shared with the backend (backend/app/models/office.py)
 */

export interface Point {
  x: number
  y: number
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
  source: Point
  desks: Point[]
  slots: Slot[]
}

export type Strategy = 'greedy' | 'exhaustive'

export interface OptimizationParams {
  office: Office
  n_screens: number
  screen_length_m: number
  screen_thickness_m: number
  frequencies_hz: number[]
  strategy: Strategy
}

export interface LayoutResult {
  slot_ids: number[]
  desk_levels_db: number[]
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
}

export interface OptimizationResults {
  optimization_id: string
  status: string
  baseline: LayoutResult
  best: LayoutResult
  layouts: LayoutResult[]
  project_url: string | null
  parameters: OptimizationParams
}

export interface Capabilities {
  sdk_installed: boolean
  credentials_configured: boolean
  host: string
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
    source: { x: 2.2, y: 5 },
    desks,
    slots: slots.map(([x, y, orientation, label], id) => ({ id, x, y, orientation, label })),
  }
}
