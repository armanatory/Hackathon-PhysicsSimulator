export interface DeploymentMetadata {
  deployment?: 'worker-pc'
  offline?: boolean
  snapshot?: boolean
  message?: string
}
export interface Health extends DeploymentMetadata {
  status: string
  allsolve_configured: boolean
  modes?: { surrogate_demo: boolean; allsolve: boolean }
  liquid_optimizer_available?: boolean
}

export interface NumericBounds { min: number; max: number }
export interface LiquidInput { label: string; n: number }
export interface Geometry {
  period_nm: number
  fill_factor: number
  ridge_height_nm: number
}
export interface OptimizationRequest {
  schema_version: 1
  liquids: [LiquidInput, LiquidInput]
  geometry_bounds: {
    period_nm: NumericBounds
    fill_factor: NumericBounds
    ridge_height_nm: NumericBounds
  }
  film_thickness_nm: number
  minimum_feature_nm: number
  wavelength_min_nm: number
  wavelength_max_nm: number
  wavelength_samples: number
  candidate_count: number
  max_parallel_cores: number
  seed: number
  objective: 'max_abs_reflectance_contrast'
}
export type OptimizationStatus = 'queued' | 'running' | 'verifying' | 'completed' | 'failed'
export interface OptimizationReport {
  status?: OptimizationStatus
  stage?: string
  [key: string]: unknown
}
export interface OptimizationJob extends DeploymentMetadata {
  id: string
  status: OptimizationStatus
  created_at: string
  updated_at: string
  request: OptimizationRequest
  label: 'allsolve_liquid_discriminator'
  synthetic: false
  report: OptimizationReport | null
  error?: string | null
  reused?: boolean
}
export interface OptimizationConfig extends DeploymentMetadata {
  available: boolean
  allsolve_configured: boolean
  default_request: OptimizationRequest
  limits: Record<string, unknown>
  model: Record<string, unknown>
}

// The archived slab panel remains independently compilable.
export type SlabValidationStatus = 'not_run' | 'queued' | 'running' | 'completed' | 'failed' | 'unverified'
export interface SlabValidation {
  status: SlabValidationStatus
  validated: boolean
  label?: string
  purpose?: string
  synthetic?: boolean
  wavelength_nm?: number
  slab_index?: number
  slab_thickness_nm?: number
  project_id?: string
  project_url?: string
  inputs?: Record<string, unknown>
  analytical_reference?: Record<string, unknown>
  runs: Record<string, unknown>[]
  error?: string
  errors?: unknown
  [key: string]: unknown
}
