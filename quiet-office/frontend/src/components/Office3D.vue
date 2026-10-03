<script setup lang="ts">
/**
 * The office in 3D: room, desks, the conversation and the chosen screens at their real
 * height. When a phone scan is loaded, its mesh is shown in place so the room can be checked
 * against it. Drag to orbit, scroll to zoom.
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { LayoutResult, Office, OptimizationParams } from '@/types'
import { levelColor, segmentOf } from '@/physics/estimate'
import { boundsOf } from '@/physics/geometry'
import type { Placement, ScanMesh } from '@/scan/glb'

const props = defineProps<{
  office: Office
  params: OptimizationParams
  best: LayoutResult | null
  scan: ScanMesh | null
  scanPlacement: Placement | null
}>()

const INK = 0x1d1b2f
const PIN = 0x5b3fd3
const DESK = { width: 1.2, depth: 0.7, height: 0.75 }

const host = ref<HTMLDivElement | null>(null)
let renderer: THREE.WebGLRenderer | null = null
let scene: THREE.Scene | null = null
let camera: THREE.PerspectiveCamera | null = null
let controls: OrbitControls | null = null
let content: THREE.Group | null = null
let observer: ResizeObserver | null = null
let framed = false

function render(): void {
  if (renderer && scene && camera) renderer.render(scene, camera)
}

function disposeGroup(group: THREE.Object3D): void {
  group.traverse((object) => {
    const mesh = object as THREE.Mesh
    mesh.geometry?.dispose()
    const material = mesh.material
    if (Array.isArray(material)) material.forEach((m) => m.dispose())
    else material?.dispose()
  })
}

/** Floor plan (x, y) and height map to three.js (x, height, y). */
function build(): void {
  if (!scene) return
  if (content) {
    scene.remove(content)
    disposeGroup(content)
  }
  content = new THREE.Group()
  const { office, params } = props
  const ceiling = office.ceiling_height_m

  // Floor
  const shape = new THREE.Shape(office.outline.map((p) => new THREE.Vector2(p.x, p.y)))
  const floor = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshLambertMaterial({ color: 0xffffff, side: THREE.DoubleSide }))
  floor.rotation.x = Math.PI / 2
  content.add(floor)

  // Walls: see-through, so the inside stays visible from any side
  const wallMaterial = new THREE.MeshLambertMaterial({ color: 0xdfe2ec, transparent: true, opacity: 0.28, side: THREE.DoubleSide, depthWrite: false })
  const edgePoints: number[] = []
  office.outline.forEach((a, i) => {
    const b = office.outline[(i + 1) % office.outline.length]
    const length = Math.hypot(b.x - a.x, b.y - a.y)
    if (length < 1e-6) return
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(length, ceiling), wallMaterial)
    wall.position.set((a.x + b.x) / 2, ceiling / 2, (a.y + b.y) / 2)
    wall.rotation.y = -Math.atan2(b.y - a.y, b.x - a.x)
    content!.add(wall)
    edgePoints.push(a.x, 0, a.y, b.x, 0, b.y, a.x, ceiling, a.y, b.x, ceiling, b.y, a.x, 0, a.y, a.x, ceiling, a.y)
  })
  const edges = new THREE.BufferGeometry()
  edges.setAttribute('position', new THREE.Float32BufferAttribute(edgePoints, 3))
  content.add(new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: INK })))

  // Desks, coloured by the speech level left at each one
  office.desks.forEach((desk, i) => {
    const level = props.best?.desk_levels_db[i]
    const top = new THREE.Mesh(
      new THREE.BoxGeometry(DESK.width, 0.05, DESK.depth),
      new THREE.MeshLambertMaterial({ color: level === undefined ? 0xffffff : new THREE.Color(levelColor(level)) }),
    )
    top.position.set(desk.x, DESK.height, desk.y)
    content!.add(top)
    const legs = new THREE.Mesh(new THREE.BoxGeometry(DESK.width - 0.1, DESK.height - 0.05, 0.04), new THREE.MeshLambertMaterial({ color: 0x9aa8a3 }))
    legs.position.set(desk.x, (DESK.height - 0.05) / 2, desk.y)
    content!.add(legs)
    // Where the seated person's ears are
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), new THREE.MeshLambertMaterial({ color: INK }))
    head.position.set(desk.x, params.ear_height_m, desk.y + DESK.depth / 2 + 0.25)
    content!.add(head)
  })

  // Quiet zones: a green patch on the floor, up to ear height at the edges
  for (const zone of office.quiet_zones) {
    const patch = new THREE.Mesh(
      new THREE.BoxGeometry(zone.width, params.ear_height_m, zone.height),
      new THREE.MeshLambertMaterial({ color: 0x2a7a5f, transparent: true, opacity: 0.14, depthWrite: false }),
    )
    patch.position.set(zone.x + zone.width / 2, params.ear_height_m / 2, zone.y + zone.height / 2)
    content.add(patch)
    content.add(new THREE.LineSegments(new THREE.EdgesGeometry(patch.geometry), new THREE.LineBasicMaterial({ color: 0x2a7a5f })).translateX(patch.position.x).translateY(patch.position.y).translateZ(patch.position.z))
  }

  // Noise sources: a figure with the sound coming from mouth height
  for (const source of office.sources) {
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.2, params.source_height_m - 0.15, 16), new THREE.MeshLambertMaterial({ color: 0xc13a5c }))
    body.position.set(source.x, (params.source_height_m - 0.15) / 2, source.y)
    content.add(body)
    const mouth = new THREE.Mesh(new THREE.SphereGeometry(0.15, 20, 14), new THREE.MeshLambertMaterial({ color: 0xc13a5c }))
    mouth.position.set(source.x, params.source_height_m, source.y)
    content.add(mouth)
  }

  // Screens of the best layout, at the chosen panel height
  const height = Math.min(params.screen_height_m, ceiling)
  const chosen = new Set(props.best?.slot_ids ?? [])
  for (const slot of office.slots) {
    const g = segmentOf(slot, params.screen_length_m)
    const vertical = slot.orientation === 'v'
    const size: [number, number, number] = vertical ? [0.08, height, g.length] : [g.length, height, 0.08]
    if (chosen.has(slot.id)) {
      const panel = new THREE.Mesh(new THREE.BoxGeometry(...size), new THREE.MeshLambertMaterial({ color: params.screen_absorbing ? 0x646880 : INK }))
      panel.position.set(slot.x, height / 2, slot.y)
      content.add(panel)
      const cap = new THREE.Mesh(new THREE.BoxGeometry(size[0] + 0.02, 0.04, size[2] + 0.02), new THREE.MeshBasicMaterial({ color: PIN }))
      cap.position.set(slot.x, height + 0.02, slot.y)
      content.add(cap)
    } else {
      // Positions that were not chosen: a faint line on the floor
      const mark = new THREE.Mesh(new THREE.BoxGeometry(size[0], 0.01, size[2]), new THREE.MeshBasicMaterial({ color: INK, transparent: true, opacity: 0.18 }))
      mark.position.set(slot.x, 0.006, slot.y)
      content.add(mark)
    }
  }

  // The phone scan, moved and turned exactly as in the floor-plan editor
  if (props.scan && props.scanPlacement) {
    const { positions, indices, floorY } = props.scan
    const { cos, sin, dx, dy } = props.scanPlacement
    const placed = new Float32Array(positions.length)
    for (let i = 0; i < positions.length; i += 3) {
      placed[i] = positions[i] * cos - positions[i + 2] * sin + dx
      placed[i + 1] = positions[i + 1] - floorY
      placed[i + 2] = positions[i] * sin + positions[i + 2] * cos + dy
    }
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(placed, 3))
    geometry.setIndex(new THREE.BufferAttribute(indices, 1))
    geometry.computeVertexNormals()
    content.add(new THREE.Mesh(geometry, new THREE.MeshLambertMaterial({ color: 0x2b6fd0, transparent: true, opacity: 0.35, side: THREE.DoubleSide, depthWrite: false })))
  }

  scene.add(content)
  if (!framed) frame()
  render()
}

/** Point the camera at the whole room from a corner above it. */
function frame(): void {
  if (!camera || !controls) return
  const b = boundsOf(props.office.outline)
  const cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2, span = Math.max(b.width, b.height)
  controls.target.set(cx, 1, cy)
  camera.position.set(cx - span * 0.55, span * 0.75, cy + span * 0.95)
  controls.update()
  framed = true
}

function resize(): void {
  if (!host.value || !renderer || !camera) return
  const width = host.value.clientWidth, height = host.value.clientHeight
  if (!width || !height) return
  renderer.setSize(width, height, false)
  camera.aspect = width / height
  camera.updateProjectionMatrix()
  render()
}

function resetView(): void {
  frame()
  render()
}

onMounted(() => {
  if (!host.value) return
  renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setClearColor(0xeaf2fd)
  host.value.appendChild(renderer.domElement)

  scene = new THREE.Scene()
  scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa8a3, 1.5))
  const sun = new THREE.DirectionalLight(0xffffff, 1.4)
  sun.position.set(-6, 14, 8)
  scene.add(sun)

  camera = new THREE.PerspectiveCamera(42, 1, 0.1, 400)
  controls = new OrbitControls(camera, renderer.domElement)
  controls.maxPolarAngle = Math.PI / 2 - 0.02 // stay above the floor
  controls.addEventListener('change', render)

  observer = new ResizeObserver(resize)
  observer.observe(host.value)
  resize()
  build()
})

onBeforeUnmount(() => {
  observer?.disconnect()
  controls?.dispose()
  if (content) disposeGroup(content)
  renderer?.dispose()
  renderer?.domElement.remove()
  renderer = null
})

watch(() => [props.office, props.params, props.best, props.scan, props.scanPlacement], build, { deep: true })
</script>

<template>
  <div class="view3d">
    <div ref="host" class="stage" role="img" aria-label="3D view of the office with the chosen screens"></div>
    <button type="button" class="reset" @click="resetView">Reset view</button>
  </div>
</template>
