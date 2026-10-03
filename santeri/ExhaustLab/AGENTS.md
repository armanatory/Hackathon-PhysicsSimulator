# ExhaustLab case thread instructions

Own the combustion-exhaust particle-collection case in `F:\H4H quanscient\ExhaustLab`. Use its own local frontend/API ports, provisionally `127.0.0.1:5176` and `127.0.0.1:8003`. Keep the work separate from `MetaSense`, `RoomValue`, `beer_cooling_app`, and the three-teammate `Hackathon-PhysicsSimulator` repository. Do not edit or push the shared repository. Keep Allsolve credentials server-side; do not print keys.

## User goal

Explore exhaust systems for combustion sources, including cars, ships, and power plants, that collect particles and reduce particulate emissions. Seek a useful, affordable design decision supported by a real simulation. Choose one narrow initial device and operating envelope rather than claiming one model covers every source.

## Feasible first hypothesis to verify

Prototype a small **electrostatic particulate collector for a precharged, dilute aerosol in a low-flow exhaust side-stream**. Allsolve documents laminar velocity/pressure and electrostatic potential/field solves; its documented SDK supports field outputs. Particle tracing, soot charging/corona, porous filter flow, species transport, and combustion chemistry have not been verified as turnkey Allsolve workflows here.

1. Verify a real Allsolve geometry, mesh, laminar-flow solve, and electrostatic solve for one small 3D duct/collector layout. Check boundary conditions, velocity/pressure, potential/electric field, and exported fields against simple channel-flow and uniform-field cases.
2. Compare two or three plate/baffle layouts. If particle tracking is not available in Allsolve, integrate explicitly documented particle trajectories locally from the **Allsolve-computed fields** with stated particle diameter/charge, inlet distribution, drag assumptions, wall capture rule, and trajectory-convergence checks. Make clear which quantities came from Allsolve and which came from local postprocessing.
3. Show modeled single-pass capture conditional on those inputs and the simulated pressure penalty. Rank the layouts by capture, pressure drop, and an entered cost/power budget. Label the result as a modeled pilot collector, not measured or certified emission reduction for a car, ship, or plant.
4. Do not claim CO2/NOx reduction, raw soot charging efficiency, corona physics, filter regeneration, full hot/turbulent stack behavior, or regulatory compliance without corresponding physics and validation. If the proposed field workflow is blocked, narrow the app to quantities genuinely solved and record the SDK limitation.
5. Build a working local web app only after a verified solver path, and record concrete SDK usability feedback for judging.

Official references: [Allsolve laminar flow](https://allsolve.quanscient.com/documentation/using-allsolve/physics/laminar-flow), [electrostatics](https://allsolve.quanscient.com/documentation/using-allsolve/physics/v-formulation-electrostatics), [SDK](https://allsolve.quanscient.com/documentation/reference/allsolve-sdk), and [EPA electrostatic precipitator overview](https://www.epa.gov/air-emissions-monitoring-knowledge-base/monitoring-control-technique-electrostatic-precipitators).

## Authorized follow-up: constraint-driven diesel filter installation planner

The user requested a web app where editable system constraints drive an inverse search for an optimal exhaust installation. Prioritize a pipe-shaped DPF installation, filter sizing, housing geometry and insulation across an editable engine duty cycle. Preserve the electrostatic pilot as historical validation work.

Use engine mass flow and temperature histories as inputs; compute velocity from density and area, and constrain the predicted backpressure. Optimize a finite, explicit design space and report the best feasible candidate under a declared objective, alternative tradeoffs and binding constraints. If no candidate meets the constraints, report infeasibility and the reasons without inventing a winner. Cost, material and filter performance inputs must identify their source. Demonstration coefficients are editable and must remain clearly distinguished from measured calibration.

Verify a real Allsolve porous-flow/thermal path before labeling results as cloud-supported DPF predictions. An equivalent bulk porous cartridge is a reduced model, not resolved wall-flow filtration. Filter capture may use a supplied specification; do not imply that the pressure/thermal solve predicts capture. A temperature-retention screen is not a validated regeneration/soot-oxidation calculation. Compare clean and loaded resistance states. Record job IDs, hashes, physical checks and observed parallel-job overlap. Keep API keys server-side, costs bounded, and all work inside this case folder.
