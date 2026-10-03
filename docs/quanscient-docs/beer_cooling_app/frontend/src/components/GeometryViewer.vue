<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { useSimulationStore } from '@/stores/simulationStore'

const store = useSimulationStore()
const containerRef = ref<HTMLDivElement | null>(null)

let scene: THREE.Scene
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let controls: OrbitControls
let beerMesh: THREE.Mesh
let waterMesh: THREE.Mesh
let animationId: number

// Container dimensions (scaled for visualization)
const scale = 5

const containerHeight = computed(() => store.containerSpec.height * scale)
const containerRadius = computed(() => store.containerSpec.radius * scale)
const waterLevel = computed(() => containerHeight.value * store.params.immersion_level)

function init() {
  if (!containerRef.value) return

  const width = containerRef.value.clientWidth
  const height = containerRef.value.clientHeight

  // Scene
  scene = new THREE.Scene()
  scene.background = new THREE.Color(0xfafafa)

  // Camera
  camera = new THREE.PerspectiveCamera(50, width / height, 0.1, 100)
  camera.position.set(0.8, 0.6, 0.8)

  // Renderer
  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(window.devicePixelRatio)
  containerRef.value.appendChild(renderer.domElement)

  // Controls
  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.05
  controls.target.set(0, 0.25, 0)

  // Lighting
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.7)
  scene.add(ambientLight)

  const directionalLight = new THREE.DirectionalLight(0xffffff, 1)
  directionalLight.position.set(5, 8, 5)
  scene.add(directionalLight)

  const fillLight = new THREE.DirectionalLight(0xffffff, 0.3)
  fillLight.position.set(-3, 3, 3)
  scene.add(fillLight)

  // Create beer container
  createContainer()

  // Ground plane
  const groundGeometry = new THREE.PlaneGeometry(2, 2)
  const groundMaterial = new THREE.MeshStandardMaterial({
    color: 0xeeeeee,
    metalness: 0.1,
    roughness: 0.9
  })
  const ground = new THREE.Mesh(groundGeometry, groundMaterial)
  ground.rotation.x = -Math.PI / 2
  ground.position.y = -0.01
  scene.add(ground)

  // Start animation
  animate()
}

function createContainer() {
  // Remove old meshes if they exist
  if (beerMesh) scene.remove(beerMesh)
  if (waterMesh) scene.remove(waterMesh)

  const height = containerHeight.value
  const radius = containerRadius.value
  const waterH = waterLevel.value

  // Beer container (cylinder)
  const containerGeometry = new THREE.CylinderGeometry(radius, radius, height, 32)
  const beerColor = new THREE.Color(store.temperatureColor)
  const containerMaterial = new THREE.MeshStandardMaterial({
    color: beerColor,
    metalness: store.params.container_shape === 'can' ? 0.8 : 0.1,
    roughness: store.params.container_shape === 'can' ? 0.2 : 0.3,
    transparent: store.params.container_shape !== 'can',
    opacity: store.params.container_shape === 'can' ? 1 : 0.7,
  })
  beerMesh = new THREE.Mesh(containerGeometry, containerMaterial)
  beerMesh.position.y = height / 2
  scene.add(beerMesh)

  // Water/ice bath
  const waterGeometry = new THREE.BoxGeometry(1, waterH, 1)
  const waterMaterial = new THREE.MeshStandardMaterial({
    color: 0x0ea5e9,
    transparent: true,
    opacity: 0.2,
    metalness: 0.1,
    roughness: 0.8,
  })
  waterMesh = new THREE.Mesh(waterGeometry, waterMaterial)
  waterMesh.position.y = waterH / 2 - 0.01
  scene.add(waterMesh)

  // Add ice cubes
  for (let i = 0; i < 6; i++) {
    const angle = (i / 6) * Math.PI * 2
    const dist = 0.35
    const iceGeometry = new THREE.BoxGeometry(0.04, 0.04, 0.04)
    const iceMaterial = new THREE.MeshStandardMaterial({
      color: 0xe0f2fe,
      transparent: true,
      opacity: 0.7,
    })
    const ice = new THREE.Mesh(iceGeometry, iceMaterial)
    ice.position.set(
      Math.cos(angle) * dist,
      Math.random() * waterH * 0.5 + 0.02,
      Math.sin(angle) * dist
    )
    ice.rotation.set(Math.random(), Math.random(), Math.random())
    scene.add(ice)
  }
}

function updateBeerColor() {
  if (beerMesh && beerMesh.material instanceof THREE.MeshStandardMaterial) {
    beerMesh.material.color.set(store.temperatureColor)
  }
}

function animate() {
  animationId = requestAnimationFrame(animate)
  controls.update()
  renderer.render(scene, camera)
}

function handleResize() {
  if (!containerRef.value) return
  const width = containerRef.value.clientWidth
  const height = containerRef.value.clientHeight
  camera.aspect = width / height
  camera.updateProjectionMatrix()
  renderer.setSize(width, height)
}

// Watch for parameter changes
watch(() => store.params.immersion_level, createContainer)
watch(() => store.params.container_shape, createContainer)
watch(() => store.temperatureColor, updateBeerColor)

onMounted(() => {
  init()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  cancelAnimationFrame(animationId)
  window.removeEventListener('resize', handleResize)
  if (renderer) {
    renderer.dispose()
  }
  if (containerRef.value && renderer) {
    containerRef.value.removeChild(renderer.domElement)
  }
})
</script>

<template>
  <div class="w-full h-full relative">
    <div ref="containerRef" class="w-full h-full rounded-md overflow-hidden" />

    <!-- Overlay info -->
    <div class="absolute bottom-2 left-2 right-2 flex justify-between text-xs text-grey-500 bg-white/80 backdrop-blur-sm rounded px-2 py-1">
      <span>{{ store.containerSpec.label }}</span>
      <span>{{ Math.round(store.params.immersion_level * 100) }}% submerged</span>
    </div>
  </div>
</template>
