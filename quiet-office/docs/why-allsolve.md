# Why Allsolve and its SDK for this problem

The question a judge, a teammate or a customer will ask: *you want to know where to put three
acoustic screens — why does that need a cloud FEM solver with a Python SDK, and why this one?*

Short answer: the problem has two properties that pull in different directions. The physics
needs a **wave solver**, and the decision needs **dozens to hundreds of solves on changing
geometry**. Tools that are good at one are usually awkward at the other. Allsolve with the SDK
covers both from one Python process.

## 1. The physics is wave physics, and simpler methods are weakest exactly here

Speech carries most of its energy and intelligibility between about 250 Hz and 2 kHz. In air
that is:

| Frequency | Wavelength |
|----------:|-----------:|
| 250 Hz | 1.37 m |
| 500 Hz | 0.69 m |
| 1 kHz | 0.34 m |
| 2 kHz | 0.17 m |

An acoustic screen is 1.2 to 2.6 m wide. A desk is 1.6 m. The gap between a screen and a
wall is a metre or two. **Everything in an office is about one wavelength in size.** In that
regime sound does not travel in straight lines and cast sharp shadows. It bends around the
ends of a screen, the bent waves from two ends interfere, and the result depends on the exact
position of the screen relative to the talker and each desk.

That is what makes "where should the screen go?" a real question, and it is where the usual
shortcuts break down:

- **Rules of thumb** ("put it close to the source") give a direction, not a position, and
  cannot say what the second and third screen are worth.
- **Barrier formulas** (Maekawa-type insertion loss) treat one screen, one source and one
  receiver in open space. Our own quick estimate in the browser is built on such a formula.
  It is useful as a preview and it is exactly the thing we do not trust for the decision.
- **Ray tracing / geometric acoustics**, the standard for room acoustics, assumes wavelengths
  much smaller than the objects. It is the right tool for a concert hall at 2 kHz and the
  wrong one for diffraction around a 1.8 m screen at 250 Hz.

A finite-element solve of the Helmholtz equation has none of these assumptions. Diffraction,
interference and the effect of the room come out of the equation, not out of a correction
factor. Allsolve's **Acoustic waves** physics with **harmonic** analysis is that solver: one
solve per frequency gives the pressure everywhere in the room.

## 2. The answer is a search, so the solver has to be driven by code

One simulation answers "how loud is it at the desks with the screens *here*?". The user's
question is "where is *here*?". For three screens and twelve allowed positions that is 220
layouts, or 34 if we place one screen at a time, each at several frequencies. Nobody clicks
through that in a GUI. What the SDK gives us, concretely:

- **Geometry as variables.** Screen positions are project variables
  (`s0_x`, `s0_y`, ...). One project describes every layout; see
  [`project_builder.py`](../backend/app/allsolve/project_builder.py).
- **Parallel by construction.** Every step of a sweep runs on its own cloud machine, up to
  100 at the same time, so a round of layouts takes about as long as one layout. With several
  noise sources each layout needs one solve per source and band, so this is where the wall
  time goes, and where local software on one workstation would queue. What takes time is
  booting the machines, not solving: see the measurements in
  [`machines.py`](../backend/app/allsolve/machines.py). The fast search boots them once with a
  resource reservation, or uses machines started beforehand.
- **Many layouts per machine.** In the fast search a sweep step is not one solve. A custom
  solver script ([`batch_script.py`](../backend/app/allsolve/batch_script.py)) makes each of
  the 100 machines solve its share of the layouts one after another on the mesh it has
  already loaded, and return all pressures as one list. Measured: 300 layouts (600 solves) in
  29 s, and 500 in 23 s when the room was searched before and its mesh is used again.
- **Sweeps as one cloud job.** `create_variable_overrides` plus one mesh and one harmonic
  simulation run a whole round of layouts and frequencies. Allsolve remeshes only when the
  geometry changes, so the frequencies of a layout share its mesh.
- **Results as numbers in Python.** Pressure at each desk comes back through
  `get_output_data()`, so scoring and picking the next round is ordinary Python; see
  [`optimization_runner.py`](../backend/app/allsolve/optimization_runner.py).
- **Everything else is just Python.** The same process is a FastAPI backend for the web UI.
  Swapping the greedy search for scipy, a surrogate model or anything else needs no change to
  the simulation side.

The value of the project is in this loop, not in a single run. Without scripted access to
geometry, meshing, solving and results there is no product.

## 3. The compute is somewhere else

Wave problems get expensive fast: the mesh needs about six elements per wavelength, so the
element count grows with the square of frequency in 2D and the cube in 3D. Our 16 x 10 m
office in 2D is some tens of thousands of elements at 500 Hz and several hundred thousand at
2 kHz, and each layout is solved again for each frequency.

With Allsolve the laptop only orchestrates. There is no solver to install, no licence server
and no workstation to buy, and the runs of a sweep do not queue behind each other on one
machine. For a hackathon this means a working pipeline in a day. For a real product it means
the backend can sit on a small server while the heavy work scales separately.

## 4. Room to grow without changing tools

The first model was deliberately small: 2D, sound-hard screens, absorbing walls. The 3D room
with panel heights and absorbing panels was then added as a second project builder, using the
same SDK calls with boxes in place of rectangles. Each further step is likewise a feature
Allsolve already documents, so it is an edit to the project builder, not a new toolchain:

| Next step | Allsolve feature |
|-----------|------------------|
| Screens that absorb as well as block | Acoustic damping regions, material attenuation |
| Reflecting or partly absorbing walls | Boundary choice per wall, damping regions for panels |
| Light screens that vibrate and leak sound | Acoustic-structure interaction |
| Why does this room boom at 80 Hz? | Eigenmode analysis |
| Ceiling height, sound going over the screen | 3D geometry with the iterative solver on several nodes |
| A real floor plan | STEP import into the same project |

## 5. Compared with the alternatives

| Approach | Good at | Why it is not our choice here |
|----------|---------|-------------------------------|
| Rules of thumb, ISO 3382-3 style metrics | Describing and rating an existing office | They measure a result; they do not predict a specific layout |
| Barrier formulas (our quick estimate) | Instant, runs in a browser | One screen in open space; no interference, no room |
| Ray-tracing room-acoustics software | Large rooms, high frequencies, reverberation | Weak at diffraction around wavelength-sized screens; desktop tools, not built to be called 200 times from a web backend |
| Desktop FEM packages | The same wave physics | Licence and workstation per user; the search loop means scripting a desktop application |
| Open-source FEM libraries | Free, fully scriptable | We would write the acoustics formulation, absorbing boundaries, meshing pipeline and cluster setup ourselves before the first result |
| **Allsolve + SDK** | Wave physics, scripted geometry sweeps, cloud compute, one Python API | See the limits below |

## 6. Where it is not the best choice

Being honest about this is part of the argument.

- **High frequencies in full 3D.** A whole 3D office at 2 kHz is over a hundred million
  elements. For that, geometric methods are the practical choice. FEM is for the low and
  middle bands where diffraction decides the outcome, which is where screens are hardest to
  place.
- **Certified numbers.** The result is a relative improvement inside a simplified model. It
  ranks layouts. It is not a measured dB reduction and not ISO compliance.
- **SDK documentation.** The room-acoustics boundary conditions are thinly documented; we had
  to read the SDK source to find their parameters. See [sdk-feedback.md](sdk-feedback.md).
- **Cost and latency.** Each search uses cloud compute and takes minutes, not milliseconds.
  That is why the UI shows a quick estimate first and replaces it with the simulation.

## 7. What is proven so far

The project setup, the sweep and the scoring are written against the real SDK
([backend](../backend/README.md)). Until the baseline run in
[`simulations/baseline`](../simulations/baseline/run_baseline.py) has been checked, every
number on screen comes from the quick estimate, and this document describes why the approach
is right, not results we have measured.

## One sentence for the pitch

> Sound in an office bends around screens because everything is one wavelength in size, so
> placing them is a wave problem; and finding the best place means solving it for hundreds of
> layouts, so it is a scripting problem. Allsolve's SDK is the one tool that does both.
