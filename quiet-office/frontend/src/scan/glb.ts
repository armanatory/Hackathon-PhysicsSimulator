/**
 * Read a phone scan (.glb) in the browser and cut it into a floor plan.
 *
 * A Polycam Room-mode export is one textured surface mesh in metres with Y up. Nothing in
 * it says "wall", so the floor plan is made by slicing the mesh with a horizontal plane.
 * See docs/scan-import.md.
 */

export type UpAxis = 'x' | 'y' | 'z'

/** How the file's own coordinates are turned into metres with Y pointing up. */
export interface Orientation {
  /** Which of the file's axes points up. Phone scans use y; CAD and BIM exports often use z. */
  up: UpAxis
  /** Turn the model upside down. Nothing in a mesh says which way is up along the axis. */
  flipped: boolean
  /** Metres per file unit: 1 for metres, 0.01 for centimetres, 0.001 for millimetres. */
  unitScale: number
}

export interface ScanMesh {
  /** x, y, z per vertex exactly as in the file, with node transforms applied. */
  raw: Float32Array
  orientation: Orientation
  /** x, y, z per vertex, in metres, Y up. Derived from raw and orientation. */
  positions: Float32Array
  indices: Uint32Array
  floorY: number
  /** Floor to ceiling in metres, or null when the scan shows no clear ceiling. */
  ceilingHeight: number | null
  triangles: number
}

const GLB_MAGIC = 0x46546c67 // "glTF"
const CHUNK_JSON = 0x4e4f534a
const CHUNK_BIN = 0x004e4942

type Mat4 = number[] // column-major, like glTF

const IDENTITY: Mat4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

function multiply(a: Mat4, b: Mat4): Mat4 {
  const out = new Array<number>(16).fill(0)
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) for (let k = 0; k < 4; k++) out[c * 4 + r] += a[k * 4 + r] * b[c * 4 + k]
  return out
}

function localMatrix(node: any): Mat4 {
  if (node.matrix) return node.matrix
  const [tx, ty, tz] = node.translation ?? [0, 0, 0]
  const [qx, qy, qz, qw] = node.rotation ?? [0, 0, 0, 1]
  const [sx, sy, sz] = node.scale ?? [1, 1, 1]
  return [
    (1 - 2 * (qy * qy + qz * qz)) * sx, 2 * (qx * qy + qz * qw) * sx, 2 * (qx * qz - qy * qw) * sx, 0,
    2 * (qx * qy - qz * qw) * sy, (1 - 2 * (qx * qx + qz * qz)) * sy, 2 * (qy * qz + qx * qw) * sy, 0,
    2 * (qx * qz + qy * qw) * sz, 2 * (qy * qz - qx * qw) * sz, (1 - 2 * (qx * qx + qy * qy)) * sz, 0,
    tx, ty, tz, 1,
  ]
}

/** Parse a binary glTF file into one merged triangle mesh. Throws with a readable message. */
export function parseGlb(buffer: ArrayBuffer): ScanMesh {
  const view = new DataView(buffer)
  if (buffer.byteLength < 20 || view.getUint32(0, true) !== GLB_MAGIC) {
    throw new Error('This is not a .glb file. In Polycam choose Export, Mesh, GLTF.')
  }
  let json: any = null
  let bin: DataView | null = null
  for (let offset = 12; offset + 8 <= buffer.byteLength; ) {
    const length = view.getUint32(offset, true), type = view.getUint32(offset + 4, true)
    if (type === CHUNK_JSON) json = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, offset + 8, length)))
    else if (type === CHUNK_BIN) bin = new DataView(buffer, offset + 8, length)
    offset += 8 + length
  }
  if (!json || !bin) throw new Error('The file has no geometry in it.')
  const data = bin

  const positions: number[] = []
  const indices: number[] = []

  const accessorInfo = (index: number) => {
    const accessor = json.accessors[index]
    const bufferView = json.bufferViews[accessor.bufferView]
    return { accessor, start: (bufferView.byteOffset ?? 0) + (accessor.byteOffset ?? 0), stride: bufferView.byteStride as number | undefined }
  }

  const addPrimitive = (primitive: any, m: Mat4) => {
    if ((primitive.mode ?? 4) !== 4) return // triangles only
    if (primitive.extensions?.KHR_draco_mesh_compression) {
      throw new Error('This scan is Draco-compressed, which is not supported. Export it without compression.')
    }
    if (primitive.attributes?.POSITION === undefined) return
    const pos = accessorInfo(primitive.attributes.POSITION)
    if (pos.accessor.componentType !== 5126) throw new Error('This scan uses quantized positions, which is not supported.')
    const base = positions.length / 3, stride = pos.stride ?? 12
    for (let i = 0; i < pos.accessor.count; i++) {
      const o = pos.start + i * stride
      const x = data.getFloat32(o, true), y = data.getFloat32(o + 4, true), z = data.getFloat32(o + 8, true)
      positions.push(m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13], m[2] * x + m[6] * y + m[10] * z + m[14])
    }
    if (primitive.indices === undefined) {
      for (let i = 0; i < pos.accessor.count; i++) indices.push(base + i)
      return
    }
    const idx = accessorInfo(primitive.indices), type = idx.accessor.componentType
    for (let i = 0; i < idx.accessor.count; i++) {
      const value = type === 5125 ? data.getUint32(idx.start + i * 4, true) : type === 5123 ? data.getUint16(idx.start + i * 2, true) : data.getUint8(idx.start + i)
      indices.push(base + value)
    }
  }

  const visit = (nodeIndex: number, parent: Mat4) => {
    const node = json.nodes[nodeIndex]
    const world = multiply(parent, localMatrix(node))
    if (node.mesh !== undefined) for (const primitive of json.meshes[node.mesh].primitives) addPrimitive(primitive, world)
    for (const child of node.children ?? []) visit(child, world)
  }
  const scene = json.scenes?.[json.scene ?? 0]
  for (const root of scene?.nodes ?? []) visit(root, IDENTITY)

  if (indices.length < 3) throw new Error('The file has no triangles in it.')
  const raw = new Float32Array(positions), index = new Uint32Array(indices)
  return orient(raw, index, guessOrientation(raw, index))
}

/** Build the usable mesh for a given orientation. Cheap enough to redo when the user changes it. */
export function orient(raw: Float32Array, indices: Uint32Array, orientation: Orientation): ScanMesh {
  const { up, flipped, unitScale: k } = orientation
  const positions = new Float32Array(raw.length)
  const sign = flipped ? -1 : 1 // flipping is a half turn about x: y and z change sign
  for (let i = 0; i < raw.length; i += 3) {
    const x = raw[i], y = raw[i + 1], z = raw[i + 2]
    // Each case is a pure rotation, so the model is never mirrored.
    let px: number, py: number, pz: number
    if (up === 'y') { px = x; py = y; pz = z }
    else if (up === 'z') { px = x; py = z; pz = -y }
    else { px = y; py = x; pz = -z }
    positions[i] = px * k
    positions[i + 1] = py * k * sign
    positions[i + 2] = pz * k * sign
  }
  const levels = findLevels({ positions, indices })
  return { raw, orientation, positions, indices, floorY: levels.floorY, ceilingHeight: levels.ceilingHeight, triangles: indices.length / 3 }
}

/**
 * Guess which axis is up and what the units are.
 *
 * Up: the floor is normally the largest flat surface in a room, so take the axis with the
 * most surface area lying in a single plane across it. Units: pick the one that makes the
 * model a believable height for a room.
 */
function guessOrientation(raw: Float32Array, indices: Uint32Array): Orientation {
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity]
  for (let i = 0; i < raw.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      if (raw[i + k] < min[k]) min[k] = raw[i + k]
      if (raw[i + k] > max[k]) max[k] = raw[i + k]
    }
  }
  const extent = [0, 1, 2].map((k) => Math.max(max[k] - min[k], 1e-9))
  const BINS = 80
  const area = [new Float64Array(BINS + 2), new Float64Array(BINS + 2), new Float64Array(BINS + 2)]
  for (let t = 0; t < indices.length; t += 3) {
    const a = indices[t] * 3, b = indices[t + 1] * 3, c = indices[t + 2] * 3
    const ux = raw[b] - raw[a], uy = raw[b + 1] - raw[a + 1], uz = raw[b + 2] - raw[a + 2]
    const vx = raw[c] - raw[a], vy = raw[c + 1] - raw[a + 1], vz = raw[c + 2] - raw[a + 2]
    const n = [uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx]
    const length = Math.hypot(n[0], n[1], n[2])
    if (length === 0) continue
    for (let k = 0; k < 3; k++) {
      if (Math.abs(n[k]) / length < 0.8) continue // not facing along this axis
      const centre = (raw[a + k] + raw[b + k] + raw[c + k]) / 3
      area[k][1 + Math.min(BINS - 1, Math.floor(((centre - min[k]) / extent[k]) * BINS))] += length / 2
    }
  }
  const peak = area.map((bins) => {
    let best = 0
    for (let i = 1; i <= BINS; i++) best = Math.max(best, bins[i - 1] + bins[i] + bins[i + 1])
    return best
  })
  // y wins ties, since that is what glTF says up should be.
  let axis = 1
  for (const k of [2, 0]) if (peak[k] > peak[axis] * 1.15) axis = k
  const up = (['x', 'y', 'z'] as const)[axis]

  const height = extent[axis]
  const unitScale = [1, 0.01, 0.001].find((k) => height * k >= 2 && height * k <= 8) ?? 1
  return { up, flipped: false, unitScale }
}

/**
 * Floor and ceiling: the lowest and the highest heights that hold a large share of the
 * horizontal surface. Counting area, not vertices, keeps desks from being mistaken for either.
 */
function findLevels(mesh: Pick<ScanMesh, 'positions' | 'indices'>): { floorY: number; ceilingHeight: number | null } {
  const { positions: p, indices } = mesh
  const BIN = 0.05
  const area = new Map<number, number>()
  for (let t = 0; t < indices.length; t += 3) {
    const a = indices[t] * 3, b = indices[t + 1] * 3, c = indices[t + 2] * 3
    const ux = p[b] - p[a], uy = p[b + 1] - p[a + 1], uz = p[b + 2] - p[a + 2]
    const vx = p[c] - p[a], vy = p[c + 1] - p[a + 1], vz = p[c + 2] - p[a + 2]
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
    const length = Math.hypot(nx, ny, nz)
    if (length === 0 || Math.abs(ny) / length < 0.8) continue // not horizontal
    const key = Math.round((p[a + 1] + p[b + 1] + p[c + 1]) / 3 / BIN)
    area.set(key, (area.get(key) ?? 0) + length / 2)
  }
  if (!area.size) {
    let min = Infinity
    for (let i = 1; i < p.length; i += 3) if (p[i] < min) min = p[i]
    return { floorY: min, ceilingHeight: null }
  }
  // Smooth over neighbouring bins: a scanned floor is never perfectly flat.
  const keys = [...area.keys()].sort((a, b) => a - b)
  const smooth = (k: number) => (area.get(k - 1) ?? 0) + (area.get(k) ?? 0) + (area.get(k + 1) ?? 0)
  const largest = Math.max(...keys.map(smooth))
  const floorKey = keys.find((k) => smooth(k) >= 0.4 * largest)!
  // The ceiling is often only partly scanned, so it gets a lower bar than the floor.
  const ceilingKey = [...keys].reverse().find((k) => smooth(k) >= 0.15 * largest)!
  const height = (ceilingKey - floorKey) * BIN
  const plausible = height >= 2.0 && height <= 6.0
  return { floorY: floorKey * BIN, ceilingHeight: plausible ? Math.round(height * 20) / 20 : null }
}

/**
 * Cut the mesh with a horizontal plane `heightAboveFloor` metres up.
 * Returns line segments as x1, y1, x2, y2 in floor-plan coordinates (x = glTF x, y = glTF z).
 */
export function sliceAt(mesh: ScanMesh, heightAboveFloor: number): Float32Array {
  const { positions: p, indices } = mesh
  const h = mesh.floorY + heightAboveFloor
  const out: number[] = []
  for (let t = 0; t < indices.length; t += 3) {
    let n = 0, x1 = 0, y1 = 0, x2 = 0, y2 = 0
    for (let e = 0; e < 3; e++) {
      const a = indices[t + e] * 3, b = indices[t + ((e + 1) % 3)] * 3
      const da = p[a + 1] - h, db = p[b + 1] - h
      if (da > 0 === db > 0) continue
      const f = da / (da - db)
      const x = p[a] + f * (p[b] - p[a]), y = p[a + 2] + f * (p[b + 2] - p[a + 2])
      if (n === 0) { x1 = x; y1 = y } else { x2 = x; y2 = y }
      n++
    }
    if (n === 2) out.push(x1, y1, x2, y2)
  }
  return new Float32Array(out)
}

/**
 * Angle in degrees, between -45 and 45, that most wall length makes with the axes.
 * Rotating the scan by the negative of this squares it up with the screen.
 */
export function dominantAngle(segments: Float32Array): number {
  const bins = new Float64Array(90)
  for (let i = 0; i < segments.length; i += 4) {
    const dx = segments[i + 2] - segments[i], dy = segments[i + 3] - segments[i + 1]
    const length = Math.hypot(dx, dy)
    if (length < 1e-6) continue
    const degrees = ((Math.atan2(dy, dx) * 180) / Math.PI + 360) % 90
    bins[Math.round(degrees) % 90] += length
  }
  let best = 0, bestWeight = -1
  for (let i = 0; i < 90; i++) {
    const weight = bins[(i + 89) % 90] + 2 * bins[i] + bins[(i + 1) % 90]
    if (weight > bestWeight) { bestWeight = weight; best = i }
  }
  return best > 45 ? best - 90 : best
}

/** Where the scan sits on the floor plan: a rotation, then a shift. */
export interface Placement {
  cos: number
  sin: number
  dx: number
  dy: number
  width: number
  height: number
}

/**
 * Rotate the whole scan by `degrees` and shift it so its footprint starts at (0, 0).
 * Uses every vertex, so the placement does not move when the slice height changes.
 */
export function placementOf(mesh: ScanMesh, degrees: number): Placement {
  const cos = Math.cos((degrees * Math.PI) / 180), sin = Math.sin((degrees * Math.PI) / 180)
  const p = mesh.positions
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  for (let i = 0; i < p.length; i += 3) {
    const x = p[i] * cos - p[i + 2] * sin, y = p[i] * sin + p[i + 2] * cos
    if (x < minX) minX = x
    if (y < minY) minY = y
    if (x > maxX) maxX = x
    if (y > maxY) maxY = y
  }
  return { cos, sin, dx: -minX, dy: -minY, width: maxX - minX, height: maxY - minY }
}

export function placeSegments(segments: Float32Array, placement: Placement): Float32Array {
  const { cos, sin, dx, dy } = placement
  const out = new Float32Array(segments.length)
  for (let i = 0; i < segments.length; i += 2) {
    out[i] = segments[i] * cos - segments[i + 1] * sin + dx
    out[i + 1] = segments[i] * sin + segments[i + 1] * cos + dy
  }
  return out
}
