import { useMemo,useRef,useState } from 'react'
import type { PanelSlot,RoomCatalog,SoundSource,Vec3 } from './api'
export type Placement={kind:'listener'}|{kind:'source';source_id:string}|null
type Face={vertices:Vec3[];fill:string;stroke:string;opacity:number}
interface Props{
  catalog:RoomCatalog;sources:SoundSource[];listener:Vec3;allowedSlots:string[];recommendedSlots:string[]
  selectedSource:string|null;placement:Placement;noiseDb?:number
  onSelectSource:(id:string)=>void;onSelectSlot:(id:string)=>void;onSelectListener:()=>void;onPlacePosition:(x:number,y:number)=>void
}
function boxFaces(origin:Vec3,size:Vec3,fill:string,stroke:string,opacity=1):Face[]{
  const[x,y,z]=origin,[w,l,h]=size
  return [
    [[x,y,z],[x+w,y,z],[x+w,y+l,z],[x,y+l,z]],[[x,y,z+h],[x+w,y,z+h],[x+w,y+l,z+h],[x,y+l,z+h]],
    [[x,y,z],[x+w,y,z],[x+w,y,z+h],[x,y,z+h]],[[x,y+l,z],[x+w,y+l,z],[x+w,y+l,z+h],[x,y+l,z+h]],
    [[x,y,z],[x,y+l,z],[x,y+l,z+h],[x,y,z+h]],[[x+w,y,z],[x+w,y+l,z],[x+w,y+l,z+h],[x+w,y,z+h]],
  ].map(vertices=>({vertices:vertices as Vec3[],fill,stroke,opacity}))
}
export default function RoomView(props:Props){
  const{catalog,sources,listener,allowedSlots,recommendedSlots,placement}=props
  const[yaw,setYaw]=useState(-.65),[pitch,setPitch]=useState(.61),[zoom,setZoom]=useState(1)
  const drag=useRef<{x:number;y:number;yaw:number;pitch:number}|null>(null),svgRef=useRef<SVGSVGElement|null>(null)
  const[w,l,h]=catalog.room.size_m,scale=57*zoom,origin={x:440,y:315}
  const project=(point:Vec3)=>{
    const x=point[0]-w/2,y=point[1]-l/2,z=point[2],rx=Math.cos(yaw)*x-Math.sin(yaw)*y,ry=Math.sin(yaw)*x+Math.cos(yaw)*y
    // Larger depth points toward the elevated camera; paint those objects last.
    return{x:origin.x+rx*scale,y:origin.y+(ry*Math.sin(pitch)-z*Math.cos(pitch))*scale,depth:ry*Math.cos(pitch)+z*Math.sin(pitch)}
  }
  const points=(vertices:Vec3[])=>vertices.map(v=>{const p=project(v);return`${p.x},${p.y}`}).join(' ')
  const depth=(vertices:Vec3[])=>vertices.reduce((sum,p)=>sum+project(p).depth,0)/vertices.length
  const floor:Vec3[]=[[0,0,0],[w,0,0],[w,l,0],[0,l,0]],walls:Vec3[][]=[
    [[0,0,0],[0,l,0],[0,l,h],[0,0,h]],[[w,0,0],[w,l,0],[w,l,h],[w,0,h]],
    [[0,0,0],[w,0,0],[w,0,h],[0,0,h]],[[0,l,0],[w,l,0],[w,l,h],[0,l,h]],
  ]
  const grid=useMemo(()=>{const lines:[Vec3,Vec3][]=[];for(let x=.5;x<w;x+=.5)lines.push([[x,0,0],[x,l,0]]);for(let y=.5;y<l;y+=.5)lines.push([[0,y,0],[w,y,0]]);return lines},[w,l])
  const positionedSources=catalog.sources.map(source=>({...source,position_m:sources.find(s=>s.id===source.id)?.position_m??source.position_m}))
  const scene:Array<{id:string;kind:'slot'|'listener'|'source';depth:number;slot?:PanelSlot}>=[
    ...catalog.slots.map(slot=>({id:slot.id,kind:'slot' as const,depth:project(slot.position_m.map((v,i)=>v+slot.size_m[i]/2) as Vec3).depth,slot})),
    {id:'listener',kind:'listener' as const,depth:project(listener).depth},
    ...positionedSources.map(source=>({id:source.id,kind:'source' as const,depth:project(source.position_m).depth})),
  ].sort((a,b)=>a.depth-b.depth)
  const line=(a:Vec3,b:Vec3,stroke:string,width=1,dashed=false)=>{const pa=project(a),pb=project(b);return<line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke={stroke} strokeWidth={width} strokeDasharray={dashed?'4 4':undefined}/>}
  const faces=(items:Face[])=>[...items].sort((a,b)=>depth(a.vertices)-depth(b.vertices)).map((face,i)=><polygon key={i} points={points(face.vertices)} fill={face.fill} stroke={face.stroke} strokeWidth="1.2" opacity={face.opacity}/>)
  function place(event:React.MouseEvent<SVGPolygonElement>){
    if(!placement||!svgRef.current)return
    const svg=svgRef.current,pt=svg.createSVGPoint();pt.x=event.clientX;pt.y=event.clientY
    const inverse=svg.getScreenCTM()?.inverse();if(!inverse)return
    const local=pt.matrixTransform(inverse),rx=(local.x-origin.x)/scale,ry=(local.y-origin.y)/(scale*Math.sin(pitch))
    props.onPlacePosition(Math.cos(yaw)*rx+Math.sin(yaw)*ry+w/2,-Math.sin(yaw)*rx+Math.cos(yaw)*ry+l/2)
  }
  const activate=(event:React.KeyboardEvent,action:()=>void)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();action()}}
  return<div className={`room-view ${placement?'placing':''}`}>
    <div className="view-topline"><span><i/> DATASET GEOMETRY</span><span>125 Hz · 3D acoustic waves</span></div>
    <svg ref={svgRef} viewBox="0 0 880 470" role="img" aria-label="Interactive 3D dEchorate room with movable sound sources, listening point and candidate acoustic panels. Drag to rotate."
      onPointerDown={event=>{if(placement||(event.target as Element).closest('[data-object]'))return;drag.current={x:event.clientX,y:event.clientY,yaw,pitch};event.currentTarget.setPointerCapture(event.pointerId)}}
      onPointerMove={event=>{const d=drag.current;if(!d)return;setYaw(d.yaw+(event.clientX-d.x)*.008);setPitch(Math.max(.25,Math.min(1.25,d.pitch+(event.clientY-d.y)*.006)))}}
      onPointerUp={()=>{drag.current=null}} onPointerCancel={()=>{drag.current=null}}>
      <defs><radialGradient id="room-shadow"><stop offset="0" stopColor="#19372a" stopOpacity=".1"/><stop offset="1" stopColor="#19372a" stopOpacity="0"/></radialGradient><radialGradient id="source-fill"><stop offset="0" stopColor="#ffbd87"/><stop offset="1" stopColor="#dd7c46"/></radialGradient></defs>
      <ellipse cx="440" cy="345" rx="310" ry="99" fill="url(#room-shadow)"/><polygon points={points(floor)} fill="#eef2eb" stroke="#80988b" strokeWidth="1.6" onClick={place}/>
      <g pointerEvents="none">{grid.map(([a,b],i)=><g key={i}>{line(a,b,'#d4dfd5')}</g>)}
        {walls.filter(wall=>depth(wall.map(([x,y])=>[x,y,0] as Vec3))<0).sort((a,b)=>depth(a)-depth(b)).map((wall,i)=><polygon key={i} points={points(wall)} fill={i===0?'#e5ece2':'#f3f6f0'} fillOpacity=".9" stroke="#94a79a" strokeWidth="1.4"/>)}
        {walls.filter(wall=>depth(wall.map(([x,y])=>[x,y,0] as Vec3))>=0).map((wall,i)=><polygon key={i} points={points(wall)} fill="none" stroke="#9aafa0" strokeWidth="1" strokeDasharray="4 5" opacity=".65"/>)}
      </g>
      {scene.map(item=>{
        if(item.kind==='slot'&&item.slot){const slot=item.slot,allowed=allowedSlots.includes(slot.id),chosen=recommendedSlots.includes(slot.id),p=project(slot.position_m.map((v,i)=>v+slot.size_m[i]/2) as Vec3)
          return<g key={`slot-${slot.id}`} data-object="slot" className="scene-object" role="button" tabIndex={0} aria-label={`${slot.name}; ${chosen?'lowest noise layout':allowed?'available':'excluded'}`} onClick={()=>props.onSelectSlot(slot.id)} onKeyDown={e=>activate(e,()=>props.onSelectSlot(slot.id))}>
            <title>{slot.name} · {slot.size_m.map(v=>v.toFixed(2)).join(' × ')} m</title>{faces(boxFaces(slot.position_m,slot.size_m,chosen?'#b7d577':allowed?'#e7cbb1':'#e4e6e0',chosen?'#668b37':allowed?'#b99575':'#b9c0b6',allowed?.95:.35))}
            <circle cx={p.x} cy={p.y} r="10" fill={chosen?'#44692b':'#fff'} stroke={chosen?'#44692b':'#c3b099'}/><text x={p.x} y={p.y+3.5} textAnchor="middle" fontSize="10" fontWeight="700" fill={chosen?'#fff':'#796c59'}>{catalog.slots.findIndex(s=>s.id===slot.id)+1}</text>
          </g>
        }
        if(item.kind==='listener'){const p=project(listener),fp=project([listener[0],listener[1],0]);return<g key="listener" data-object="listener" className="scene-object" role="button" tabIndex={0} aria-label="Selected listening point" onClick={props.onSelectListener} onKeyDown={e=>activate(e,props.onSelectListener)}>
          <title>Listening point · XYZ {listener.map(v=>v.toFixed(3)).join(', ')} m{props.noiseDb!==undefined?` · ${props.noiseDb.toFixed(2)} dB normalized SPL`:''}</title>
          <line x1={p.x} y1={p.y} x2={fp.x} y2={fp.y} stroke="#538d70" strokeDasharray="4 3"/><ellipse cx={fp.x} cy={fp.y} rx="9" ry="3" fill="#9db9a6" opacity=".45"/>
          <circle cx={p.x} cy={p.y} r="15" fill="#e4f0e4" stroke="#55966d" strokeWidth="1.4"/><circle cx={p.x} cy={p.y} r="4" fill="#317e55"/>
          <path d={`M${p.x-20} ${p.y}h9 M${p.x+11} ${p.y}h9 M${p.x} ${p.y-20}v9 M${p.x} ${p.y+11}v9`} stroke="#4b8b65" strokeWidth="1.3"/>
          <g transform={`translate(${p.x+20},${p.y-23})`}><rect width={props.noiseDb!==undefined?136:106} height="25" rx="5" fill="#fff" stroke="#c7ddcc"/><text x="9" y="16" fill="#417650" fontSize="10" fontWeight="700">{props.noiseDb!==undefined?`Listener · ${props.noiseDb.toFixed(1)} dB`:'Listening point'}</text></g>
        </g>}
        const definition=positionedSources.find(source=>source.id===item.id)!,active=sources.find(s=>s.id===definition.id),p=project(definition.position_m),fp=project([definition.position_m[0],definition.position_m[1],0])
        return<g key={`source-${definition.id}`} data-object="source" className="scene-object" role="button" tabIndex={0} aria-label={`${definition.name}; ${active?'enabled':'disabled'}`} onClick={()=>props.onSelectSource(definition.id)} onKeyDown={e=>activate(e,()=>props.onSelectSource(definition.id))} opacity={active?1:.4}>
          <title>{definition.name} · XYZ {definition.position_m.map(v=>v.toFixed(2)).join(', ')} m{active?` · ${active.level_db.toFixed(1)} dB normalized source level`:''}</title>
          <line x1={p.x} y1={p.y} x2={fp.x} y2={fp.y} stroke="#cf9b71" strokeDasharray="4 3"/><ellipse cx={fp.x} cy={fp.y} rx="9" ry="3" fill="#d6bb9e" opacity=".45"/>
          {active&&<circle cx={p.x} cy={p.y} r={props.selectedSource===active.id?24:20} fill="none" stroke="#e3a779" strokeWidth={props.selectedSource===active.id?1.8:1} opacity=".7"/>}<circle cx={p.x} cy={p.y} r={active?12:5} fill={active?'url(#source-fill)':'#c2b9a8'} stroke="#fff8ef" strokeWidth="2"/>
          {active&&<><path d={`M${p.x-4} ${p.y-3} L${p.x+1} ${p.y-6} L${p.x+1} ${p.y+6} L${p.x-4} ${p.y+3} Z`} fill="white"/><text x={p.x} y={p.y+35} textAnchor="middle" fill="#855937" fontSize="11" fontWeight="700">{definition.id.toUpperCase()} · {active.level_db.toFixed(1)} dB</text></>}
        </g>
      })}
      <g pointerEvents="none">{line([0,0,0],[.8,0,0],'#937b69',2)}{line([0,0,0],[0,.8,0],'#668a70',2)}{line([0,0,0],[0,0,.8],'#6f8aa1',2)}{([[.95,0,0,'X'],[0,.95,0,'Y'],[0,0,.95,'Z']] as[number,number,number,string][]).map(([x,y,z,label])=>{const p=project([x,y,z]);return<text key={label} x={p.x} y={p.y} fontSize="11" fill="#60766a" textAnchor="middle">{label}</text>})}</g>
    </svg>
    <div className="view-bottomline"><span>{placement?`Click the floor to move ${placement.kind==='listener'?'the listening point':placement.source_id}; height is preserved`:'Drag to orbit · click sources, listener or panels'}</span><div className="view-actions"><button aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(.65,z-.1))}>−</button><button aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(1.35,z+.1))}>+</button><button onClick={()=>{setYaw(-.65);setPitch(.61);setZoom(1)}}>Reset view</button></div></div>
    <div className="room-legend"><span><i className="source-key"/> Sound source</span><span><i className="zone-key"/> Listening point</span><span><i className="panel-key"/> Candidate panel</span>{recommendedSlots.length>0&&<span><i className="chosen-key"/> Lowest noise layout</span>}</div>
  </div>
}
