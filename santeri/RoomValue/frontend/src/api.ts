export type Vec3 = [number,number,number]
export interface SourceDefinition { id:string;name:string;position_m:Vec3;position_status?:string;directivity_note?:string }
export interface PanelSlot { id:string;name:string;position_m:Vec3;size_m:Vec3;area_m2:number }
export interface SoundSource { id:string;position_m:Vec3;level_db:number }
export interface PointPlan { sources:SoundSource[];listener_m:Vec3;max_panels:number;allowed_slot_ids:string[] }
export interface RoomCatalog {
  room:{id:string;name:string;size_m:Vec3;volume_m3:number}
  dataset:{name:string;url:string;license:string}
  sources:SourceDefinition[];slots:PanelSlot[];frequency_hz:number;allsolve_ready?:boolean
  maximums:{sources:number;objects:number};assumptions:string[];point_defaults?:PointPlan
}
export interface PointLayout { slot_ids:string[];object_count:number;pressure_rms_pa:number;noise_db:number;reduction_db:number;simulation_ids:string[];status:'SUCCESS' }
export interface ParallelExecution {
  basis_cores?:number;total_basis_solves?:number;cached_basis_fields?:number;newly_started_basis_solves?:number
  peak_parallel_solves?:number;peak_inflight_solves?:number;peak_allocated_cores?:number;observations?:Array<Record<string,unknown>>
}
export interface PointResult {
  objective:'minimize_listener_noise';noise_metric:'normalized_spl_db';dimension:3;frequency_hz:125
  project_id:string;project_url:string;mesh?:Record<string,unknown>;sources:SoundSource[];listener_m:Vec3;max_panels:number
  baseline:{pressure_rms_pa:number;noise_db:number;simulation_ids:string[]}
  optimal_layout:PointLayout;evaluations:PointLayout[]
  search:{evaluated_layouts:number;total_layouts:number;optimality_scope:string;source_combination?:string}
  assumptions?:string[]
  parallel_execution?:ParallelExecution
}
export interface JobProgress {
  stage?:string;message?:string;evaluated?:number;total?:number;best_count?:number;best_noise_db?:number;latest_simulation_id?:string;project_url?:string
  active_solves?:number;cloud_running_solves?:number;allocated_cores?:number;max_concurrent_cores?:number
  account_running_cores?:number;account_reserved_cores?:number
  cached_basis_fields?:number;completed_basis_solves?:number;verified_basis_fields?:number;remaining_basis_solves?:number;queued_basis_solves?:number;total_basis_solves?:number
  peak_parallel_solves?:number;running_simulation_ids?:string[]
}
export interface JobRecord { job_id:string;kind?:string;status:'queued'|'running'|'completed'|'failed'|'interrupted';request?:PointPlan;result?:PointResult;progress?:JobProgress;error?:string;created_at?:string;updated_at?:string }
export interface Health { allsolve_ready?:boolean;deployment?:string;message?:string }
function record(value:unknown):value is Record<string,unknown>{return typeof value==='object'&&value!==null&&!Array.isArray(value)}
function finite(value:unknown):value is number{return typeof value==='number'&&Number.isFinite(value)}
function vector(value:unknown):value is Vec3{return Array.isArray(value)&&value.length===3&&value.every(finite)}
export function sharedJob(search:string):{explicit:boolean;id?:string;error?:string}{
  const values=new URLSearchParams(search).getAll('job')
  if(!values.length)return{explicit:false}
  if(values.length!==1||! /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(values[0]))return{explicit:true,error:'The job link must contain one valid UUID.'}
  return{explicit:true,id:values[0].toLowerCase()}
}
export function preferredJob(saved:JobRecord|null,latest:JobRecord|null):JobRecord|null{
  if(saved&&['queued','running','failed','interrupted'].includes(saved.status))return saved
  if(!latest)return saved
  if(saved?.status==='completed'&&latest.status==='completed'){
    const savedAt=Date.parse(saved.updated_at||saved.created_at||''),latestAt=Date.parse(latest.updated_at||latest.created_at||'')
    if(Number.isFinite(savedAt)&&Number.isFinite(latestAt)&&savedAt>latestAt)return saved
  }return latest
}
export function validPointPlan(value:unknown,catalog?:RoomCatalog):value is PointPlan{
  if(!record(value)||!Array.isArray(value.sources)||!vector(value.listener_m)||!Array.isArray(value.allowed_slot_ids)||
     !finite(value.max_panels)||!Number.isInteger(value.max_panels)||value.max_panels<0||value.max_panels>6||
     !value.sources.length||value.sources.length>(catalog?.maximums.sources??3))return false
  if(!value.sources.every(source=>record(source)&&typeof source.id==='string'&&vector(source.position_m)&&
     finite(source.level_db)&&source.level_db>=0&&source.level_db<=120&&(!catalog||catalog.sources.some(item=>item.id===source.id))))return false
  return value.allowed_slot_ids.every(id=>typeof id==='string'&&(!catalog||catalog.slots.some(slot=>slot.id===id)))&&
    new Set(value.sources.map(source=>source.id)).size===value.sources.length&&new Set(value.allowed_slot_ids).size===value.allowed_slot_ids.length
}
export function samePointPlan(a:PointPlan|undefined,b:PointPlan){
  if(!a)return false
  const canonical=(p:PointPlan)=>JSON.stringify({sources:p.sources.map(s=>({id:s.id,position_m:[...s.position_m],level_db:s.level_db})).sort((x,y)=>x.id.localeCompare(y.id)),listener_m:[...p.listener_m],max_panels:p.max_panels,allowed_slot_ids:[...p.allowed_slot_ids].sort()})
  return canonical(a)===canonical(b)
}
export function verifiedPointResult(value:unknown):value is PointResult{
  if(!record(value)||value.objective!=='minimize_listener_noise'||value.noise_metric!=='normalized_spl_db'||value.dimension!==3||value.frequency_hz!==125||
     typeof value.project_id!=='string'||!value.project_id||typeof value.project_url!=='string'||!record(value.search)||!record(value.baseline)||!record(value.optimal_layout)||!vector(value.listener_m)||
     !Array.isArray(value.sources)||!value.sources.length||!value.sources.every(source=>record(source)&&typeof source.id==='string'&&vector(source.position_m)&&finite(source.level_db)))return false
  const result=value.optimal_layout,baseline=value.baseline
  return result.status==='SUCCESS'&&Array.isArray(result.slot_ids)&&result.slot_ids.every(id=>typeof id==='string')&&
    Number.isInteger(result.object_count)&&result.object_count===result.slot_ids.length&&finite(result.pressure_rms_pa)&&result.pressure_rms_pa>0&&finite(result.noise_db)&&finite(result.reduction_db)&&
    Array.isArray(result.simulation_ids)&&result.simulation_ids.length>0&&result.simulation_ids.every(id=>typeof id==='string'&&id.length>0)&&
    finite(baseline.pressure_rms_pa)&&baseline.pressure_rms_pa>0&&finite(baseline.noise_db)&&
    Array.isArray(baseline.simulation_ids)&&baseline.simulation_ids.length>0&&baseline.simulation_ids.every(id=>typeof id==='string'&&id.length>0)&&
    finite(value.search.evaluated_layouts)&&finite(value.search.total_layouts)
}
async function readJson(response:Response):Promise<unknown>{
  let payload:unknown;try{payload=await response.json()}catch{throw new Error(`The API returned HTTP ${response.status} without JSON.`)}
  if(!response.ok){
    let detail=`The API returned HTTP ${response.status}.`
    if(record(payload)&&typeof payload.detail==='string')detail=payload.detail
    else if(record(payload)&&Array.isArray(payload.detail))detail=payload.detail.map(item=>record(item)?`${Array.isArray(item.loc)?item.loc.slice(1).join(' / '):'Input'}: ${String(item.msg)}`:String(item)).join('; ')
    throw new Error(detail)
  }return payload
}
export async function getCatalog(signal?:AbortSignal):Promise<RoomCatalog>{
  const payload=await readJson(await fetch('/api/room3d/catalog',{cache:'no-store',signal}))
  if(!record(payload)||!record(payload.room)||!vector(payload.room.size_m)||!Array.isArray(payload.sources)||!Array.isArray(payload.slots))throw new Error('The API did not return the 3D room catalog.')
  return payload as unknown as RoomCatalog
}
export async function getHealth(signal?:AbortSignal):Promise<Health>{
  const payload=await readJson(await fetch('/api/health',{cache:'no-store',signal}));if(!record(payload))throw new Error('The health response was invalid.');return payload as Health
}
export async function startMinimization(input:PointPlan):Promise<string>{
  const payload=await readJson(await fetch('/api/room3d/minimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)}))
  if(!record(payload)||typeof payload.job_id!=='string')throw new Error('The API did not return a job ID.');return payload.job_id
}
export async function getJob(jobId:string,signal?:AbortSignal):Promise<JobRecord>{
  const payload=await readJson(await fetch(`/api/jobs/${encodeURIComponent(jobId)}`,{cache:'no-store',signal}))
  if(!record(payload)||typeof payload.job_id!=='string'||!['queued','running','completed','failed','interrupted'].includes(String(payload.status)))throw new Error('The job response was invalid.')
  if(payload.job_id!==jobId)throw new Error('The API returned a different job than the one requested.')
  if(payload.kind!==undefined&&payload.kind!=='room3d_point')throw new Error('The requested job is not a listening-point simulation.')
  return payload as unknown as JobRecord
}
export async function getLatest(signal?:AbortSignal):Promise<JobRecord|null>{
  const response=await fetch('/api/room3d/minimize/latest',{cache:'no-store',signal});if(response.status===404)return null
  const payload=await readJson(response);return record(payload)&&typeof payload.job_id==='string'?payload as unknown as JobRecord:null
}
export async function resumeJob(jobId:string):Promise<string>{
  const payload=await readJson(await fetch(`/api/jobs/${encodeURIComponent(jobId)}/resume`,{method:'POST'}))
  if(!record(payload)||typeof payload.job_id!=='string')throw new Error('The API did not resume the job.');return payload.job_id
}
