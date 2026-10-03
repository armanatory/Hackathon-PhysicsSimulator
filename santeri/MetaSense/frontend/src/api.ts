import type { Health, OptimizationConfig, OptimizationJob, OptimizationRequest, OptimizationStatus, SlabValidation, SlabValidationStatus } from './types'

async function decode(response: Response): Promise<unknown> {
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const data = record(body), detail = data.detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => { const entry=record(item); return `${Array.isArray(entry.loc)?entry.loc.slice(1).join('.'):''}: ${String(entry.msg??'Invalid input')}` }).join('; ') : typeof data.message === 'string' ? data.message : `Request failed (${response.status})`
    throw new Error(message)
  }
  return body
}
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
function isNumber(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function request(value: unknown): OptimizationRequest {
  const v=record(value), bounds=record(v.geometry_bounds)
  if (!Array.isArray(v.liquids)||v.liquids.length!==2||!v.liquids.every(item=>typeof record(item).label==='string'&&isNumber(record(item).n))||!['period_nm','fill_factor','ridge_height_nm'].every(key=>isNumber(record(bounds[key]).min)&&isNumber(record(bounds[key]).max))||!['film_thickness_nm','minimum_feature_nm','wavelength_min_nm','wavelength_max_nm','wavelength_samples','candidate_count','max_parallel_cores','seed'].every(key=>isNumber(v[key]))||v.objective!=='max_abs_reflectance_contrast') throw new Error('Invalid optimization input data returned by the API.')
  return v as unknown as OptimizationRequest
}
function job(value: unknown): OptimizationJob {
  const v=record(value), statuses:OptimizationStatus[]=['queued','running','verifying','completed','failed']
  if(typeof v.id!=='string'||!statuses.includes(v.status as OptimizationStatus)||v.label!=='allsolve_liquid_discriminator'||v.synthetic!==false||typeof v.created_at!=='string'||typeof v.updated_at!=='string'||!(v.report===null||(v.report&&typeof v.report==='object'&&!Array.isArray(v.report)))) throw new Error('Invalid cloud optimization job returned by the API.')
  return {...v,request:request(v.request)} as unknown as OptimizationJob
}
export async function getHealth(): Promise<Health> {
  return await decode(await fetch('/api/health',{cache:'no-store'})) as Health
}
export async function getOptimizationConfig():Promise<OptimizationConfig> {
  const v=record(await decode(await fetch('/api/optimization/config',{cache:'no-store'})))
  if(typeof v.available!=='boolean'||typeof v.allsolve_configured!=='boolean')throw new Error('Invalid optimizer configuration returned by the API.')
  return {...v,default_request:request(v.default_request),limits:record(v.limits),model:record(v.model)} as unknown as OptimizationConfig
}
export async function createOptimizationJob(body:OptimizationRequest):Promise<OptimizationJob> {
  return job(await decode(await fetch('/api/optimization/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})))
}
export async function getOptimizationJob(id:string):Promise<OptimizationJob> {
  return job(await decode(await fetch(`/api/optimization/jobs/${encodeURIComponent(id)}`,{cache:'no-store'})))
}
export async function getLatestOptimizationJob():Promise<OptimizationJob|null> {
  const value=await decode(await fetch('/api/optimization/jobs/latest',{cache:'no-store'}))
  return value===null?null:job(value)
}
export async function getSlabValidation(signal?: AbortSignal): Promise<SlabValidation> {
  const body = await decode(await fetch('/api/validation/slab', { cache: 'no-store', signal }))
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error('Invalid optical validation report.')
  const report = body as Record<string, unknown>
  const statuses: SlabValidationStatus[] = ['not_run', 'queued', 'running', 'completed', 'failed', 'unverified']
  if (!statuses.includes(report.status as SlabValidationStatus) || typeof report.validated !== 'boolean') throw new Error('Invalid optical validation report.')
  const runs = Array.isArray(report.runs) ? report.runs.filter((run): run is Record<string, unknown> => !!run && typeof run === 'object' && !Array.isArray(run)) : []
  return {
    ...report,status:report.status as SlabValidationStatus,
    validated:report.validated===true&&report.label==='allsolve_slab_validation'&&report.status==='completed'&&report.synthetic===false&&report.purpose==='optical_slab_benchmark'&&runs.length>0,
    runs,
  }
}
