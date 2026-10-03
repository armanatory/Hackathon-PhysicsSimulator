/**
 * Small 2D helpers for the floor plan. All coordinates are metres, x to the right, y down.
 */

import type { Point } from '@/types'

export interface Bounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
  width: number
  height: number
}

export function boundsOf(points: Point[], pad = 0): Bounds {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (const p of points) {
    if (p.x < minX) minX = p.x
    if (p.y < minY) minY = p.y
    if (p.x > maxX) maxX = p.x
    if (p.y > maxY) maxY = p.y
  }
  if (!points.length) minX = minY = maxX = maxY = 0
  minX -= pad
  minY -= pad
  maxX += pad
  maxY += pad
  return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY }
}

/** Even-odd test. Points exactly on an edge may land on either side. */
export function pointInPolygon(x: number, y: number, polygon: Point[]): boolean {
  let inside = false
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const a = polygon[i], b = polygon[j]
    if (a.y > y !== b.y > y && x < ((b.x - a.x) * (y - a.y)) / (b.y - a.y) + a.x) inside = !inside
  }
  return inside
}

/** A point that is certainly inside the polygon: the vertex average if that works, else a search. */
export function interiorPoint(polygon: Point[]): Point {
  const cx = polygon.reduce((s, p) => s + p.x, 0) / polygon.length
  const cy = polygon.reduce((s, p) => s + p.y, 0) / polygon.length
  if (pointInPolygon(cx, cy, polygon)) return { x: snap(cx), y: snap(cy) }
  const b = boundsOf(polygon)
  for (let y = b.minY + 0.25; y < b.maxY; y += 0.5) {
    for (let x = b.minX + 0.25; x < b.maxX; x += 0.5) {
      if (pointInPolygon(x, y, polygon)) return { x: snap(x), y: snap(y) }
    }
  }
  return { x: snap(cx), y: snap(cy) }
}

export function snap(value: number, step = 0.1): number {
  return Number((Math.round(value / step) * step).toFixed(3))
}

/** SVG path for a closed polygon, scaled by `unit` drawing units per metre. */
export function polygonPath(polygon: Point[], unit: number): string {
  return polygon.map((p, i) => `${i ? 'L' : 'M'}${(p.x * unit).toFixed(2)} ${(p.y * unit).toFixed(2)}`).join('') + 'Z'
}
