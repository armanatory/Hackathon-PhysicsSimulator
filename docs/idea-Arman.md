# Ideas — Arman

## ChatGPT

| Project / surprising question | Difficulty | Novelty | Demo strength |
|---|---:|---:|---:|
| **Last Cool Corner** — “Where should you sleep during a heatwave blackout?” | 3/5 | 5/5 | 5/5 |
| **One Fan, Many Lives** — “Where should the only fan in a hot room actually go?” | 4/5 | 5/5 | 5/5 |
| **Shade One Window** — “If you can cover only one window, which one buys you the most time?” | 2/5 | 4/5 | 5/5 |
| **Firefighter Door** — “Should this door be opened to remove heat, or will it make conditions worse?” | 4/5 | 5/5 | 5/5 |
| **Medicine Without a Fridge** — “Where in this powerless room will medicine stay coolest longest?” | 3/5 | 5/5 | 5/5 |
| **Baby Seat Heat Trap** — “Which parts of a parked car become dangerous first?” | 3/5 | 4/5 | 5/5 |
| **Quiet Refuge** — “Where should a hospital bed go to escape the most noise?” | 3/5 | 4/5 | 4/5 |
| **Earthquake Shelf** — “Where should emergency supplies sit so vibration affects them least?” | 3/5 | 4/5 | 4/5 |
| **Phone Rescue** — “What passive geometry keeps an emergency phone alive longest in extreme heat?” | 3/5 | 4/5 | 4/5 |
| **One Hole** — “Where should you cut one ventilation opening into an emergency shelter?” | 4/5 | 5/5 | 5/5 |

## Grock
This is an ideation request, not a build. Allsolve can actually run these: **solid mechanics, heat solid/fluid, laminar flow, acoustics, electrostatics, current flow, EM waves, magnetism, FSI, acoustic–structure, electromechanics**. It cannot do turbulent HVAC, crowds-as-particles, or ionizing radiation — so none of that is here.

Your last line cut off at “prefer ideas with: * one”. I treated that as: **one geometry, one coupling, one decision, one metric**, weekend-sized.

I shuffled domains against non-obvious physics on purpose. Hearing-loop vs rebar, not “wheelchair ramp FEA”.

---

#### 1. Disability × magnetics  
**Hearing loops that die on rebar**

Audio-frequency induction loops in clinics, churches, and council halls often fail for T-coil users because the steel mesh in the floor shorts the field. People are told their aid is broken.

- **Allsolve:** Magnetism A or H + current flow, harmonic, 100 Hz–5 kHz. A rectangular loop over a rebar grid in a lossy slab.
- **Decision:** loop height, figure-8 vs perimeter, rebar-aware routing.
- **Metric:** B-field at ear height vs IEC 60118-4 (100 mA/m).
- **Weekend geo:** 8×6 m room, 150 mm slab, 200 mm rebar pitch.
- **Why it isn’t ChatGPT:** judges expect ramps. This is the actual broken accessibility tech in public buildings.

---

#### 2. Ageing × structural stress  
**Grab bars that pull out of rented bathrooms**

Hip-fracture falls often start as a 1.3 kN yank on a bar whose anchors live in tile + plasterboard, not studs. Landlords install the cheap ones.

- **Allsolve:** Solid mechanics + contact, static then transient yank.
- **Decision:** toggle vs chemical vs spanning-plate; tile thickness; grout gap.
- **Metric:** bar displacement at 1.5 kN and whether the tile cone punches out.
- **Weekend geo:** 400×400 mm wall patch, one bar, three anchor types.
- **Why it isn’t ChatGPT:** not an “ageing-in-place digital twin”. It is a fastener problem.

---

#### 3. Humanitarian logistics × structural stress  
**Airdropped RUTF cartons that burst**

Plumpy’nut / biscuit cartons split on impact. Food is eaten by animals or looted as mush. Packing specs come from warehouse stacking, not 5 m dirt drops.

- **Allsolve:** Solid mechanics, transient impact, cardboard orthotropy + inner sachet as a pressure cavity.
- **Decision:** flute direction, corner crumple length, sachet fill fraction.
- **Metric:** sachet survival at 4–7 m onto 30° packed earth.
- **Weekend geo:** one RSC carton, 12 sachets, rigid ground.
- **Why it isn’t ChatGPT:** aid logistics usually becomes routing. This is a crashworthiness problem.

---

#### 4. Disaster aftermath × acoustics  
**The tap frequency that actually reaches a void**

After quakes, rescuers shout and drill. Victim tapping is real; the rubble is a filter. Most “listen” gear is tuned to air, not to concrete–rebar–void paths.

- **Allsolve:** Acoustic waves + acoustic–structure + solid, harmonic sweep 20–400 Hz through a rubble unit cell.
- **Decision:** which tap frequency and which listening point on the pile.
- **Metric:** transmission into a 0.5 m void vs drill-noise masker.
- **Weekend geo:** three concrete chunks + one rebar cage + one air void.
- **Why it isn’t ChatGPT:** not a drone swarm. A frequency.

---

#### 5. Childcare × solid mechanics  
**Baby-sling geometry that wrecks infant hips**

Narrow-base carriers hold the femur in adduction. Hip dysplasia is a geometry + fabric-tension problem, not a parenting one. Cheap slings sold online are the worst.

- **Allsolve:** Solid mechanics + contact, static. Soft fabric (low-E membrane) vs infant pelvis analog.
- **Decision:** seat width, thigh-strap angle, fabric modulus.
- **Metric:** hip abduction in the International Hip Dysplasia Institute “M” range.
- **Weekend geo:** pelvis + two femurs + one sling panel.
- **Why it isn’t ChatGPT:** childcare sims default to “room air quality”. This is a product that already exists and is injuring babies.

---

#### 6. Public toilets × acoustics  
**Stall speech that everyone can hear**

People with ostomies, IBS, catheter bags, or periods skip toilets because the 150 mm gap + tile cavity is an acoustic horn. That is a dignity and public-health failure (toilets avoided → UTIs, missed meds).

- **Allsolve:** Acoustic–structure, eigenmode then harmonic speech band 200–3 kHz.
- **Decision:** gap height, partition surface density, a 20 mm brush strip vs a full door.
- **Metric:** articulation index in the adjacent stall.
- **Weekend geo:** two stalls, one shared partition, tiled box.
- **Why it isn’t ChatGPT:** toilets as HVAC. This is privacy as a wave problem.

---

#### 7. Prisons × acoustics  
**The 80 Hz cell-block boom**

Wing corridors with hard surfaces lock onto a low mode. Sleep loss here is not “noise”; it is a structural acoustic resonance. Foam that can be weaponized will be banned, so the geometry has to be the treatment.

- **Allsolve:** Acoustic waves + ASI, eigenmode of a cell + corridor slice.
- **Decision:** bed-slab perforation, a hanging steel panel tuned as a membrane absorber, vs a soffit splitter that cannot hide contraband.
- **Metric:** kill the 60–100 Hz mode without creating a cavity >80 mm.
- **Weekend geo:** one cell, open door, corridor half-width, periodic BC.
- **Why it isn’t ChatGPT:** prison ideas usually go CCTV or heat. This is sleep as eigenmodes.

---

#### 8. Refugee camps × FSI / pressure  
**Bladder tanks that rip on lumpy ground**

Flexible water bladders are laid on ungraded earth. A 200 mm hump plus slosh at fill-up peels the RF-weld. A camp loses a week of water in one seam.

- **Allsolve:** Laminar flow + mesh deformation / FSI, transient fill.
- **Decision:** ground-beam spacing, fill rate, pillow vs sausage planform.
- **Metric:** peak seam peel stress vs weld rating during the last 10% of fill.
- **Weekend geo:** 10 m³ bladder, two ground humps, one weld line.
- **Why it isn’t ChatGPT:** not “camp digital twin”. One seam.

---

#### 9. Agriculture × EM waves + heat  
**RF that cooks weevils, not wheat**

Dielectric heating hits insects harder than dry grain because of water content. The failure mode is hot spots near metal silo walls and under-heating in the core — after which you have toasted grain and live weevils.

- **Allsolve:** EM waves + heat solid, harmonic then thermal transient. Grain as lossy dielectric; insect as a small high-loss inclusion.
- **Decision:** frequency (27 vs 915 MHz), electrode geometry, wall standoff.
- **Metric:** insect T > 55 °C while bulk grain T < 45 °C.
- **Weekend geo:** 1 m³ grain cell, one weevil cluster, one steel wall.
- **Why it isn’t ChatGPT:** agri-sim is irrigation. This is a pesticide-free physics trick Allsolve is actually good at.

---

#### 10. Remote communities × current flow  
**Stray voltage on the clinic floor**

A diesel genset with a bad earth, a wet concrete slab, and a steel delivery table. Midwives and neonatal gear share a current path. This is not “energy access”. It is a shock and device-reset problem in the one building that cannot go down.

- **Allsolve:** Current flow, static/DC and 50/60 Hz harmonic. Wet concrete conductivity, human-foot contact patches, table legs.
- **Decision:** equipotential bonding bar vs isolated table feet vs floor-drain as the real earth.
- **Metric:** touch voltage and current through a 1 kΩ body model; incubator supply integrity.
- **Weekend geo:** 6×4 m slab, genset earth rod, table, drain.
- **Why it isn’t ChatGPT:** remote-community ideas become solar. The genset is already there and is electrocuting people.

---

#### 11. Homelessness × acoustics  
**The underpass that will not let you sleep**

People sleeping in underpasses are not kept awake by dB(A). They are kept awake by 40–80 Hz boom from the deck above. Cheap foam is stolen and does nothing at those wavelengths.

- **Allsolve:** Acoustic–structure, harmonic. Concrete deck + cavity + hanging membrane.
- **Decision:** mass-loaded vinyl area density, air gap, attachment points that look like nothing worth stealing (paint-on or buried).
- **Metric:** 40–80 Hz SPL at ear height on a bedroll, vs untreated.
- **Weekend geo:** 8 m underpass bay, one deck span, one membrane.
- **Why it isn’t ChatGPT:** homelessness+physics defaults to hypothermia tents (you banned that). This is sleep.

---

### 12. Animal welfare × laminar flow  
**Live-fish tanks with anoxic corners**

Ornamental and food fish die in last-mile vans not from “stress” in the abstract but from a recirculation pattern that leaves a dead corner. High-Re CFD is the usual mistake; these tanks are slow and laminar.

- **Allsolve:** Laminar flow + heat fluid if you want oxygen-as-scalar via a custom weak form, transient.
- **Decision:** inlet/outlet placement, one baffle, stocking density as occupancy volume.
- **Metric:** fraction of tank below a velocity threshold where water is not exchanged in 5 minutes.
- **Weekend geo:** 80 L crate, one pump loop, one baffle variant.
- **Why it isn’t ChatGPT:** animal welfare sims become barn HVAC. A crate is a closed laminar problem Allsolve can finish overnight.

---

#### 13. Food storage × acoustics  
**Ultrasonic rat-repellers with silent apartments**

Community grain rooms and soup-kitchen stores buy plug-in 20–40 kHz gadgets. Standing waves leave quiet pockets. Rats nest there. The device is not fake; the room is a resonator.

- **Allsolve:** Acoustic waves, harmonic at the device frequency. Hard walls, sacks as absorbers.
- **Decision:** one source vs two, height, sack layout as the actual absorber.
- **Metric:** volume fraction below the aversive threshold.
- **Weekend geo:** 4×3×2.5 m store, pallet of sacks, one disk transducer.
- **Why it isn’t ChatGPT:** food storage becomes cold-chain. Rats plus eigenmodes is not in the starter pack.

---

#### 14. Menstruation × laminar FSI  
**Why the cup leaks when you sit**

Leak is usually blamed on “user error”. Sitting shortens the canal and peels a circular rim. Rim cross-section and silicone durometer are design variables. This is a product used by ~100 million people with almost no published FSI.

- **Allsolve:** Laminar flow of a viscous analog + FSI / mesh deformation of the rim, quasi-static sit.
- **Decision:** rim tube diameter, 40A vs 60A, stem as a peel-stop.
- **Metric:** seal contact pressure remaining after 25 mm canal shortening.
- **Weekend geo:** axisymmetric canal + cup, then one 3D sit.
- **Why it isn’t ChatGPT:** hygiene ideas become “pad supply chain”. Nobody else will put a menstrual cup in a FEM solver at a physics hackathon.

---

#### 15. Public transport × magnetics  
**Pacemakers on the tram platform**

Regenerative braking and third-rail / overhead inverters put low-frequency B-fields on the platform edge, exactly where someone with an ICD stands. ISO 14117 has limits. Operators do not have a map.

- **Allsolve:** Magnetism A or H, harmonic at inverter ripple and 50 Hz. Simplified bogie + rails + platform slab + a device-sized pickup loop at 1.3 m.
- **Decision:** waiting-line setback, shielding in the platform coping, inverter slew.
- **Metric:** peak dB/dt and B at implant height vs ISO 14117.
- **Weekend geo:** 10 m of rail, one bogie, platform edge.
- **Why it isn’t ChatGPT:** transport ideas become traffic flow (banned) or HVAC. This is a magnetics problem, which is Allsolve’s home turf.

---

#### 16. Construction workers × acoustic–structure  
**Formwork that is a loudspeaker**

Plywood wall forms on a high-rise are exponential horns for circular saws and grinders. The crew on the deck wears PPE. The crew *inside* the form, tying rebar, does not, and they go deaf in a season.

- **Allsolve:** ASI + acoustic waves, harmonic at saw-blade frequencies (2–6 kHz) and a 100 Hz structure-borne path.
- **Decision:** a 15 mm slit, a cross-brace, or a polymer sheet that breaks the cavity.
- **Metric:** SPL at the rebar-tyer’s head vs on the deck.
- **Weekend geo:** 2.4×1.2 m plywood panel, 200 mm cavity, one saw point load.
- **Why it isn’t ChatGPT:** construction+sim is PPE dashboards. The formwork is the instrument.

---

#### 17. Festivals / crowds × structural stress  
**Portable toilets that tip when people queue on the base**

Three people stand on the plastic skid waiting, one person is inside. The tank is half-full, the ground is wet, the unit rotates about the fill-side edge. This is a real ED-visit generator. It is also one rigid-body-plus-flex body statics problem.

- **Allsolve:** Solid mechanics, static then a slow transient as the fourth person shifts. Hydrostatic pressure on tank walls as a load.
- **Decision:** skid width, fill level at which you must pump, a 5 kg ground spike, max queue markings.
- **Metric:** restoring moment vs tip moment; door-jam if it rocks 8°.
- **Weekend geo:** one polyethylene cabin, tank, four point masses.
- **Why it isn’t ChatGPT:** festival sim is crowd flow or speaker aiming. This is the object people actually fall off.

---

#### 18. Emergency medicine × contact / pressure  
**Vacuum mattresses that cause the pressure sore during the rescue**

A 4-hour extrication on a scoop or vacuum mattress produces heel and sacrum sores before the patient reaches a ward. The mattress is designed for spinal immobilisation, not contact pressure.

- **Allsolve:** Solid mechanics + contact, static. Body with soft-tissue layers vs bead-mattress as a crushable continuum.
- **Decision:** bead size / fill fraction, heel cut-out, pump-down pressure.
- **Metric:** peak interface pressure at heel and sacrum vs 32 mmHg capillary threshold.
- **Weekend geo:** pelvis + heels + mattress slab, two vacuum levels.
- **Why it isn’t ChatGPT:** emergency-med sim is ambulance routing. This is a bedsore created by the rescue device.

---

#### 19. Schools × structural stress  
**Crash bars that jam when children pile on the door**

Fire-drill and real-panic loads put ~5 kPa on a gym exit. Some panic hardware cams bind under in-plane racking, so the door that should open inward-pressure / outward-swing doesn’t. This has already killed people in nightclubs; schools copy the same hardware.

- **Allsolve:** Solid mechanics + contact, static then short transient. Door leaf, two hinges, crash-bar mechanism as a few solids.
- **Decision:** bar height, latch cam angle, a second unlatching roller, leaf stiffness.
- **Metric:** unlatch still works at 5 kPa uniform crowd pressure plus 2 kN at the handle.
- **Weekend geo:** one leaf, frame, bar, latch.
- **Why it isn’t ChatGPT:** school sim is classroom HVAC or “learning analytics”. The exit is the humanitarian object.

---

#### 20. Developing-world infrastructure × vibration / elastic waves  
**The India Mark II handpump that dies from a crooked borehole**

A slightly doglegged borehole puts a lateral cycle on the GI rising main every stroke. The leather cup and the pipe joint fail weeks later. The village loses water. Maintainers replace the cup, not the alignment, so it fails again.

- **Allsolve:** Solid mechanics + elastic waves or transient, one pump stroke as a periodic load. Rod + rising main + a 2–3° dogleg.
- **Decision:** centraliser spacing, rod diameter, max allowable dogleg before you abandon the hole.
- **Metric:** alternating stress at the lowest joint vs fatigue of galvanised pipe; lateral displacement of the cup.
- **Weekend geo:** 20 m of pipe, one dogleg, one stroke.
- **Why it isn’t ChatGPT:** developing-world infrastructure becomes water purification (banned) or solar (banned). This is a fatigue problem in the most common village machine on earth.

---

### If you can only pitch three

| Pick | Why it wins a short Allsolve hackathon |
|---|---|
| **#1 hearing loop vs rebar** | Native magnetics, small mesh, IEC number, disabled users as the human stake |
| **#14 menstrual cup sit-peel** | Tiny FSI, visually obvious, nobody else in the room will do it |
| **#9 RF weevils in grain** | Coupled EM + heat, Allsolve’s actual product strength, pesticide-free “useful for humanity” story |

**Do not do** anything that needs turbulence, agent-based crowds, a city-scale mesh, or an LLM sitting on top of a solver. Judges have seen those. Pick one geometry, one coupling, one number a real person would change on Monday.

## Claude
I'll start by reading the Allsolve documentation so the ideas stay inside what it actually supports.

Now the SDK and physics/coupling details.

I read the Allsolve docs: physics pages, the simulation types, and the SDK intro and examples. Your prompt cuts off partway through "4. SDK USE", so I covered fields 1–4 and added three more I think you'd want: why it needs a solver, a hackathon-sized scope, and the documentation risks.

### Limits that shaped these ideas

- **Heat solid** offers fixed temperature, heat source, convection (h·(T−T∞)), periodicity and Lump T/Φ. **No radiation boundary condition is documented.**
- **Laminar flow** is incompressible Navier–Stokes. **No buoyancy or natural convection and no turbulence are documented.** So "air circulating in a room" is out; forced, low-Reynolds flow in tubes and channels is in.
- **Couplings that are documented:** Joule heating (Current flow or Magnetism H → Heat solid), Thermal fluid (Laminar ↔ Heat fluid), conjugate heat transfer, Thermal expansion, Fluid–structure interaction, Acoustic–structure, Piezoelectricity, and Electric force.
- **Analysis types:** static, harmonic, multiharmonic, transient and eigenmode. Acoustic and EM waves have no static mode.
- **The SDK can:** create projects, build or import geometry, assign materials, physics and boundary conditions, set meshing, run simulations, monitor jobs and retrieve results. Its examples include geometry and frequency Cartesian sweeps, a scipy optimization loop (in the legacy script-based examples), a surrogate-model workflow and compute reservation for repeated jobs.

---

### 1. Cable reel fire risk ⭐ (my top pick)

**1. Human problem.** People run space heaters, kettles or EV trickle chargers through extension reels that are still partly wound. The inner turns trap heat and the insulation can melt, which is a known cause of house fires. Reel labels give one rating for "wound" and one for "unwound", with nothing in between.

**2. Surprising question.** *"How many amps can I safely pull through this reel if I've only unrolled half of it?"*

**3. Allsolve physics.** Current flow plus Heat solid, joined by the **Joule heating** coupling. Convection boundary conditions model the outer surfaces. Use static analysis for steady state and transient analysis for time to failure. A 2D cross-section of the wound turns (copper, PVC, air gaps, drum) is enough.

**4. SDK use.** Generate the geometry programmatically for N wound layers and turns. Sweep current, number of wound turns, ambient temperature and h. Retrieve the maximum insulation temperature from each run. Then bisect on current to find the largest current that keeps PVC under its rated temperature for each unrolled fraction.

**5. Why a solver.** Heat has to pass through many alternating layers of copper, PVC and air with heat generated inside every turn. The hot spot is buried in the middle, and a hand calculation can't estimate it reliably.

**6. Hackathon scope.** Build a 2D axisymmetric-style cross-section and run about 30–60 simulations. The demo is a "safe-amps vs. % unrolled" curve plus an app: enter your appliance's wattage and see how much cable to unroll.

**7. Risks.** Air gaps are treated as solid conductors, which is a conservative assumption because there is no natural convection. Contact resistances are estimated.

### 2. Cold IV fluids in the field

**1. Human problem.** Room-temperature or cold IV fluids make hypothermia worse in trauma patients. Medics in the field or in low-resource clinics often warm the line by wrapping it around a heat pack or their own body, with no idea whether it works.

**2. Surprising question.** *"How many turns of IV tubing around a 40 °C pack does it take to deliver fluid near body temperature at trauma flow rates?"*

**3. Allsolve physics.** Laminar flow, Heat fluid and Heat solid, set up as **conjugate heat transfer** with the **Thermal fluid** coupling. This matches the documented microchannel heat sink workflow, and IV flow really is laminar. The pack can be a fixed temperature, a Lump T/Φ, or a Heat source.

**4. SDK use.** Sweep flow rate, tube length in contact, pack temperature and starting fluid temperature. Retrieve the outlet temperature from each run. Use an optimization loop to find the minimum wrap length for each flow rate.

**5. Why a solver.** The fluid's temperature develops along the tube, the wall conducts heat, and the residence time depends on flow rate. These interact in a way a rule of thumb can't capture.

**6. Hackathon scope.** Model a single straight tube segment, which is cheap, and scale up to the coiled length. The demo is a field card: "flow rate X → wrap Y cm".

**7. Risks.** The pack is idealized as a constant temperature unless you model its transient cooling. The result is advisory, not medical guidance.

### 3. The bouncy DIY loft bed or footbridge

**1. Human problem.** DIY loft beds, decks and small community footbridges often feel "bouncy". Walking (about 1.6–2.4 Hz) can excite resonance, which is uncomfortable and sometimes dangerous.

**2. Surprising question.** *"Will my kid's loft bed sway when they climb in, and which single extra brace fixes it?"*

**3. Allsolve physics.** Solid mechanics: **eigenmode** analysis for natural frequencies, then **harmonic** or **transient** analysis with a time-varying footstep load from the documented load expressions.

**4. SDK use.** Generate the frame geometry from user dimensions. Try each candidate brace location automatically as a geometry variant. Swap timber grades and section sizes. Rank the fixes by how far the first mode moves out of the walking band.

**5. Why a solver.** The mode shapes of a real frame with joints, posts and a mattress mass aren't intuitive. A brace in the "obvious" spot often does nothing.

**6. Hackathon scope.** Build a parametric box-frame generator and run about 20 eigenmode runs. The demo is an animated mode shape plus a ranked list of fixes.

**7. Risks.** Joint stiffness is idealized as fully rigid. Present the output as comparative ranking, not certification.

### 4. Quietest corner for the crib

**1. Human problem.** Low-frequency hum (a neighbour's subwoofer, a heat pump, traffic) collects in specific spots in a room because of room modes. Parents move the crib around by trial and error.

**2. Surprising question.** *"Where in this bedroom is the 50 Hz hum quietest, and where should a single absorber panel go?"*

**3. Allsolve physics.** Acoustic waves: **eigenmode** analysis for room modes and **harmonic** analysis at the hum frequency. A Normal acceleration boundary on the noisy wall acts as the source, and an **Acoustic damping** region represents the absorber panel.

**4. SDK use.** Build room geometry from user dimensions. Sweep frequency over the noise band and the absorber's position and size. Retrieve the pressure field and evaluate it at crib-height grid points. Optimize absorber placement to minimize sound level at the chosen crib spot.

**5. Why a solver.** In real L-shaped rooms with furniture, the pressure nodes and antinodes can't be guessed. One meter can mean a 10+ dB difference.

**6. Hackathon scope.** Start with a 2D floor plan and move to 3D if time allows. The demo is a heatmap "quiet zone" overlaid on the floor plan.

**7. Risks.** Walls are rigid by default. Absorption values for the damping region have to be estimated.

### 5. Insulin in a hot car

**1. Human problem.** Insulin degrades above about 30 °C. People with diabetes travelling or living through heatwaves rely on pouches with unclear real-world performance.

**2. Surprising question.** *"What's the cheapest pouch, made from materials I already own, that keeps insulin under 25 °C for 8 hours in a 45 °C car?"*

**3. Allsolve physics.** Heat solid, **transient**, with convection boundary conditions to hot car air and optionally a cold-pack region with its own heat capacity.

**4. SDK use.** Sweep layer materials (foam, wool, towel, aluminium foil as a conduction layer), thicknesses and cold-pack size. Retrieve the vial temperature over time. Optimize for minimum thickness or cost subject to a time-above-limit constraint.

**5. Why a solver.** It is a layered 3D transient problem with corners, zipper gaps and a finite cold reservoir. Simple 1D estimates usually overrate the pouch.

**6. Hackathon scope.** Use a box-in-box geometry and about 50 transient runs. The demo is a "time until unsafe" leaderboard for household material combinations.

**7. Risks.** The docs show **no radiation boundary condition**, so direct sun has to be approximated as a surface heat source. A melting cold pack (phase change) isn't documented, so treat it as a high-heat-capacity solid.

### 6. Wi-Fi dead zone in a child's study room

**1. Human problem.** Kids doing homework in back bedrooms lose signal. People buy mesh extenders without knowing where the router should go.

**2. Surprising question.** *"Where do I put the router so the study desk gets signal, without buying anything?"*

**3. Allsolve physics.** Electromagnetic waves, **harmonic** at 2.4 GHz and 5 GHz, on a 2D floor plan. Walls are given permittivity and conductivity values, with a PML or absorbing boundary at the outer edge.

**4. SDK use.** Sweep candidate router positions (each one moves the source in the geometry or region), repeat at both bands, retrieve field magnitude at the desk, and rank the positions.

**5. Why a solver.** Interference and multipath through walls produce dead spots that don't follow distance.

**6. Hackathon scope.** A 2D floor plan of about 10 m is electrically large but feasible. Use the iterative DDM solver.

**7. Risks.** This one has the highest compute cost. Wall material properties are estimates, and 2D ignores the vertical dimension.

---

#### Recommendation

For a short hackathon I'd pick **#1 (cable reel)** or **#2 (IV warming)**. Both use multiphysics couplings the docs explicitly describe, are cheap to mesh, give one clear answer from a sweep, and tell a strong safety story. **#3** is the safest fallback because eigenmode plus geometry sweeps is the best-trodden path in the SDK examples. I'd avoid anything that depends on room air convection or sunlight, since neither is documented.

Sources:
- [Allsolve docs](https://allsolve.quanscient.com/documentation/start-here/introduction)
- [SDK introduction](https://allsolve.quanscient.com/documentation/reference/public-api-introduction)
- [Working with physics](https://allsolve.quanscient.com/documentation/using-allsolve/physics/working-with-physics)
- [Simulations overview](https://allsolve.quanscient.com/documentation/using-allsolve/simulations/overview)
- [Heat solid](https://allsolve.quanscient.com/documentation/using-allsolve/physics/heat-solid)
- [Heat fluid](https://allsolve.quanscient.com/documentation/using-allsolve/physics/heat-fluid)
- [Laminar flow](https://allsolve.quanscient.com/documentation/using-allsolve/physics/laminar-flow)
- [Acoustic waves](https://allsolve.quanscient.com/documentation/using-allsolve/physics/acoustic-waves)
- [SDK examples](https://github.com/Quanscient-Public/allsolve-sdk-python/blob/main/examples/README.md)

## Deepseek
I sampled unusual human contexts and forced each idea to hinge on a specific coupled-physics bottleneck—not an “AI wrapper,” not a generic digital twin, not the usual hackathon themes. Each can be scoped down to a reduced-order simulation in a short hackathon.

Prisons — Acoustic refuge for neurodivergent prisoners
Simulate sound propagation and absorption in concrete cell blocks to design cheap retrofit panels that reduce sensory overload and self-harm triggers.
Allsolve: acoustic FEA + porous-media absorption + structural vibration.
MVP: 2D acoustic cavity model of one cell tier; compare bare concrete vs mattress/foam retrofit.

Public toilets — Ostomy/incontinence splash guard
Model flush-jet droplets and surface contamination in public toilets to design a clip-on shield for people emptying ostomy bags or changing incontinence products.
Allsolve: CFD + discrete droplet phase + surface tension.
MVP: 2D axisymmetric flush model; show droplet spread with/without guard.

Menstruation — Reusable pad leakage under walking motion
Simulate blood-analogue flow through layered fabric under cyclic body compression, then redesign layer order/stitching for low-resource and homeless users.
Allsolve: poroelasticity + multiphase Darcy flow + contact mechanics.
MVP: 1D layered porous model with cyclic pressure; compare leakage volume.

Ageing — Arthritic blister-pack opening
Simulate peel and rupture forces for stiff polymer blister packs using reduced grip strength and hand tremor, then redesign the seal for safer self-dosing.
Allsolve: nonlinear structural + viscoelastic + contact.
MVP: peel-test FEA of one blister cavity; map force vs grip angle.

Disability — Wheelchair cushion pressure-ulcer microclimate
Couple pressure, shear, moisture, and heat in a low-cost 3D-printed lattice cushion to reduce pressure ulcers in wheelchair users.
Allsolve: poroelastic contact + heat/moisture transport + CFD.
MVP: unit-cell lattice simulation; show peak pressure and humidity vs cell geometry.

Humanitarian logistics — Vaccine cold chain on motorbike panniers
Simulate vibration and transient heat ingress in a vaccine carrier strapped to a motorbike, then design a cheaper insulation/packing layout.
Allsolve: structural dynamics + transient thermal + CFD.
MVP: 2D thermal model with measured vibration spectrum; predict vial temperature excursion.

Disaster aftermath — Tent CO poisoning from cooking
Model carbon monoxide transport inside emergency tents with wind, occupant heat, and vent flaps, then derive a simple “open this flap” rule.
Allsolve: CFD + species transport + buoyancy.
MVP: 2D tent cross-section; CO concentration vs vent opening and wind speed.

Childcare — Safe baby-bottle warming in low-resource clinics
Simulate natural convection and conduction in thermos/water-bath warmers to avoid hotspots and scalding, and to hit safe milk temperature reliably.
Allsolve: CFD + conjugate heat transfer.
MVP: 2D axisymmetric bottle-in-water model; time-to-temperature and hotspot map.

Food storage — Hermetic grain bag condensation
Model day-night temperature swings, moisture migration, and CO2 in stacked hermetic grain bags to prevent mold without opening them.
Allsolve: porous-media heat/moisture + species transport.
MVP: 1D bag-stack model; predict condensation risk vs bag material and stack height.

Animal welfare — Day-old chick transport box ventilation
Simulate airflow, heat, humidity, and CO2 in stacked chick boxes during transport, then redesign vent holes to cut mortality.
Allsolve: CFD + heat/moisture + species transport.
MVP: 2D box-stack model; compare vent patterns.

Homelessness — Sleeping-bag microclimate in wet cold
Couple heat and moisture through layered sleeping-bag fabrics with wind and rain to design a low-cost vapor barrier that stays warm when damp.
Allsolve: CFD + heat/moisture transport through porous layers.
MVP: 1D multi-layer model; core temperature drop vs wind/rain.

Remote communities — Hand-powered dental drill vibration
Simulate vibration transmission from a human-powered dental drill to patient and clinician, then add passive damping to reduce pain and hand injury.
Allsolve: structural dynamics + contact + damping.
MVP: 1D/2D modal model; vibration at patient end vs damper material.

Prisons — TB aerosol spread in cell blocks
Model passive ventilation and aerosol transport between cells to redesign grilles and door gaps, reducing TB transmission without powered HVAC.
Allsolve: CFD + particle tracing + buoyancy.
MVP: 2D cell-block slice; aerosol exchange rate vs grille placement.

Refugee camps — Latrine siting to protect shallow groundwater
Simulate groundwater flow and solute transport from pit latrines to find safe distances from hand-dug wells in sandy/rocky camps.
Allsolve: Darcy flow + advection-dispersion.
MVP: 2D cross-section; contamination arrival time vs latrine distance.

Menstruation — Menstrual cup fit and leakage
Simulate pelvic anatomy, cup rim stiffness, and fluid-structure interaction to design cup shapes that seal without pain for different body types.
Allsolve: FSI + contact + nonlinear elastic.
MVP: axisymmetric cup-vaginal wall model; seal pressure vs rim geometry.

Ageing — Hip-protector underwear impact
Simulate fall impact through foam pads in ordinary underwear to design a cheap hip protector that older adults will actually wear.
Allsolve: structural dynamics + contact + foam crush.
MVP: 2D fall impact; peak femoral neck stress vs foam shape.

Public toilets — Hand-dryer aerosol in wheelchair-accessible stalls
Model airflow and droplet spread from hand dryers in accessible stalls, then recommend placement/type that reduces infection risk for wheelchair users.
Allsolve: CFD + discrete droplet phase.
MVP: 2D stall model; droplet count on wheelchair surfaces vs dryer position.

Disability — Tactile paving detection by white cane
Simulate cane-tip dynamics on truncated domes under wet/dry conditions to improve tactile paving geometry for blind pedestrians.
Allsolve: structural dynamics + contact + thin fluid film.
MVP: 2D cane-tip/ dome model; tactile signal vs dome height and wetness.

Childcare — Skin-to-skin warming bag for preterm transport
Simulate infant thermoregulation with phase-change material in a low-cost transport bag during power outages or rural referral.
Allsolve: bioheat + phase-change heat transfer.
MVP: 1D infant/PCM model; core temperature stability over 4 hours.

Animal welfare — Urban beehive overheating
Model hive thermal regulation and ventilation under urban heat and direct sun, then design shade/vent add-ons that reduce colony collapse.
Allsolve: CFD + heat transfer + species/humidity.
MVP: 2D hive cross-section; internal temperature vs shade and vent area.

Short-hackathon advice: pick one idea, simulate one reduced case, show a sensitivity curve, and end with a design rule. That is more convincing than trying to model the whole system.


-------
### The main prompt that I used:

You are helping me brainstorm a project for a short hackathon.

The project MUST substantially use Quanscient Allsolve and its Python SDK:
https://allsolve.quanscient.com/documentation/

FIRST, study the documentation before generating ideas.

Treat the documentation as a hard technical boundary.

Only propose ideas that can realistically be implemented using capabilities currently documented by Allsolve, such as:

- Heat transfer in solids
- Heat transfer in fluids
- Laminar fluid flow
- Solid mechanics
- Elastic waves
- Acoustic waves
- Current flow
- Electrostatics
- Electromagnetic waves
- Magnetism
- Multiphysics couplings supported by Allsolve
- Parameterized geometry
- Materials and boundary conditions
- Static, transient, harmonic, eigenmode or other documented simulation modes
- Allsolve Python SDK automation
- Programmatic parameter sweeps
- Programmatic simulation execution
- Programmatic result retrieval
- Optimization loops built around repeated Allsolve simulations

Do NOT invent physics or SDK capabilities that are not documented.

The mission is NOT merely to make an application that happens to call Allsolve. The core value of the project should come from a physical simulation that would be difficult to answer reliably without a physics solver.

For each proposed project explicitly state:

1. HUMAN PROBLEM
What real human problem does this solve?

2. SURPRISING QUESTION
Phrase the project as one interesting question such as:
"Where should this person sleep during a blackout?"
rather than:
"Building thermal simulation."

3. ALLSOLVE PHYSICS
Name the exact documented Allsolve physics required.

4. SDK USE
Explain exactly why the Allsolve Python SDK is useful.
For example:
- alter geometry automatically
- change material properties
- vary boundary conditions
- launch