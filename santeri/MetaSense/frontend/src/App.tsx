import { useEffect, useMemo, useState } from 'react'
import { createOptimizationJob, getHealth, getLatestOptimizationJob, getOptimizationConfig, getOptimizationJob } from './api'
import type { Geometry, Health, NumericBounds, OptimizationConfig, OptimizationJob, OptimizationRequest } from './types'

const initialRequest: OptimizationRequest = {
  schema_version: 1,
  liquids: [{ label: 'Water', n: 1.33 }, { label: 'Glycerol–water', n: 1.38 }],
  geometry_bounds: {
    period_nm: { min: 450, max: 550 },
    fill_factor: { min: 0.3, max: 0.7 },
    ridge_height_nm: { min: 80, max: 220 },
  },
  film_thickness_nm: 100, minimum_feature_nm: 50,
  wavelength_min_nm: 900, wavelength_max_nm: 1100, wavelength_samples: 11,
  candidate_count: 24, max_parallel_cores: 64, seed: 42,
  objective: 'max_abs_reflectance_contrast',
}

function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
function finite(value: unknown): value is number { return typeof value === 'number' && Number.isFinite(value) }
function number(value: unknown): number | null { return finite(value) ? value : null }
function count(value: unknown): number | null { return finite(value) && Number.isInteger(value) && value >= 0 ? value : null }
function format(value: unknown, digits = 3) { return finite(value) ? value.toFixed(digits) : '—' }
function text(value: unknown): string | null { return typeof value === 'string' && value.trim() ? value : null }
function isCandidateId(value:unknown):boolean { return (finite(value)&&Number.isInteger(value)&&value>=0)||(typeof value==='string'&&value.trim().length>0) }
function safeUrl(value: unknown): string | null { try { const u = new URL(String(value)); return u.protocol === 'https:' && !u.username && !u.password ? u.href : null } catch { return null } }
function isActive(job: OptimizationJob | null) { return !!job && ['queued', 'running', 'verifying'].includes(job.status) }
function geometry(value: unknown): Geometry | null {
  const v = record(value)
  return finite(v.period_nm) && finite(v.fill_factor) && finite(v.ridge_height_nm)
    ? { period_nm: v.period_nm, fill_factor: v.fill_factor, ridge_height_nm: v.ridge_height_nm } : null
}

function NumberField({ id, label, value, min, max, step = 1, onChange }: { id: string; label: string; value: number; min: number; max: number; step?: number; onChange: (value: number) => void }) {
  return <label className="field" htmlFor={id}><span>{label}</span><input id={id} type="number" value={Number.isNaN(value) ? '' : value} min={min} max={max} step={step} onChange={event => onChange(event.target.value === '' ? NaN : Number(event.target.value))} /></label>
}
function BoundsField({ label, id, bounds, min, max, step = 1, onChange }: { label: string; id: string; bounds: NumericBounds; min: number; max: number; step?: number; onChange: (value: NumericBounds) => void }) {
  return <div className="bounds-row"><span>{label}</span><input aria-label={`${label} minimum`} id={`${id}-min`} type="number" min={min} max={max} step={step} value={Number.isNaN(bounds.min) ? '' : bounds.min} onChange={e => onChange({ ...bounds, min: e.target.value === '' ? NaN : Number(e.target.value) })} /><input aria-label={`${label} maximum`} id={`${id}-max`} type="number" min={min} max={max} step={step} value={Number.isNaN(bounds.max) ? '' : bounds.max} onChange={e => onChange({ ...bounds, max: e.target.value === '' ? NaN : Number(e.target.value) })} /></div>
}

function GeometryDiagram({ design, film, label }: { design: Geometry; film: number; label: string }) {
  const p = design.period_nm, width = p * design.fill_factor, height = design.ridge_height_nm
  const h = Math.max(25, Math.min(88, height / p * 150)), filmHeight = Math.max(7, Math.min(22, film / p * 65))
  const point = (x: number, y: number, z: number) => `${62 + x + y * 0.65},${177 + y * 0.34 - z}`
  const polygon = (vertices: [number, number, number][]) => vertices.map(v => point(...v)).join(' ')
  const prism = (x: number, y: number, width: number, depth: number, bottom: number, top: number, fills: string[], key: string) => <g key={key} stroke="#7e94a9" strokeWidth="0.75">
    <polygon points={polygon([[x,y,bottom],[x+width,y,bottom],[x+width,y,top],[x,y,top]])} fill={fills[0]} />
    <polygon points={polygon([[x+width,y,bottom],[x+width,y+depth,bottom],[x+width,y+depth,top],[x+width,y,top]])} fill={fills[1]} />
    <polygon points={polygon([[x,y,top],[x+width,y,top],[x+width,y+depth,top],[x,y+depth,top]])} fill={fills[2]} />
  </g>
  const aria = `${label}: silicon nitride ridges along y on a ${film} nanometer film and fused silica substrate, immersed in liquid. Period ${p} nanometers, ridge width ${width} nanometers, height ${height} nanometers. Incident light propagates in positive z with electric field along y. Drawing vertical scale is schematic.`
  return <section className="panel" aria-labelledby="geometry-title">
    <div className="panel-heading geometry-header"><div><h2 id="geometry-title">Geometry</h2><p>{label} · 1D ridge grating</p></div><span className="badge">TE · Eᵧ</span></div>
    <div className="geometry-body" role="img" aria-label={aria}>
      <div className="geometry-view"><span className="view-name">Perspective · 3 periods</span><svg viewBox="0 0 470 275" aria-hidden="true">
        <defs><marker id="geo-arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0L6 3L0 6" fill="#2a6ca4" /></marker><marker id="geo-dimension" markerWidth="5" markerHeight="5" refX="2.5" refY="2.5" orient="auto-start-reverse"><path d="M5 0L0 2.5L5 5" fill="none" stroke="#73869a" /></marker></defs>
        <rect x="18" y="24" width="433" height="180" rx="3" fill="#edf5fa" />
        <text x="327" y="45" className="geometry-label">Liquid A / B</text>
        {prism(0,0,300,80,-filmHeight-28,-filmHeight,['#cad5df','#becbd7','#dbe3e9'],'glass')}
        {prism(0,0,300,80,-filmHeight,0,['#7c99b3','#6f8ba4','#a9bfd1'],'film')}
        {[0,1,2].map(i => prism(i*100+(1-design.fill_factor)*50,0,design.fill_factor*100,80,0,h,['#8ba6bf','#7b96af','#b4c9da'],`ridge-${i}`))}
        <polyline points={polygon([[100,0,h+12],[200,0,h+12],[200,80,h+12],[100,80,h+12],[100,0,h+12]])} className="geometry-dashed" />
        <line x1="35" y1="46" x2="35" y2="91" className="geometry-arrow" markerEnd="url(#geo-arrow)" /><text x="43" y="64" className="geometry-dimension">k +z</text>
        <line x1="29" y1="113" x2="57" y2="125" className="geometry-arrow" markerEnd="url(#geo-arrow)" /><text x="22" y="140" className="geometry-dimension">Eᵧ</text>
        <line x1="162" y1="240" x2="262" y2="240" className="geometry-stroke" markerStart="url(#geo-dimension)" markerEnd="url(#geo-dimension)" /><text x="212" y="256" textAnchor="middle" className="geometry-dimension">p = {p.toFixed(0)} nm</text>
        <text x="328" y="244" className="geometry-dimension">y →</text><text x="63" y="266" className="geometry-label">Fused silica substrate</text>
      </svg></div>
      <div className="geometry-view"><span className="view-name">x–z cross section</span><svg viewBox="0 0 420 275" aria-hidden="true">
        <defs><marker id="cross-dimension" markerWidth="5" markerHeight="5" refX="2.5" refY="2.5" orient="auto-start-reverse"><path d="M5 0L0 2.5L5 5" fill="none" stroke="#73869a" /></marker></defs>
        <rect x="40" y="24" width="300" height="153" fill="#edf5fa" />
        <text x="50" y="43" className="geometry-label">Liquid fills grooves</text>
        <rect x="40" y={177+filmHeight} width="300" height={51-filmHeight} fill="#d7dfe7" stroke="#94a7b8" strokeWidth=".7" />
        <rect x="40" y="177" width="300" height={filmHeight} fill="#8da9c3" stroke="#738ca4" strokeWidth=".7" />
        {[0,1,2].map(i => <rect key={i} x={40+i*100+(1-design.fill_factor)*50} y={177-h} width={100*design.fill_factor} height={h} fill="#8da9c3" stroke="#6a87a2" strokeWidth=".8" />)}
        <rect x="140" y="24" width="100" height="204" className="geometry-dashed" />
        <line x1={140+(1-design.fill_factor)*50} y1={163-h} x2={140+(1+design.fill_factor)*50} y2={163-h} className="geometry-stroke" markerStart="url(#cross-dimension)" markerEnd="url(#cross-dimension)" /><text x="190" y={153-h} textAnchor="middle" className="geometry-dimension">w = {width.toFixed(0)} nm</text>
        <line x1="354" y1={177-h} x2="354" y2="177" className="geometry-stroke" markerStart="url(#cross-dimension)" markerEnd="url(#cross-dimension)" /><text x="363" y={176-h/2} className="geometry-dimension">h</text><text x="349" y="201" className="geometry-dimension">{height.toFixed(0)} nm</text>
        <text x="52" y="219" className="geometry-label">Fused silica</text><line x1="140" y1="246" x2="240" y2="246" className="geometry-stroke" markerStart="url(#cross-dimension)" markerEnd="url(#cross-dimension)" /><text x="190" y="263" textAnchor="middle" className="geometry-dimension">p = {p.toFixed(0)} nm</text>
      </svg></div>
    </div>
    <div className="geometry-legend"><span><i className="swatch liquid" /> Liquid</span><span><i className="swatch silicon" /> Si₃N₄ ridge + film</span><span><i className="swatch glass" /> Fused silica</span></div>
    <p className="geometry-caption"><strong>Fill factor {design.fill_factor.toFixed(3)}</strong> · w = p × fill · film {film.toFixed(0)} nm · invariant-y cell 100 nm. Vertical scale schematic; dimensions label the model.</p>
  </section>
}

interface Spectrum { wavelength_nm: number[]; reflectance_a: number[]; reflectance_b: number[]; stage: 'search' | 'dense' }
function validPoint(point:Record<string,unknown>):boolean { return point.valid===true&&finite(point.wavelength_nm)&&finite(point.R)&&finite(point.T)&&finite(point.energy_residual) }
function spectrum(value: unknown, candidateId: unknown, liquids: OptimizationRequest['liquids']): Spectrum | null {
  if(!Array.isArray(value)||!isCandidateId(candidateId))return null
  const spectra=value.map(record).filter(s=>s.candidate_id===candidateId)
  const stage=['dense','search'].find(stage=>liquids.every(liquid=>spectra.some(s=>s.stage===stage&&finite(s.n)&&Math.abs(s.n-liquid.n)<1e-9))) as 'dense'|'search'|undefined
  if(!stage)return null
  const selected=liquids.map(liquid=>spectra.find(s=>s.stage===stage&&finite(s.n)&&Math.abs(s.n-liquid.n)<1e-9))
  if(selected.some(s=>!s||!Array.isArray(s.points)))return null
  const points=selected.map(s=>(s!.points as unknown[]).map(record).sort((a,b)=>Number(a.wavelength_nm)-Number(b.wavelength_nm)))
  const [a,b]=points
  if(a.length<2||a.length!==b.length||!a.every((point,i)=>validPoint(point)&&validPoint(b[i])&&Math.abs(Number(point.wavelength_nm)-Number(b[i].wavelength_nm))<1e-6&&(i===0||Number(point.wavelength_nm)>Number(a[i-1].wavelength_nm))))return null
  return {wavelength_nm:a.map(p=>Number(p.wavelength_nm)),reflectance_a:a.map(p=>Number(p.R)),reflectance_b:b.map(p=>Number(p.R)),stage}
}
function fineReadout(value:unknown,candidateId:unknown,liquids:OptimizationRequest['liquids'],wavelength:unknown):[number,number]|null {
  if(!Array.isArray(value)||!isCandidateId(candidateId)||!finite(wavelength))return null
  const spectra=value.map(record).filter(s=>s.stage==='fine'&&s.candidate_id===candidateId)
  const points=liquids.map(liquid=>{const s=spectra.find(s=>finite(s.n)&&Math.abs(s.n-liquid.n)<1e-9);return s&&Array.isArray(s.points)?s.points.map(record).find(p=>validPoint(p)&&Math.abs(Number(p.wavelength_nm)-wavelength)<1e-6):null})
  return points.every(p=>p&&finite(p.R))?[Number(points[0]!.R),Number(points[1]!.R)]:null
}
function SpectrumChart({ values, liquids, selected, fine }: { values: Spectrum | null; liquids: OptimizationRequest['liquids']; selected: number | null; fine: [number,number] | null }) {
  if (!values) return <div className="empty"><strong>No complete cloud spectrum</strong>Two liquid reflectance curves appear when matching valid wavelength outputs are available.</div>
  const xs = values.wavelength_nm, minX = xs[0], maxX = xs[xs.length-1]
  const maxY = Math.max(1, ...values.reflectance_a, ...values.reflectance_b,...(fine??[])) * 1.02, minY = Math.min(0, ...values.reflectance_a, ...values.reflectance_b,...(fine??[]))
  const x = (v: number) => 56+(v-minX)/(maxX-minX)*604, y = (v: number) => 236-(v-minY)/(maxY-minY)*192
  const line = (ys: number[]) => ys.map((v,i) => `${i===0?'M':'L'}${x(xs[i]).toFixed(2)},${y(v).toFixed(2)}`).join(' ')
  const marker = selected !== null && selected>=minX && selected<=maxX ? x(selected) : null
  return <><div className="chart-body"><svg viewBox="0 0 704 290" role="img" aria-label={`Allsolve ${values.stage} spectra on the search mesh for ${liquids[0].label} and ${liquids[1].label}, ${minX} to ${maxX} nanometers.${fine?' Separate markers show verified fine-mesh values at the common readout wavelength.':''} Reflectance is a power fraction.`}>
    {[0,0.25,0.5,0.75,1].map(t => { const value=minY+t*(maxY-minY); return <g key={t}><line x1="56" y1={y(value)} x2="660" y2={y(value)} className="chart-grid" /><text x="47" y={y(value)+4} textAnchor="end" className="chart-label">{value.toFixed(2)}</text></g> })}
    {[0,0.25,0.5,0.75,1].map(t => { const value=minX+t*(maxX-minX); return <g key={t}><line x1={x(value)} y1="44" x2={x(value)} y2="236" className="chart-grid" /><text x={x(value)} y="256" textAnchor="middle" className="chart-label">{value.toFixed(0)}</text></g> })}
    <line x1="56" y1="236" x2="660" y2="236" className="chart-axis" />
    {marker !== null && <line x1={marker} y1="44" x2={marker} y2="236" className="chart-marker" />}
    <path d={line(values.reflectance_a)} className="chart-line a" /><path d={line(values.reflectance_b)} className="chart-line b" />
    {fine&&marker!==null&&<><circle cx={marker} cy={y(fine[0])} r="4" className="chart-point a" stroke="white" strokeWidth="1.5"/><circle cx={marker} cy={y(fine[1])} r="4" className="chart-point b" stroke="white" strokeWidth="1.5"/></>}
    <text x="56" y="24" className="chart-label">Reflectance R · power fraction</text><text x="358" y="280" textAnchor="middle" className="chart-label">Vacuum wavelength (nm)</text>
  </svg></div><div className="chart-legend"><span><i /> A · {liquids[0].label}</span><span><i className="b" /> B · {liquids[1].label}</span>{selected!==null&&<span>Readout {selected.toFixed(1)} nm{fine?' · fine-mesh markers':''}</span>}</div><p className="candidate-note">{values.stage==='dense'?'Dense wavelength':'Search wavelength'} curves use the search mesh.{fine?' The fine mesh verifies the selected wavelength only.':''}</p></>
}

function CandidateError({ error }: { error: unknown }) {
  const raw = text(error)
  if (!raw) return null
  const first = raw.split(/[;\r\n]+/).find(part => part.trim())?.trim() ?? raw.trim()
  const summary = first.length > 110 ? `${first.slice(0, 107).trimEnd()}…` : first
  const details = raw.length > 2000 ? `${raw.slice(0, 2000)}\n[Display truncated; full diagnostics are saved with the job.]` : raw
  return <details className="candidate-errors"><summary>{summary}</summary><pre>{details}</pre></details>
}
function CandidateState({ candidate }: { candidate: Record<string, unknown> }) {
  const status = text(candidate.status)
  const passed = candidate.valid === true
  const dense = record(candidate.dense_verification)
  const densePassed = dense.status === 'passed'
  const denseFailed = dense.status === 'failed'
  const validPairs = count(dense.valid_pairs), totalPairs = count(dense.total_pairs)
  const denseErrors = Array.isArray(dense.errors) ? dense.errors.map(text).filter(Boolean).join('; ') : null
  return <>
    <span className={`candidate-state ${status ?? ''}`}>{status ?? 'Pending'}</span>
    {['completed','invalid','failed'].includes(status ?? '') && <span className={`badge ${passed?'pass':'fail'}`} style={{marginLeft:6}}>{passed?'Search pass':'Search failed'}</span>}
    {candidate.verified === true && <span className="badge pass" style={{marginLeft:6}}>Fine verified</span>}
    {count(candidate.completed_solves)!==null&&count(candidate.total_solves)!==null&&<div className="muted">{String(candidate.completed_solves)}/{String(candidate.total_solves)} search solves</div>}
    {Object.keys(dense).length>0&&<div className="candidate-refinement"><span className={`badge ${densePassed?'pass':denseFailed?'fail':'queued'}`}>{densePassed?'Dense pass':denseFailed?'Dense failed':'Dense pending'}</span>{validPairs!==null&&totalPairs!==null&&<span className="muted">{validPairs}/{totalPairs} paired wavelengths</span>}</div>}
    <CandidateError error={denseFailed?denseErrors:null} />
    <CandidateError error={candidate.error} />
  </>
}

function verificationChecks(value:unknown) {
  const v=record(value),limits=record(v.limits),checks=record(v.checks)
  const names:{[key:string]:string}={mesh_max_R_change:'Fine / search mesh R',mesh_contrast_change:'Fine / search contrast',clearance_max_R_change:'Open-boundary clearance',RCWA_max_R_error:'Independent TE RCWA R',RCWA_order_convergence:'RCWA 9 / 13 orders'}
  return [{label:'Cloud readout checks',value:null,limit:null,passed:v.readout_checks===true},{label:'Mesh geometry matches request',value:null,limit:null,passed:checks.mesh_dimensions===true},...Object.entries(names).map(([key,label])=>({label,value:number(v[key]),limit:number(limits[key]),passed:finite(v[key])&&finite(limits[key])&&v[key]<=limits[key]}))]
}

export default function App() {
  const [request,setRequest] = useState<OptimizationRequest>(initialRequest)
  const [health,setHealth] = useState<Health|null>(null)
  const [config,setConfig] = useState<OptimizationConfig|null>(null)
  const [job,setJob] = useState<OptimizationJob|null>(null)
  const [submitting,setSubmitting] = useState(false)
  const [error,setError] = useState('')
  const [pollError,setPollError] = useState('')
  const [loaded,setLoaded] = useState(false)
  const [loadError,setLoadError] = useState('')
  const [availabilityError,setAvailabilityError] = useState('')
  const locked = submitting || isActive(job)
  const hosted = config?.deployment==='worker-pc'||health?.deployment==='worker-pc'||job?.deployment==='worker-pc'
  const backendOffline = config?.offline??health?.offline??job?.offline??false
  const snapshot = job?.snapshot===true||((config?.snapshot===true||health?.snapshot===true)&&backendOffline)
  const backendUnavailable = !!availabilityError||(!config&&!health&&loaded)
  const connectionLabel = hosted
    ? backendUnavailable?'Backend status unavailable':backendOffline?job?'Backend offline · saved result':'Backend offline':'Backend online'
    : backendUnavailable?'API unavailable':config||health?'API connected':'Connecting to API'

  useEffect(() => {
    let active=true
    void Promise.allSettled([getHealth(),getOptimizationConfig(),getLatestOptimizationJob()]).then(([healthResult,configResult,jobResult])=>{
      if(!active)return
      if(healthResult.status==='fulfilled')setHealth(healthResult.value)
      if(configResult.status==='fulfilled'){setConfig(configResult.value);if(jobResult.status!=='fulfilled'||!jobResult.value)setRequest(configResult.value.default_request)}
      else setAvailabilityError(configResult.reason instanceof Error?configResult.reason.message:'Could not load optimizer configuration.')
      if(jobResult.status==='fulfilled'){setJob(jobResult.value);if(jobResult.value)setRequest(jobResult.value.request)}
      else setLoadError(jobResult.reason instanceof Error?jobResult.reason.message:'Could not restore the latest job.')
      setLoaded(true)
    })
    return () => { active=false }
  },[])
  useEffect(() => {
    if(!loaded)return
    let active=true,pending=false
    const poll=async()=>{if(pending)return;pending=true;try{const settings=await getOptimizationConfig();if(active){setConfig(settings);setAvailabilityError('')}}catch(cause){if(active)setAvailabilityError(cause instanceof Error?cause.message:'Could not refresh backend availability.')}finally{pending=false}}
    const timer=window.setInterval(()=>{void poll()},15000)
    return()=>{active=false;window.clearInterval(timer)}
  },[loaded])
  useEffect(() => {
    if(!isActive(job))return
    let active=true, pending=false
    const poll=async()=>{ if(pending)return; pending=true; try{ const updated=await getOptimizationJob(job!.id); if(active){setJob(updated);setPollError('')} }catch(cause){if(active)setPollError(cause instanceof Error ? cause.message : 'Could not refresh cloud progress.')}finally{pending=false} }
    const timer=window.setInterval(()=>{void poll()},5000)
    return()=>{active=false;window.clearInterval(timer)}
  },[job?.id,job?.status])

  const validation=useMemo(()=>{
    for(const liquid of request.liquids){if(!liquid.label.trim())return 'Both liquid labels are required.';if(!finite(liquid.n)||liquid.n<1||liquid.n>1.8)return 'Liquid indices must be from 1 to 1.8.'}
    if(request.liquids[0].label.trim().toLocaleLowerCase()===request.liquids[1].label.trim().toLocaleLowerCase())return 'Liquid labels must differ.'
    if(request.liquids[0].n===request.liquids[1].n)return 'Choose two different optical indices.'
    const b=request.geometry_bounds
    for(const [label,v,min,max] of [['Period',b.period_nm,100,1000],['Fill factor',b.fill_factor,0.05,0.95],['Ridge height',b.ridge_height_nm,20,800]] as [string,NumericBounds,number,number][]){if(!finite(v.min)||!finite(v.max)||v.min<min||v.max>max||v.min>v.max)return `${label} bounds must be ordered and between ${min} and ${max}.`}
    if(!finite(request.film_thickness_nm)||request.film_thickness_nm<50||request.film_thickness_nm>250)return 'Film thickness must be from 50 to 250 nm.'
    if(!finite(request.minimum_feature_nm)||request.minimum_feature_nm<20||request.minimum_feature_nm>100)return 'Minimum feature must be from 20 to 100 nm.'
    if(b.period_nm.min*Math.min(b.fill_factor.min,1-b.fill_factor.max)<request.minimum_feature_nm)return 'The smallest ridge width and gap must meet the minimum feature.'
    if(b.ridge_height_nm.min<request.minimum_feature_nm)return 'The smallest ridge height must meet the minimum feature.'
    if(!finite(request.wavelength_min_nm)||!finite(request.wavelength_max_nm)||request.wavelength_min_nm<800||request.wavelength_max_nm>1600||request.wavelength_min_nm>=request.wavelength_max_nm)return 'Wavelength range must increase within 800–1600 nm.'
    if(b.period_nm.max*Math.max(request.liquids[0].n,request.liquids[1].n,1.46)>0.9*request.wavelength_min_nm)return 'Period must stay below the diffraction cutoff with a 10% margin.'
    if(!Number.isInteger(request.wavelength_samples)||request.wavelength_samples<3||request.wavelength_samples>41)return 'Wavelength samples must be an integer from 3 to 41.'
    if(!Number.isInteger(request.candidate_count)||request.candidate_count<1||request.candidate_count>128)return 'Candidate count must be an integer from 1 to 128.'
    if(!Number.isInteger(request.max_parallel_cores)||request.max_parallel_cores<4||request.max_parallel_cores>256)return 'Core budget must be an integer from 4 to 256.'
    if(!Number.isInteger(request.seed)||request.seed<0||request.seed>4294967295)return 'Seed must be an integer from 0 to 4,294,967,295.'
    return ''
  },[request])
  const setScalar=(key:keyof OptimizationRequest,value:number)=>setRequest(previous=>({...previous,[key]:value}))
  const setBounds=(key:keyof OptimizationRequest['geometry_bounds'],value:NumericBounds)=>setRequest(previous=>({...previous,geometry_bounds:{...previous.geometry_bounds,[key]:value}}))
  const setLiquid=(index:0|1,key:'label'|'n',value:string|number)=>setRequest(previous=>{const liquids=[...previous.liquids] as OptimizationRequest['liquids'];liquids[index]={...liquids[index],[key]:value};return {...previous,liquids}})
  async function start(){if(locked||validation||!loaded||loadError||availabilityError||backendOffline||!config?.available)return;setSubmitting(true);setError('');try{const value=await createOptimizationJob(request);setJob(value);setRequest(value.request);setPollError('')}catch(cause){setError(cause instanceof Error?cause.message:'Could not start cloud optimization.')}finally{setSubmitting(false)}}
  async function refresh(){
    const [jobResult,configResult]=await Promise.allSettled([job?getOptimizationJob(job.id):getLatestOptimizationJob(),getOptimizationConfig()])
    if(jobResult.status==='fulfilled'){const value=jobResult.value;setJob(value);if(value&&isActive(value))setRequest(value.request);setPollError('');setLoadError('')}
    else setPollError(jobResult.reason instanceof Error?jobResult.reason.message:'Could not refresh the job.')
    if(configResult.status==='fulfilled'){setConfig(configResult.value);setAvailabilityError('')}
    else setAvailabilityError(configResult.reason instanceof Error?configResult.reason.message:'Could not refresh backend availability.')
  }

  const report=record(job?.report)
  const progress=record(report.progress)
  const candidates=Array.isArray(report.candidates)?report.candidates.map(record):[]
  const winner=record(report.best_design)
  const winnerGeometry=geometry(winner.geometry)
  const runRequest=job?.request??request
  const preview:Geometry=winnerGeometry??{period_nm:(request.geometry_bounds.period_nm.min+request.geometry_bounds.period_nm.max)/2,fill_factor:(request.geometry_bounds.fill_factor.min+request.geometry_bounds.fill_factor.max)/2,ridge_height_nm:(request.geometry_bounds.ridge_height_nm.min+request.geometry_bounds.ridge_height_nm.max)/2}
  const usablePreview=finite(preview.period_nm)&&finite(preview.fill_factor)&&finite(preview.ridge_height_nm)&&preview.period_nm>0&&preview.fill_factor>0&&preview.fill_factor<1&&preview.ridge_height_nm>0?preview:null
  const completed=count(progress.completed_solve_count)
  const total=count(progress.planned_solve_count)
  const batches=Array.isArray(report.batches)?report.batches.map(record):[]
  const projectUrl=batches.map(b=>safeUrl(b.project_url)).find(Boolean)
  const objective=number(winner.score)
  const wavelength=number(winner.wavelength_nm)
  const fine=fineReadout(report.spectra,winner.candidate_id,runRequest.liquids,wavelength)
  const verification=record(winner.verification)
  const verificationRows=verificationChecks(verification)
  const verified=winner.validated===true&&verification.passed===true&&verificationRows.every(check=>check.passed)&&job?.status==='completed'&&job.synthetic===false&&objective!==null&&wavelength!==null&&finite(winner.R_A)&&finite(winner.R_B)&&fine!==null&&Math.abs(fine[0]-winner.R_A)<1e-8&&Math.abs(fine[1]-winner.R_B)<1e-8
  const spectra=spectrum(report.spectra,winner.candidate_id,runRequest.liquids)
  const selectedA=number(winner.R_A)
  const selectedB=number(winner.R_B)

  return <div className="app">
    <header className="app-header"><div className="brand"><strong>Liquid discriminator</strong><span>MetaSense · Allsolve</span></div><span className={`connection ${!backendUnavailable&&!backendOffline&&(health||config)?'online':'offline'}`}><i />{connectionLabel}</span></header>
    <div className="intro"><h1>Optimize reflectance contrast</h1><p>Find the best sampled geometry for |R<sub>A</sub> − R<sub>B</sub>| at one common readout wavelength.</p></div>
    <main className="workspace">
      <aside className="panel controls" aria-labelledby="search-inputs-title"><h2 id="search-inputs-title">Search inputs</h2>
        <button className="run-button" type="button" disabled={locked||!!validation||!loaded||!!loadError||!!availabilityError||backendOffline||!config?.available} onClick={()=>void start()}>{submitting?'Starting cloud jobs…':locked?'Optimization running…':'Optimize with Allsolve'}</button><p className="run-description">{backendOffline?'Backend offline. New cloud jobs are disabled.':'Launch real cloud jobs. Inputs lock during a run.'}{loaded&&config&&!config.available&&!backendOffline?' The cloud optimizer is currently unavailable.':''}</p>
        {validation&&<div className="error" role="alert">{validation}</div>}{error&&<div className="error" role="alert">{error}</div>}
        <fieldset disabled={locked}><legend>Liquids · assumed optical indices</legend>{request.liquids.map((liquid,i)=><div className="liquid-row" key={i}><label className="field" htmlFor={`liquid-${i}-name`}><span><b className={`liquid-tag ${i===1?'b':''}`}>{i===0?'A':'B'}</b>Label</span><input id={`liquid-${i}-name`} value={liquid.label} maxLength={80} onChange={e=>setLiquid(i as 0|1,'label',e.target.value)} /></label><NumberField id={`liquid-${i}-n`} label="Index n" value={liquid.n} min={1} max={1.8} step={.001} onChange={v=>setLiquid(i as 0|1,'n',v)} /></div>)}<p className="control-note">Constant nominal indices. No glycerol concentration is inferred.</p></fieldset>
        <fieldset disabled={locked}><legend>Geometry bounds</legend><div className="bounds-labels"><span /><span>Minimum</span><span>Maximum</span></div><BoundsField label="Period p (nm)" id="period" bounds={request.geometry_bounds.period_nm} min={100} max={1000} onChange={v=>setBounds('period_nm',v)} /><BoundsField label="Fill factor w/p" id="fill" bounds={request.geometry_bounds.fill_factor} min={.05} max={.95} step={.01} onChange={v=>setBounds('fill_factor',v)} /><BoundsField label="Ridge height h (nm)" id="height" bounds={request.geometry_bounds.ridge_height_nm} min={20} max={800} onChange={v=>setBounds('ridge_height_nm',v)} /><p className="control-note">Period below diffraction cutoff (10% margin).</p><div className="fixed-grid" style={{marginTop:10}}><NumberField id="film" label="Fixed film (nm)" value={request.film_thickness_nm} min={50} max={250} onChange={v=>setScalar('film_thickness_nm',v)} /><NumberField id="feature" label="Min. feature (nm)" value={request.minimum_feature_nm} min={20} max={100} onChange={v=>setScalar('minimum_feature_nm',v)} /></div></fieldset>
        <fieldset disabled={locked}><legend>Readout wavelength range</legend><div className="fixed-grid"><NumberField id="lambda-min" label="Minimum (nm)" value={request.wavelength_min_nm} min={800} max={1600} onChange={v=>setScalar('wavelength_min_nm',v)} /><NumberField id="lambda-max" label="Maximum (nm)" value={request.wavelength_max_nm} min={800} max={1600} onChange={v=>setScalar('wavelength_max_nm',v)} /><NumberField id="samples" label="Wavelength samples" value={request.wavelength_samples} min={3} max={41} onChange={v=>setScalar('wavelength_samples',v)} /></div></fieldset>
        <fieldset disabled={locked}><legend>Search and compute</legend><div className="fixed-grid"><NumberField id="candidate-count" label="Candidates" value={request.candidate_count} min={1} max={128} onChange={v=>setScalar('candidate_count',v)} /><NumberField id="cores" label="Parallel core budget" value={request.max_parallel_cores} min={4} max={256} onChange={v=>setScalar('max_parallel_cores',v)} /><NumberField id="seed" label="Sampling seed" value={request.seed} min={0} max={4294967295} onChange={v=>setScalar('seed',v)} /></div><p className="control-note">Space-filling search; dense wavelength sweep and finer mesh verify finalists.</p></fieldset>
      </aside>
      <section className="main-column" aria-label="Optimization results">
        <section className="panel status-panel" aria-labelledby="progress-title"><div className="status-heading"><h2 id="progress-title">{job?'Cloud optimization':'Cloud progress'}</h2><span className={`badge ${job?.status??''}`}>{job?.status??(loaded?'Not started':'Loading')}</span></div><p className="status-summary">{job?(text(report.stage)??'Waiting for cloud progress'):'No optimization has been started.'}</p>{snapshot&&job&&<p className="snapshot-note" role="status">Saved cloud result · updated {new Date(job.updated_at).toLocaleString('en-GB',{timeZone:'Europe/Helsinki'})} (Helsinki).{text(config?.message)&&<> {text(config?.message)}</>}</p>}{job&&<><div className="progress-track" role="progressbar" aria-label="Completed cloud solves" aria-valuemin={0} aria-valuemax={Math.max(1,total??0)} aria-valuenow={completed??undefined}><span style={{width:`${total!==null&&total>0&&completed!==null?Math.min(100,completed/total*100):0}%`}} /></div><div className="progress-counts"><span><b>{format(completed,0)}/{format(total,0)}</b> solves completed</span>{finite(progress.queued_solve_count)&&<span><b>{progress.queued_solve_count}</b> queued</span>}{finite(progress.running_solve_count)&&<span><b>{progress.running_solve_count}</b> running</span>}{finite(progress.failed_solve_count)&&<span><b>{progress.failed_solve_count}</b> failed</span>}{finite(progress.completed_candidates)&&<span><b>{progress.completed_candidates}/{number(progress.planned_candidates)??runRequest.candidate_count}</b> candidates</span>}{finite(progress.valid_candidates)&&<span><b>{progress.valid_candidates}</b> search-valid</span>}{finite(progress.effective_parallel_cores)&&<span><b>{progress.effective_parallel_cores}/{runRequest.max_parallel_cores}</b> parallel core limit</span>}</div><div className="status-footer"><span className="job-id">Job <code>{job.id}</code></span><div>{projectUrl&&<a href={projectUrl} target="_blank" rel="noreferrer">Allsolve project ↗</a>} <button className="refresh-button" type="button" onClick={()=>void refresh()}>Refresh</button></div></div></>}{!job&&<div className="status-footer"><span>{loadError?'Saved job state unavailable':loaded?'Last-job state loaded':'Loading saved job state'}</span><button className="refresh-button" type="button" onClick={()=>void refresh()}>Refresh</button></div>}{job?.error&&<div className="error" role="alert">{job.error}</div>}{loadError&&<div className="error" role="alert">Latest-job state unavailable. {loadError}</div>}{availabilityError&&<div className="error" role="status">Backend availability could not be checked. {availabilityError} New optimizations are disabled until a successful refresh.</div>}{pollError&&<div className="error" role="status">Progress refresh failed. {pollError} {job?'Showing the last received state.':''}</div>}</section>
        {job&&!locked&&JSON.stringify(request)!==JSON.stringify(job.request)&&<p className="muted">Inputs changed. Displayed results belong to the saved run.</p>}
        {usablePreview&&finite(winnerGeometry?runRequest.film_thickness_nm:request.film_thickness_nm)?<GeometryDiagram design={usablePreview} film={winnerGeometry?runRequest.film_thickness_nm:request.film_thickness_nm} label={winnerGeometry?verified?'Verified winning candidate':'Best sampled candidate · provisional':'Bounds midpoint · preview'} />:<section className="panel"><div className="panel-heading"><h2>Geometry</h2></div><p className="empty">Enter finite geometry dimensions to show the preview.</p></section>}
        <section className="panel"><div className="panel-heading"><div><h2>{verified?'Winner reflectance':'Best candidate reflectance'}</h2><p>{verified?'Fine readout verified · curves use the search mesh':spectra?'Cloud search output · fine verification pending':'Dense wavelength / fine mesh verification pending'}</p></div><span className={`badge ${verified?'pass':'queued'}`}>{verified?'Verified':'Provisional'}</span></div><SpectrumChart values={spectra} liquids={runRequest.liquids} selected={wavelength} fine={verified?fine:null} />{objective!==null&&<><dl className="winner-summary"><div><dt>Readout wavelength</dt><dd>{format(wavelength,1)} <small>nm</small></dd></div><div><dt>{verified?'Fine contrast |R_A − R_B|':'Provisional contrast |R_A − R_B|'}</dt><dd>{format(objective,5)}</dd></div><div><dt>A / B reflectance</dt><dd>{format(selectedA,4)} <small>/</small> {format(selectedB,4)}</dd></div></dl>{winnerGeometry&&<div className="winner-geometry"><h3>{verified?'Winner':'Best candidate'} against search bounds</h3><div className="dimension-comparison">{(['period_nm','fill_factor','ridge_height_nm'] as const).map(key=><div key={key}><span>{key==='period_nm'?'Period (nm)':key==='fill_factor'?'Fill factor':'Ridge height (nm)'}</span><strong>{format(winnerGeometry[key],key==='fill_factor'?3:1)}</strong><span>Bounds {format(runRequest.geometry_bounds[key].min,key==='fill_factor'?3:0)}–{format(runRequest.geometry_bounds[key].max,key==='fill_factor'?3:0)}</span></div>)}</div></div>}</>}
          {Object.keys(verification).length>0&&<div className="verification"><h3>Finalist verification</h3>{verificationRows.map(check=><div className={`verification-row ${check.passed?'':'failed'}`} key={check.label}><input type="checkbox" checked={check.passed} readOnly disabled aria-label={`${check.label}: ${check.passed?'passed':'failed'}`} /><span>{check.label}</span><span>{check.value!==null?`${format(check.value,5)} ≤ ${format(check.limit,5)}`:check.passed?'Passed':'Failed'}</span></div>)}</div>}
          {job&&<details className="cloud-details"><summary>Cloud provenance · {batches.length} batches</summary><dl><dt>Optimization job</dt><dd><code>{job.id}</code></dd><dt>Updated (Helsinki)</dt><dd>{job.updated_at?new Date(job.updated_at).toLocaleString('en-GB',{timeZone:'Europe/Helsinki'}):'—'}</dd></dl>{batches.map((batch,i)=><div className="cloud-batch" key={text(batch.simulation_id)??String(i)}><p><strong>{text(batch.name)??`Batch ${i+1}`}</strong> · {text(batch.stage)} · <span className={`candidate-state ${text(batch.status)??''}`}>{text(batch.status)??'Pending'}</span> · {format(batch.point_count,0)} points</p><dl>{[['Project',batch.project_id],['Mesh',batch.mesh_id],['Simulation',batch.simulation_id],['Mesh job',batch.mesh_job_id],['Simulation job',batch.simulation_job_id]].map(([label,value])=><div className="cloud-id" key={String(label)}><dt>{String(label)}</dt><dd><code>{text(value)??'Pending'}</code></dd></div>)}</dl>{safeUrl(batch.project_url)&&<a href={safeUrl(batch.project_url)!} target="_blank" rel="noreferrer">Open project ↗</a>}</div>)}</details>}
        </section>
        <section className="panel"><div className="panel-heading"><div><h2>Candidates</h2><p>Search scores use the coarse mesh. Dense and fine checks determine the verified selection.</p></div></div>{candidates.length?<div className="candidate-table-wrap"><table className="candidate-table"><thead><tr><th scope="col">Candidate</th><th scope="col" className="numeric">p (nm)</th><th scope="col" className="numeric">Fill</th><th scope="col" className="numeric">h (nm)</th><th scope="col" className="numeric">Search |ΔR|</th><th scope="col" className="numeric">λ (nm)</th><th scope="col">Search / refinement</th></tr></thead><tbody>{candidates.map((c,i)=>{const g=geometry(c.geometry),passed=c.valid===true;return <tr key={text(c.id)??String(i)} className={c.id===winner.candidate_id?'winner':''}><th scope="row">{isCandidateId(c.id)?`#${String(c.id)}`:`Candidate ${i+1}`}</th><td className="numeric">{format(g?.period_nm,0)}</td><td className="numeric">{format(g?.fill_factor)}</td><td className="numeric">{format(g?.ridge_height_nm,0)}</td><td className="numeric">{passed?format(c.score,5):'—'}</td><td className="numeric">{passed?format(c.wavelength_nm,1):'—'}</td><td><CandidateState candidate={c} /></td></tr>})}</tbody></table></div>:<div className="empty">Candidate geometries and cloud results appear after a run starts.</div>}<p className="candidate-note">The winner summary reports fine-mesh contrast. Search and failed dense scores do not establish a verified winner.</p></section>
        <details className="panel methods"><summary>Methods and assumptions</summary><p>Allsolve builds liquid-filled Si₃N₄ ridges and a continuous film on fused silica, tetrahedral meshes, and EM harmonic FEM with second-order H(curl) fields and periodic multiplier order 2. A TE plane wave enters through an impedance boundary; both exterior ends use absorbing admittance boundaries.</p><p>Chunked geometry × liquid-index × wavelength sweeps run within the selected core budget. Geometry overrides create separate meshes. Coarse children use 3-core fast-start nodes; fine verification uses 4 cores / 64 GB. Coherent zeroth-order reflectance is normalized by incident forward power; total Poynting flux and backward-wave contamination are checked. The frontend does no optical simulation.</p><p>Liquid indices are constant nominal inputs. Latin-hypercube sampling ranks valid candidates, then denser wavelengths and finer meshes verify finalists. This is a best-of-N search, with no global-optimum claim. Material constants, checks, and source hashes remain with the cloud report.</p><p><a href="https://allsolve.quanscient.com/documentation/using-allsolve/physics/em-waves" target="_blank" rel="noreferrer">Allsolve EM waves</a> · <a href="https://allsolve.quanscient.com/documentation/reference/allsolve-sdk" target="_blank" rel="noreferrer">Allsolve SDK</a></p></details>
      </section>
    </main><footer className="footer"><span>Allsolve cloud simulation · optical discrimination of two specified liquid indices</span><span>Reflectance is a power fraction; concentration and measurement noise are outside this model.</span></footer>
  </div>
}
