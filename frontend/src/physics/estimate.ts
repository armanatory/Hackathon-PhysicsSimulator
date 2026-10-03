/**
 * Quick acoustic estimate that runs in the browser.
 *
 * Geometric acoustics: direct path, first wall reflections and diffraction around screen
 * ends. It draws the sound map and gives an instant answer while the backend is offline or
 * an Allsolve run is still going. It is NOT the solver: real results come from the backend.
 */

import type { LayoutResult, Office, OptimizationParams, Slot } from '@/types'

const SPEED_OF_SOUND = 343
const SCREEN_MAX_LOSS_DB = 14 // sound also passes over a free-standing screen
const WALL_REFLECTION = 0.36
const REVERB_DB = 38

interface Segment {
  x1: number
  y1: number
  x2: number
  y2: number
  length: number
}

type SearchParams = Pick<OptimizationParams, 'n_screens' | 'screen_length_m' | 'frequencies_hz' | 'strategy'>

export function segmentOf(slot: Slot, length: number): Segment {
  const half = length / 2
  return slot.orientation === 'v'
    ? { x1: slot.x, y1: slot.y - half, x2: slot.x, y2: slot.y + half, length }
    : { x1: slot.x - half, y1: slot.y, x2: slot.x + half, y2: slot.y, length }
}

function segmentsOf(office: Office, slotIds: number[], length: number): Segment[] {
  return slotIds.map((id) => segmentOf(office.slots.find((s) => s.id === id)!, length))
}

function dist(ax: number, ay: number, bx: number, by: number): number {
  return Math.hypot(ax - bx, ay - by)
}

/** Extra path length around the nearer end of a screen, or -1 when it is not in the way. */
function detour(sx: number, sy: number, rx: number, ry: number, g: Segment): number {
  const gx = g.x2 - g.x1, gy = g.y2 - g.y1, px = rx - sx, py = ry - sy
  const d1 = gx * (sy - g.y1) - gy * (sx - g.x1), d2 = gx * (ry - g.y1) - gy * (rx - g.x1)
  const d3 = px * (g.y1 - sy) - py * (g.x1 - sx), d4 = px * (g.y2 - sy) - py * (g.x2 - sx)
  if (d1 * d2 >= 0 || d3 * d4 >= 0) return -1
  return (
    Math.min(
      dist(sx, sy, g.x1, g.y1) + dist(g.x1, g.y1, rx, ry),
      dist(sx, sy, g.x2, g.y2) + dist(g.x2, g.y2, rx, ry),
    ) - dist(sx, sy, rx, ry)
  )
}

/** The talker plus its mirror image in each wall. */
function sources(office: Office) {
  const { x, y } = office.source
  return [
    { x, y, a: 1 },
    { x: -x, y, a: WALL_REFLECTION },
    { x: 2 * office.width_m - x, y, a: WALL_REFLECTION },
    { x, y: -y, a: WALL_REFLECTION },
    { x, y: 2 * office.height_m - y, a: WALL_REFLECTION },
  ]
}

function reverbEnergy(segments: Segment[]): number {
  const absorbing = segments.reduce((sum, g) => sum + g.length, 0)
  return Math.pow(10, (REVERB_DB - 0.8 * absorbing) / 10)
}

/**
 * Speech level in dB at a point, energy-averaged over the bands.
 * With coherent=true the bands up to 500 Hz keep their phase so the map shows interference.
 */
function levelAt(
  x: number,
  y: number,
  srcs: ReturnType<typeof sources>,
  segments: Segment[],
  reverb: number,
  frequencies: number[],
  coherent: boolean,
): number {
  const n = frequencies.length
  const energy = new Array<number>(n).fill(0)
  const re = new Array<number>(n).fill(0)
  const im = new Array<number>(n).fill(0)
  for (const s of srcs) {
    const r = Math.max(dist(s.x, s.y, x, y), 0.3)
    const base = (s.a * 1e6) / (r * r) // 60 dB at 1 m
    const detours: number[] = []
    for (const g of segments) {
      const d = detour(s.x, s.y, x, y, g)
      if (d >= 0) detours.push(d)
    }
    for (let b = 0; b < n; b++) {
      let loss = 0
      for (const d of detours) {
        loss += Math.min(SCREEN_MAX_LOSS_DB, 10 * Math.log10(3 + (40 * d * frequencies[b]) / SPEED_OF_SOUND))
      }
      const e = base * Math.pow(10, -Math.min(loss, 26) / 10)
      energy[b] += e
      if (coherent && frequencies[b] <= 500) {
        const amp = Math.sqrt(e), phase = (2 * Math.PI * frequencies[b] * r) / SPEED_OF_SOUND
        re[b] += amp * Math.cos(phase)
        im[b] += amp * Math.sin(phase)
      }
    }
  }
  let total = 0
  for (let b = 0; b < n; b++) {
    let e = energy[b]
    if (coherent && frequencies[b] <= 500) e = 0.55 * e + 0.45 * (re[b] * re[b] + im[b] * im[b])
    total += e + reverb
  }
  return 10 * Math.log10(total / n)
}

function rawScore(levels: number[]): number {
  const pressures = levels.map((l) => Math.pow(10, l / 20))
  return pressures.reduce((a, b) => a + b, 0) / pressures.length + 0.5 * Math.max(...pressures)
}

function evaluate(office: Office, slotIds: number[], params: SearchParams) {
  const segments = segmentsOf(office, slotIds, params.screen_length_m)
  const srcs = sources(office), reverb = reverbEnergy(segments)
  const levels = office.desks.map((d) => levelAt(d.x, d.y, srcs, segments, reverb, params.frequencies_hz, false))
  return { levels, raw: rawScore(levels) }
}

function combinations(ids: number[], k: number): number[][] {
  if (k === 0) return [[]]
  const out: number[][] = []
  ids.forEach((id, i) => {
    for (const rest of combinations(ids.slice(i + 1), k - 1)) out.push([id, ...rest])
  })
  return out
}

/**
 * The same search the backend runs on Allsolve, with the estimate standing in for the solver.
 * Returns every layout in the order tested; the untreated office is first.
 */
export function estimateSearch(office: Office, params: SearchParams): LayoutResult[] {
  const base = evaluate(office, [], params)
  const result = (slotIds: number[]): LayoutResult => {
    const e = evaluate(office, slotIds, params)
    return { slot_ids: slotIds, desk_levels_db: e.levels, score: (100 * e.raw) / base.raw }
  }
  const results: LayoutResult[] = [{ slot_ids: [], desk_levels_db: base.levels, score: 100 }]
  const ids = office.slots.map((s) => s.id)

  if (params.strategy === 'exhaustive') {
    for (const combo of combinations(ids, params.n_screens)) results.push(result(combo))
    return results
  }
  let chosen: number[] = []
  for (let k = 0; k < params.n_screens; k++) {
    const round = ids.filter((id) => !chosen.includes(id)).map((id) => result([...chosen, id]))
    results.push(...round)
    chosen = round.reduce((best, r) => (r.score < best.score ? r : best)).slot_ids
  }
  return results
}

/** Best layout that uses exactly n screens. */
export function bestOf(layouts: LayoutResult[], nScreens: number): LayoutResult | null {
  const full = layouts.filter((l) => l.slot_ids.length === nScreens)
  return full.length ? full.reduce((best, l) => (l.score < best.score ? l : best)) : null
}

// ---------------------------------------------------------------------------
// Drawing
// ---------------------------------------------------------------------------

const STOPS: [number, [number, number, number]][] = [
  [36, [241, 243, 236]],
  [42, [248, 220, 195]],
  [48, [244, 165, 126]],
  [54, [224, 86, 106]],
  [60, [142, 31, 79]],
]

export function levelRGB(level: number): [number, number, number] {
  if (level <= STOPS[0][0]) return STOPS[0][1]
  for (let i = 1; i < STOPS.length; i++) {
    if (level <= STOPS[i][0]) {
      const [l0, c0] = STOPS[i - 1], [l1, c1] = STOPS[i], f = (level - l0) / (l1 - l0)
      return [c0[0] + (c1[0] - c0[0]) * f, c0[1] + (c1[1] - c0[1]) * f, c0[2] + (c1[2] - c0[2]) * f]
    }
  }
  return STOPS[STOPS.length - 1][1]
}

export function levelColor(level: number): string {
  const [r, g, b] = levelRGB(level)
  return `rgb(${Math.round(r)},${Math.round(g)},${Math.round(b)})`
}

/** Paint the estimated sound map of one layout onto a canvas. */
export function paintField(canvas: HTMLCanvasElement, office: Office, slotIds: number[], params: SearchParams): void {
  const width = 320, height = Math.round((320 * office.height_m) / office.width_m)
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const image = ctx.createImageData(width, height)
  const segments = segmentsOf(office, slotIds, params.screen_length_m)
  const srcs = sources(office), reverb = reverbEnergy(segments)
  let o = 0
  for (let py = 0; py < height; py++) {
    for (let px = 0; px < width; px++) {
      const x = ((px + 0.5) * office.width_m) / width, y = ((py + 0.5) * office.height_m) / height
      const [r, g, b] = levelRGB(levelAt(x, y, srcs, segments, reverb, params.frequencies_hz, true))
      image.data[o++] = r
      image.data[o++] = g
      image.data[o++] = b
      image.data[o++] = 255
    }
  }
  ctx.putImageData(image, 0, 0)
}
