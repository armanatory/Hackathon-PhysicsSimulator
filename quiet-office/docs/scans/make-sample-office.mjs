// Writes sample-office.glb: the Allquiet demo office as a 3D model, in the same container
// and conventions as a phone scan export (binary glTF 2.0, one mesh, metres, Y up).
// It is generated, not scanned: a clean, closed room to test scan import against.
//
//   node quiet-office/docs/scans/make-sample-office.mjs

import { writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOM = { width: 16, depth: 10, height: 2.7, wall: 0.15 }
const DESK = { width: 1.2, depth: 0.7, height: 0.75 }

// Floor plan x -> glTF x, floor plan y -> glTF z, height -> glTF y. Origin is a room corner.
const boxes = [] // [x0, y0, z0, x1, y1, z1]
const box = (x0, z0, x1, z1, y0, y1) => boxes.push([x0, y0, z0, x1, y1, z1])

const { width: W, depth: D, height: H, wall: T } = ROOM
box(0, 0, W, D, -0.1, 0) // floor slab
box(-T, -T, W + T, 0, 0, H) // north wall
box(-T, D, W + T, D + T, 0, H) // south wall
box(-T, 0, 0, D, 0, H) // west wall
box(W, 0, W + T, D, 0, H) // east wall

// Same desk positions as backend/app/models/office.py default_office()
for (const [cx, cy] of [[5, 2], [10.5, 2], [4.4, 7], [10.5, 7]]) {
  for (const [dx, dy] of [[0, 0], [1.6, 0], [0, 1.4], [1.6, 1.4]]) {
    const x = cx + dx, y = cy + dy
    box(x - DESK.width / 2, y - DESK.depth / 2, x + DESK.width / 2, y + DESK.depth / 2, DESK.height - 0.04, DESK.height)
  }
}
box(0.2, 4.2, 0.8, 5.8, 0, 0.95) // coffee counter against the west wall, by the talker
box(7.8, 4.8, 8.2, 5.2, 0, H) // structural column in the centre aisle

const positions = [], indices = []
// Two triangles per face, counter-clockwise seen from outside.
const FACES = [
  [0, 2, 1, 1, 2, 3], [4, 5, 6, 5, 7, 6], [0, 1, 4, 1, 5, 4],
  [2, 6, 3, 3, 6, 7], [0, 4, 2, 2, 4, 6], [1, 3, 5, 3, 7, 5],
]
for (const [x0, y0, z0, x1, y1, z1] of boxes) {
  const base = positions.length / 3
  for (let c = 0; c < 8; c++) positions.push(c & 1 ? x1 : x0, c & 2 ? y1 : y0, c & 4 ? z1 : z0)
  for (const f of FACES) for (const i of f) indices.push(base + i)
}

const pos = Buffer.from(new Float32Array(positions).buffer)
const idx = Buffer.from(new Uint32Array(indices).buffer)
const bin = Buffer.concat([pos, idx])
const min = [0, 1, 2].map((k) => Math.min(...positions.filter((_, i) => i % 3 === k)))
const max = [0, 1, 2].map((k) => Math.max(...positions.filter((_, i) => i % 3 === k)))

const gltf = {
  asset: { version: '2.0', generator: 'Allquiet make-sample-office' },
  scene: 0,
  scenes: [{ nodes: [0] }],
  nodes: [{ mesh: 0, name: 'sample-office' }],
  meshes: [{ primitives: [{ attributes: { POSITION: 0 }, indices: 1, material: 0 }] }],
  materials: [{ pbrMetallicRoughness: { baseColorFactor: [0.85, 0.87, 0.84, 1], metallicFactor: 0, roughnessFactor: 0.9 }, doubleSided: true }],
  accessors: [
    { bufferView: 0, componentType: 5126, count: positions.length / 3, type: 'VEC3', min, max },
    { bufferView: 1, componentType: 5125, count: indices.length, type: 'SCALAR' },
  ],
  bufferViews: [
    { buffer: 0, byteOffset: 0, byteLength: pos.length, target: 34962 },
    { buffer: 0, byteOffset: pos.length, byteLength: idx.length, target: 34963 },
  ],
  buffers: [{ byteLength: bin.length }],
}

// GLB container: 12-byte header, then a JSON chunk and a BIN chunk, each padded to 4 bytes.
const pad = (buffer, fill) => Buffer.concat([buffer, Buffer.alloc((4 - (buffer.length % 4)) % 4, fill)])
const json = pad(Buffer.from(JSON.stringify(gltf)), 0x20)
const body = pad(bin, 0)
const chunk = (type, data) => {
  const head = Buffer.alloc(8)
  head.writeUInt32LE(data.length, 0)
  head.write(type, 4, 'ascii')
  return Buffer.concat([head, data])
}
const header = Buffer.alloc(12)
header.write('glTF', 0, 'ascii')
header.writeUInt32LE(2, 4)
header.writeUInt32LE(12 + 8 + json.length + 8 + body.length, 8)

const out = join(dirname(fileURLToPath(import.meta.url)), 'sample-office.glb')
writeFileSync(out, Buffer.concat([header, chunk('JSON', json), chunk('BIN\0', body)]))
console.log(`Wrote ${out}: ${boxes.length} boxes, ${positions.length / 3} vertices, ${indices.length / 3} triangles`)
