import { useEffect,useMemo,useState } from 'react'
import { getCatalog,getHealth,getJob,getLatest,preferredJob,resumeJob,samePointPlan,sharedJob,startMinimization,validPointPlan,verifiedPointResult,
  type Health,type JobProgress,type JobRecord,type ParallelExecution,type PointPlan,type RoomCatalog,type Vec3 } from './api'
import RoomView,{type Placement} from './RoomView'

const jobKey='roomvalue.point.job.v1',draftKey='roomvalue.point.draft.v1',referenceLevel=90.9691
const initial:PointPlan={sources:[{id:'src1',position_m:[1.89407487,4.52190448,1.44818390],level_db:referenceLevel}],listener_m:[3.08212703,3.42108318,1.49048013],max_panels:3,allowed_slot_ids:['east_a','east_b','west','south','ceiling_a','ceiling_b']}
function stored(key:string){try{return localStorage.getItem(key)}catch{return null}}
function save(key:string,value:string){try{localStorage.setItem(key,value)}catch{/* Browser storage is optional. */}}
function rememberJob(id:string){save(jobKey,id);const url=new URL(window.location.href);url.searchParams.set('job',id);window.history.replaceState(null,'',url)}
function num(value:number,digits=1){return value.toLocaleString('en-GB',{maximumFractionDigits:digits,minimumFractionDigits:digits})}
function verifyingFields(stage:string|undefined){return stage!==undefined&&['downloading','prefetching','verifying_fields','cloud_complete'].includes(stage)}
function Numeric({label,value,onChange,min=0,max,step=.1,unit}:{label:string;value:number;onChange:(n:number)=>void;min?:number;max?:number;step?:number;unit?:string}){
  return<label className="number-field"><span>{label}{unit&&<small>{unit}</small>}</span><input aria-label={label} type="number" min={min} max={max} step={step} value={Number.isFinite(value)?value:''} onChange={e=>onChange(e.target.value===''?NaN:Number(e.target.value))}/></label>
}
function ParallelProgress({progress:p}:{progress:JobProgress|undefined}){
  if(!p)return null
  const count=(value:number|undefined):value is number=>typeof value==='number'&&Number.isFinite(value)&&value>=0
  const rows:Array<[string,string]>=[]
  if(count(p.active_solves))rows.push(['Cloud solves in flight',num(p.active_solves,0)])
  if(count(p.cloud_running_solves))rows.push(['Cloud solves executing',num(p.cloud_running_solves,0)])
  if(count(p.allocated_cores))rows.push(['Allocated cores / quota',`${num(p.allocated_cores,0)}${count(p.max_concurrent_cores)?` / ${num(p.max_concurrent_cores,0)}`:' cores'}`])
  if(count(p.account_running_cores)&&count(p.account_reserved_cores))rows.push(['Account core use',`${num(p.account_running_cores,0)} running · ${num(p.account_reserved_cores,0)} reserved`])
  if(count(p.completed_basis_solves))rows.push(['Basis solves completed',`${num(p.completed_basis_solves,0)}${count(p.total_basis_solves)?` / ${num(p.total_basis_solves,0)}`:''}`])
  if(count(p.verified_basis_fields))rows.push(['Fields verified',`${num(p.verified_basis_fields,0)}${count(p.total_basis_solves)?` / ${num(p.total_basis_solves,0)}`:''}`])
  if(count(p.cached_basis_fields))rows.push(['Fields reused from cache',num(p.cached_basis_fields,0)])
  if(count(p.remaining_basis_solves))rows.push(['Basis solves remaining',num(p.remaining_basis_solves,0)])
  if(count(p.queued_basis_solves))rows.push(['Not yet submitted',num(p.queued_basis_solves,0)])
  if(!rows.length)return null
  return<div aria-label="Live parallel cloud simulation progress">{rows.map(([label,value])=><div className="best-so-far" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
}
function CompletedParallel({execution:p}:{execution:ParallelExecution|undefined}){
  if(!p)return null
  const count=(value:number|undefined):value is number=>typeof value==='number'&&Number.isFinite(value)&&value>=0
  const rows:Array<[string,string]>=[]
  if(count(p.peak_parallel_solves))rows.push(['Peak cloud solves executing',num(p.peak_parallel_solves,0)])
  if(count(p.peak_parallel_solves)&&count(p.basis_cores)&&Number.isFinite(p.peak_parallel_solves*p.basis_cores))rows.push(['Peak executing cores',num(p.peak_parallel_solves*p.basis_cores,0)])
  if(count(p.newly_started_basis_solves))rows.push(['New cloud solves',num(p.newly_started_basis_solves,0)])
  if(count(p.cached_basis_fields))rows.push(['Cached basis fields',num(p.cached_basis_fields,0)])
  if(count(p.total_basis_solves))rows.push(['Total basis fields',num(p.total_basis_solves,0)])
  if(!rows.length)return null
  return<div aria-label="Completed parallel cloud simulation summary">{rows.map(([label,value])=><div className="best-so-far" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
}
function Results({job,catalog,stale,canResume,onResume,onRetry}:{job:JobRecord|null;catalog:RoomCatalog|null;stale:boolean;canResume:boolean;onResume:()=>void;onRetry:()=>void}){
  if(!job)return<div className="empty-result"><span className="result-illustration">▦</span><h3>Find your quietest layout.</h3><p>Set sound sources, choose one listening point and enter the number of available panels. Allsolve searches for the lowest noise at that point.</p><div className="search-note">Every permitted layout from zero panels to your limit is compared.</div></div>
  if(job.status==='queued'||job.status==='running'){
    const p=job.progress,verifying=verifyingFields(p?.stage)
    const knownVerification=typeof p?.verified_basis_fields==='number'&&Number.isFinite(p.verified_basis_fields)&&p.verified_basis_fields>=0&&typeof p.total_basis_solves==='number'&&Number.isFinite(p.total_basis_solves)&&p.total_basis_solves>0
    const percent=verifying?(knownVerification?Math.min(100,100*p!.verified_basis_fields!/p!.total_basis_solves!):0):(p?.total?Math.min(100,100*(p.evaluated||0)/p.total):0)
    const progressCaption=verifying?'Layout comparison follows field validation':`${p?.evaluated||0} / ${p?.total||'…'} layouts evaluated`
    return<div className="progress-result" role="status"><span className="live-label"><i className="loader"/> ALLSOLVE SEARCH</span><h3>{verifying?'Verifying pressure fields':job.status==='queued'?'Waiting for solver capacity':'Minimizing point noise'}</h3><p>{p?.message||'Comparing real 3D pressure at your listening point. Matching completed cloud fields are reused.'}</p><div className="progress-track"><span style={{width:`${percent}%`}}/></div><div className="progress-caption"><span>{progressCaption}</span>{(!verifying||knownVerification)&&<strong>{num(percent,0)}%</strong>}</div><ParallelProgress progress={p}/>{p?.best_noise_db!==undefined&&<div className="best-so-far">Lowest level so far <strong>{num(p.best_noise_db)} dB</strong></div>}<details className="provenance"><summary>Current solver provenance</summary><code>Local job {job.job_id}</code>{p?.peak_parallel_solves!==undefined&&<code>Peak simultaneous solves: {p.peak_parallel_solves}</code>}{p?.running_simulation_ids?.map(id=><code key={id}>In-flight simulation {id}</code>)}{p?.latest_simulation_id&&<code>Simulation {p.latest_simulation_id}</code>}{p?.project_url&&<a href={p.project_url} target="_blank" rel="noreferrer">Open Allsolve project ↗</a>}</details></div>
  }
  if(job.status==='failed'||job.status==='interrupted')return<div className="error-result" role="alert"><span className="result-illustration">!</span><h3>{job.status==='interrupted'?'Search paused by a restart':'Search could not finish'}</h3><p>{job.error||'The solver did not return a complete result.'}</p><button className="secondary-button" disabled={!canResume} onClick={onResume}>Resume saved search ↗</button><details className="provenance"><summary>Job details</summary><code>{job.job_id}</code></details></div>
  if(!verifiedPointResult(job.result))return<div className="error-result" role="alert"><h3>Result needs verification</h3><p>The API did not return complete 3D listening-point values and solver provenance.</p><button className="secondary-button" onClick={onRetry}>Reload job status</button></div>
  const result=job.result,layout=result.optimal_layout,names=layout.slot_ids.map(id=>catalog?.slots.find(s=>s.id===id)?.name||id)
  return<div className="results-content">
    {stale&&<div className="stale-notice">Inputs changed. This is the last completed search.</div>}
    <div className="result-status success"><span>✓</span><div><strong>Lowest noise layout found</strong><small>Within the panel limit and allowed positions</small></div></div>
    <div className="point-score"><span>AT YOUR LISTENING POINT</span><strong>{num(layout.noise_db,2)}<small>dB</small></strong><p>Normalized SPL at 125 Hz · re 20 μPa</p></div>
    <div className="noise-comparison"><div><span>Untreated room</span><strong>{num(result.baseline.noise_db,2)} <small>dB</small></strong></div><div><span>With this layout</span><strong>{num(layout.noise_db,2)} <small>dB</small></strong></div></div>
    <div className="point-improvement"><span>Modeled pressure change</span><strong>{layout.reduction_db>0?'−':layout.reduction_db<0?'+':''}{num(Math.abs(layout.reduction_db),2)} dB</strong></div>
    <div className="result-summary panel-count-summary"><div><span className="big-number">{layout.object_count}</span><span>{layout.object_count===1?'panel used':'panels used'}</span></div><div><strong>{result.max_panels}</strong><span>panels available</span></div></div>
    <div className="layout-list"><span className="eyebrow">LOWEST NOISE POSITIONS</span>{names.length?names.map((name,i)=><div key={layout.slot_ids[i]}><span className="layout-index">{(catalog?.slots.findIndex(s=>s.id===layout.slot_ids[i])??-1)+1||i+1}</span><strong>{name}</strong></div>):<p>The untreated room gives the minimum modeled noise under these constraints.</p>}</div>
    <div className="search-scope"><strong>{result.search.evaluated_layouts} layouts evaluated</strong><p>{result.search.optimality_scope||`All allowed layouts using zero to ${result.max_panels} panels were compared. Lowest listening-point noise wins; equal levels prefer fewer panels.`}</p><small>Normalized model levels use the entered source levels. This is a single-frequency result, with assumed source directivity and treatment properties.</small></div>
    <CompletedParallel execution={result.parallel_execution}/><details className="provenance"><summary>Pressure, source inputs & job IDs</summary><p className="point-details">Listener XYZ: {result.listener_m.map(v=>num(v,3)).join(' / ')} m<br/>Untreated RMS: {result.baseline.pressure_rms_pa.toExponential(3)} Pa<br/>Optimized RMS: {layout.pressure_rms_pa.toExponential(3)} Pa</p>{result.sources.map(s=><code key={s.id}>{s.id}: {num(s.level_db,3)} dB · XYZ {s.position_m.map(v=>num(v,3)).join(', ')} m</code>)}<a href={result.project_url} target="_blank" rel="noreferrer">Open 3D model in Allsolve ↗</a><code>Project {result.project_id}</code><code>Local job {job.job_id}</code>{layout.simulation_ids.map(id=><code key={id}>Simulation {id}</code>)}</details>
  </div>
}
function App(){
  const[catalog,setCatalog]=useState<RoomCatalog|null>(null),[health,setHealth]=useState<Health|null>(null),[input,setInput]=useState<PointPlan>(initial)
  const[tab,setTab]=useState<'sources'|'listener'|'panels'>('sources'),[selectedSource,setSelectedSource]=useState<string|null>('src1'),[placement,setPlacement]=useState<Placement>(null)
  const[job,setJob]=useState<JobRecord|null>(null),[pollId,setPollId]=useState<string|null>(null),[loading,setLoading]=useState(true),[starting,setStarting]=useState(false)
  const[connectionError,setConnectionError]=useState<string|null>(null),[requestError,setRequestError]=useState<string|null>(null)
  useEffect(()=>{
    const controller=new AbortController()
    async function load(){
      const requested=sharedJob(window.location.search),oldId=stored(jobKey)
      const explicitFetch=requested.id?getJob(requested.id,controller.signal):Promise.resolve(null)
      const savedFetch=!requested.explicit&&oldId?getJob(oldId,controller.signal):Promise.resolve(null)
      const latestFetch=!requested.explicit?getLatest(controller.signal):Promise.resolve(null)
      const[roomResponse,healthResponse,explicitResponse,savedResponse,latestResponse]=await Promise.allSettled([getCatalog(controller.signal),getHealth(controller.signal),explicitFetch,savedFetch,latestFetch])
      if(controller.signal.aborted)return
      let chosen=requested.explicit?(explicitResponse.status==='fulfilled'?explicitResponse.value:null):preferredJob(savedResponse.status==='fulfilled'?savedResponse.value:null,latestResponse.status==='fulfilled'?latestResponse.value:null)
      if(requested.error)setRequestError(requested.error)
      else if(requested.explicit&&explicitResponse.status==='rejected')setRequestError(`Could not load requested job ${requested.id}: ${explicitResponse.reason instanceof Error?explicitResponse.reason.message:'The API could not retrieve this job.'}`)
      else if(!requested.explicit&&!chosen&&latestResponse.status==='rejected')setRequestError(`Could not load the latest job: ${latestResponse.reason instanceof Error?latestResponse.reason.message:'The API could not retrieve the latest job.'}`)
      if(roomResponse.status==='fulfilled'){
        const room=roomResponse.value;setCatalog(room)
        let draft:PointPlan|undefined
        if(!requested.explicit){try{const data=stored(draftKey);if(data){const parsed:unknown=JSON.parse(data);if(validPointPlan(parsed,room))draft=parsed}}catch{/* Ignore obsolete drafts. */}}
        const defaults=validPointPlan(room.point_defaults,room)?room.point_defaults:{...initial,allowed_slot_ids:room.slots.map(s=>s.id)}
        if(chosen&&!validPointPlan(chosen.request,room)){setRequestError(requested.explicit?'The requested job does not contain valid listening-point inputs.':'The selected job does not contain valid listening-point inputs.');chosen=null}
        const start=draft||(validPointPlan(chosen?.request,room)?chosen.request:undefined)||defaults
        setInput(start);setSelectedSource(start.sources[0]?.id||null)
      }else setConnectionError(roomResponse.reason instanceof Error?roomResponse.reason.message:'The 3D catalog is unavailable.')
      if(chosen){setJob(chosen);save(jobKey,chosen.job_id);if(chosen.status==='queued'||chosen.status==='running')setPollId(chosen.job_id)}
      if(healthResponse.status==='fulfilled')setHealth(healthResponse.value)
      if(!controller.signal.aborted)setLoading(false)
    }void load();return()=>controller.abort()
  },[])
  useEffect(()=>{if(!loading&&catalog)save(draftKey,JSON.stringify(input))},[input,loading,catalog])
  useEffect(()=>{
    if(!pollId)return
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined
    async function poll(){try{const current=await getJob(pollId!,controller.signal);if(controller.signal.aborted)return;setJob(current);setRequestError(null);if(current.status==='queued'||current.status==='running')timer=setTimeout(()=>void poll(),3000);else setPollId(null)}catch(e){if(controller.signal.aborted)return;setRequestError(e instanceof Error?e.message:'Could not refresh the solver status.');timer=setTimeout(()=>void poll(),6000)}}
    void poll();return()=>{controller.abort();if(timer)clearTimeout(timer)}
  },[pollId])
  const error=useMemo(()=>{
    if(!catalog)return null
    if(!input.sources.length)return 'Enable at least one sound source.'
    if(input.sources.length>3)return 'Select at most three simultaneous sources.'
    if(!Number.isInteger(input.max_panels)||input.max_panels<0||input.max_panels>6)return 'Available panels must be a whole number from 0 to 6.'
    for(const source of input.sources){
      if(!Number.isFinite(source.level_db)||source.level_db<0||source.level_db>120)return `${source.id}: source level must be 0–120 dB.`
      if(!source.position_m.every(Number.isFinite)||source.position_m.some((v,i)=>v<.081||v>catalog.room.size_m[i]-.081))return `${source.id}: position its 0.08 m source sphere fully inside the room.`
    }
    if(!input.listener_m.every(Number.isFinite)||input.listener_m.some((v,i)=>v<=0||v>=catalog.room.size_m[i]))return 'Place the listening point inside the room in all three dimensions.'
    for(let i=0;i<input.sources.length;i++){
      const s=input.sources[i],distance=(a:Vec3,b:Vec3)=>Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2])
      if(distance(s.position_m,input.listener_m)<=.08)return 'The listening point must be outside the source spheres.'
      for(let j=i+1;j<input.sources.length;j++)if(distance(s.position_m,input.sources[j].position_m)<=.16)return 'Move overlapping sound sources farther apart.'
    }return null
  },[input,catalog])
  const ready=Boolean(catalog&&(health?.allsolve_ready??catalog.allsolve_ready)),busy=starting||pollId!==null,verifying=verifyingFields(job?.progress?.stage)
  const stale=Boolean(job?.status==='completed'&&!samePointPlan(job.request,input))
  const result=verifiedPointResult(job?.result)?job.result:null
  const update=(patch:Partial<PointPlan>)=>setInput(current=>({...current,...patch}))
  function updateSource(id:string,patch:Partial<PointPlan['sources'][number]>){setInput(current=>({...current,sources:current.sources.map(source=>source.id===id?{...source,...patch}:source)}))}
  function toggleSource(id:string){
    setRequestError(null);setPlacement(null)
    if(input.sources.some(source=>source.id===id)){update({sources:input.sources.filter(s=>s.id!==id)});if(selectedSource===id)setSelectedSource(null);return}
    if(input.sources.length>=3){setRequestError('Disable one source before adding another. The search supports three simultaneous sources.');return}
    const source=catalog?.sources.find(s=>s.id===id);if(!source)return
    update({sources:[...input.sources,{id,position_m:[...source.position_m],level_db:referenceLevel}]});setSelectedSource(id)
  }
  function selectSource(id:string){setTab('sources');setPlacement(null);if(!input.sources.some(s=>s.id===id))toggleSource(id);else setSelectedSource(id)}
  function toggleSlot(id:string){update({allowed_slot_ids:input.allowed_slot_ids.includes(id)?input.allowed_slot_ids.filter(s=>s!==id):[...input.allowed_slot_ids,id]})}
  function place(x:number,y:number){if(!catalog||!placement)return;const[w,l]=catalog.room.size_m,px=Math.max(.1,Math.min(w-.1,x)),py=Math.max(.1,Math.min(l-.1,y));if(placement.kind==='listener')update({listener_m:[px,py,input.listener_m[2]]});else{const s=input.sources.find(s=>s.id===placement.source_id);if(s)updateSource(s.id,{position_m:[px,py,s.position_m[2]]})}setPlacement(null)}
  async function run(){if(!ready||busy||error)return;setStarting(true);setRequestError(null);try{const id=await startMinimization(input);rememberJob(id);setJob({job_id:id,status:'queued',kind:'room3d_point',request:input});setPollId(id)}catch(e){setRequestError(e instanceof Error?e.message:'The search could not start.')}finally{setStarting(false)}}
  async function resume(){if(!job||busy||!ready)return;setStarting(true);setRequestError(null);try{const id=await resumeJob(job.job_id);rememberJob(id);setJob({...job,status:'queued',error:undefined});setPollId(id)}catch(e){setRequestError(e instanceof Error?e.message:'The saved search could not resume.')}finally{setStarting(false)}}
  const roomSize=catalog?.room.size_m||[5.705,5.965,2.355]
  return<div className="app-shell">
    <header className="topbar"><a className="brand" href="/" aria-label="RoomValue home"><span className="brand-mark"><i/><i/><i/></span><span>RoomValue</span></a><span className="topbar-note">ACOUSTIC SPACE PLANNER</span><div className="topbar-status" title={health?.message}><i className={ready?'online':''}/>{loading?'Connecting':ready?'Allsolve connected':health?.deployment==='worker-pc'?'PC backend offline':'Solver unavailable'}</div></header>
    <main><section className="intro"><div><div className="eyebrow">PUT YOUR PANELS WHERE THEY HELP MOST</div><h1>Find your quietest <em>point.</em></h1><p>Set your sound sources and panel limit. Find the placement that minimizes noise at your chosen listening point.</p></div><div className="dataset-stamp"><span className="eyebrow">REAL ROOM / DECHORATE</span><strong>5.705 × 5.965 × 2.355 <small>m</small></strong><span>Calibrated room geometry · 3D simulation at 125 Hz</span></div></section>
      {connectionError&&<div className="connection-banner" role="alert"><strong>The 3D catalog could not load.</strong> {connectionError} <button onClick={()=>location.reload()}>Reconnect</button></div>}
      <div className="workspace">
        <aside className="controls-panel panel"><div className="panel-heading"><span className="eyebrow">01 / SET YOUR CONSTRAINTS</span><h2>Sources & listening point</h2></div><div className="control-tabs" role="tablist" aria-label="Room inputs">{(['sources','listener','panels']as const).map(name=><button key={name} role="tab" aria-selected={tab===name} onClick={()=>{setTab(name);setPlacement(null)}}>{name==='sources'?'Sources':name==='listener'?'Listen here':'Panels'}<small>{name==='sources'?input.sources.length:name==='listener'?1:input.allowed_slot_ids.length}</small></button>)}</div>
          <div className="config-content point-config">
            {tab==='sources'&&<><div className="section-intro"><h3>Where does sound come from?</h3><p>Enable up to three sources. Start at a dataset position, then edit its XYZ location and normalized source level.</p></div><div className="source-list point-source-list">{catalog?.sources.map(def=>{const source=input.sources.find(s=>s.id===def.id);return<div className={`source-card ${source?'active':''} ${selectedSource===def.id?'focused-source':''}`} key={def.id}><label><input type="checkbox" checked={Boolean(source)} onChange={()=>toggleSource(def.id)}/><span className="source-code">{def.id.replace('src','S')}</span><span><strong>{def.name}</strong><small>{source?'Active source · editable position':`Dataset XYZ ${def.position_m.map(v=>num(v,2)).join(' / ')} m`}</small></span></label>{def.position_status&&def.position_status!=='calibrated'&&<small className="position-warning">Dataset position is approximate</small>}{source&&<div className="source-editor"><Numeric label={`${def.id} source level`} value={source.level_db} min={0} max={120} step={1} unit="dB" onChange={n=>updateSource(def.id,{level_db:n})}/><div className="xyz-fields">{(['X','Y','Z']as const).map((axis,i)=><Numeric key={axis} label={`${def.id} ${axis}`} value={source.position_m[i]} min={.081} max={roomSize[i]-.081} step={.01} unit="m" onChange={n=>{const position=[...source.position_m]as Vec3;position[i]=n;updateSource(def.id,{position_m:position})}}/>)}</div><div className="position-actions"><button className="text-button" onClick={()=>{updateSource(def.id,{position_m:[...def.position_m]});setPlacement(null)}}>Reset dataset position</button><button className="text-button" onClick={()=>{setSelectedSource(def.id);setPlacement(placement?.kind==='source'&&placement.source_id===def.id?null:{kind:'source',source_id:def.id})}}>{placement?.kind==='source'&&placement.source_id===def.id?'Cancel moving':'Move on room floor'}</button></div></div>}</div>})}</div><p className="config-note">Source dB describes normalized pressure at each spherical emitter, referenced to 20 μPa. Independent source powers are summed.</p></>}
            {tab==='listener'&&<><div className="section-intro"><h3>Where should noise be lowest?</h3><p>Choose one 3D listening point. The search minimizes its sound level across all permitted panel layouts.</p></div><div className="listener-card"><span className="listener-symbol">⊕</span><div><strong>Listening point</strong><small>XYZ {input.listener_m.map(v=>num(v,2)).join(' / ')} m</small></div></div><div className="zone-editor point-editor">{(['X','Y','Z']as const).map((axis,i)=><Numeric key={axis} label={i===2?'Listening height Z':`Listening point ${axis}`} value={input.listener_m[i]} min={.01} max={roomSize[i]-.01} step={.01} unit="m" onChange={n=>{const point=[...input.listener_m]as Vec3;point[i]=n;update({listener_m:point})}}/>)}<button className="secondary-button" onClick={()=>setPlacement(placement?.kind==='listener'?null:{kind:'listener'})}>{placement?.kind==='listener'?'Cancel moving':'Move listening point on floor'}</button></div><p className="config-note">Floor placement changes X and Y while preserving the entered listening height. Results report normalized SPL at 125 Hz.</p></>}
            {tab==='panels'&&<><div className="section-intro"><h3>Where can your panels go?</h3><p>Allow or exclude positions. All combinations from zero panels to your available count are compared.</p></div><div className="slot-list">{catalog?.slots.map((slot,i)=><label className={`slot-card ${input.allowed_slot_ids.includes(slot.id)?'active':''}`} key={slot.id}><input type="checkbox" checked={input.allowed_slot_ids.includes(slot.id)} onChange={()=>toggleSlot(slot.id)}/><span className="slot-code">{i+1}</span><span><strong>{slot.name}</strong><small>{num(slot.area_m2,0)} m² face · {slot.size_m.map(v=>num(v,1)).join(' × ')} m</small></span></label>)}</div><p className="config-note">Each panel uses the same illustrative damping material. The optimizer chooses the combination with the lowest listening-point noise.</p></>}
          </div><div className="budget-section panel-limit"><div className="section-label">PANEL AVAILABILITY <span>Maximum count</span></div><Numeric label="Available panels" value={input.max_panels} min={0} max={6} step={1} unit="panels" onChange={n=>update({max_panels:n})}/><p className="config-note">The solver may use fewer panels if they give the same or lower noise.</p></div>
        </aside>
        <section className="scene-panel panel"><div className="panel-heading scene-heading"><div><span className="eyebrow">02 / CHOOSE YOUR POINT</span><h2>The dEchorate room</h2><p>Explore the measured room, source locations and your listening point.</p></div><span className="room-tag">3D MODEL</span></div>{catalog?<RoomView catalog={catalog} sources={input.sources} listener={input.listener_m} allowedSlots={input.allowed_slot_ids} recommendedSlots={!stale?result?.optimal_layout.slot_ids||[]:[]} selectedSource={selectedSource} placement={placement} noiseDb={!stale?result?.optimal_layout.noise_db:undefined} onSelectSource={selectSource} onSelectSlot={id=>{toggleSlot(id);setTab('panels');setPlacement(null)}} onSelectListener={()=>{setTab('listener');setPlacement(null)}} onPlacePosition={place}/>:<div className="room-loading"><span className="loader"/><p>{loading?'Loading the dataset room…':'Reconnect the API to load the room.'}</p></div>}
          <div className="room-metrics"><div><span>ROOM VOLUME</span><strong>{catalog?num(catalog.room.volume_m3):'80.1'} <small>m³</small></strong></div><div><span>ACTIVE SOURCES</span><strong>{input.sources.length} <small>/ 3</small></strong></div><div><span>AVAILABLE PANELS</span><strong>{input.max_panels} <small>maximum</small></strong></div><div><span>CANDIDATE POSITIONS</span><strong>{input.allowed_slot_ids.length} <small>/ 6</small></strong></div></div>
          <div className="model-context"><div className="context-symbol">∿</div><div><h3>One listening point. Every allowed panel layout.</h3><p>Allsolve computes pressure in the real 3D room. The optimizer checks untreated and treated layouts up to your panel limit, then selects the lowest normalized sound level at your point. Matching cloud fields are reused; moving sources can require a new mesh.</p><a href={catalog?.dataset.url||'https://zenodo.org/records/4626590'} target="_blank" rel="noreferrer">Explore the source dataset ↗</a></div></div>
          <details className="assumptions"><summary>Model assumptions & dB interpretation</summary><p>Input and output levels are normalized SPL in dB relative to 20 μPa at 125 Hz. They are not calibrated dB(A). Source directivity, room surface loss and the panel damping material remain simulation assumptions. The optimum applies to the six discrete candidate positions and the entered panel limit.</p><div className="preview-links"><a href="/api/room3d/preview/room" target="_blank" rel="noreferrer">Earlier verified room geometry ↗</a><a href="/api/room3d/preview/field" target="_blank" rel="noreferrer">Earlier verified pressure slice ↗</a></div></details>
        </section>
        <aside className="results-panel panel"><div className="panel-heading"><span className="eyebrow">03 / MINIMIZE THE NOISE</span><h2>Your quietest layout</h2><p>Lowest sound level at the chosen point, within your available panel count.</p></div><div className="run-area"><button className="run-button" disabled={!ready||busy||Boolean(error)} onClick={()=>void run()}>{busy?(verifying?'Verifying results…':'Searching in Allsolve…'):'Minimize noise at point'}<span>{busy?<i className="loader"/>:'↗'}</span></button><span className="run-caption">Real 3D solves · zero to your panel limit</span>{error&&<p className="inline-error" role="alert">{error}</p>}{requestError&&<p className="inline-error" role="alert">{requestError}</p>}{health?.message&&!loading&&<p className={ready?'run-caption':'inline-error'}>{health.message}</p>}</div><div className="results-divider"><span>SEARCH RESULTS</span><i/></div><Results job={job} catalog={catalog} stale={stale} canResume={ready&&!busy} onResume={()=>void resume()} onRetry={()=>job&&setPollId(job.job_id)}/>{stale&&validPointPlan(job?.request,catalog||undefined)&&<button className="text-button load-inputs" onClick={()=>{if(job?.request){setInput(job.request);setPlacement(null)}}}>Inspect inputs used for this result</button>}</aside>
      </div><footer><span>RoomValue <i>/</i> Physics informed acoustic planning</span><span>125 Hz normalized SPL · assumed materials · lowest point noise within the panel limit</span></footer>
    </main>
  </div>
}
export default App
