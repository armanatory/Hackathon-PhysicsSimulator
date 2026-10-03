# Cylindrical exhaust-installation planner

The new planner is a bounded inverse-design **screening** tool. It enumerates user-entered cylindrical cartridge diameters and lengths, upstream pipe lengths, and insulation thicknesses. It reports the cheapest, smallest or lowest-backpressure feasible member of that finite grid, plus feasible Pareto tradeoffs. If none meets the constraints, `recommended` is null and the app reports violated constraints and near-feasible candidates.

It models a homogeneous axial porous cartridge installation. A conventional wall-flow DPF forces exhaust through ceramic walls between alternately plugged channels; this is different from the homogeneous axial model. The wall permeability of a real DPF must **not** be pasted into this planner as the effective axial permeability of the complete cartridge. Predictions become design evidence only when the chosen resistance law, thermal properties, capture specification and volume requirement have been calibrated for the actual cartridge family and geometry range. No measured engine cycle or supplier cartridge dataset was supplied; the defaults are deliberately labeled demonstration inputs.

## Inputs and constraints

The selected application is a small stationary diesel engine. The reference rated point is the [FG Wilson P22-1 supplier datasheet](https://www.fgwilson.jo/images/document/19867560/P22-1L_SKID_EN-XUZENrzO_pyIozFA7Ecs6g.pdf), which lists 16 kW prime electrical output, 445°C exhaust, 3.6 m³/min exhaust flow and 10.2 kPa maximum exhaust backpressure. The app uses 0.030 kg/s as a rounded inference from that volume flow treated as hot actual flow, using ideal dry-air density at 445°C and 101.325 kPa; the supplier does not publish this mass-flow value. Warm-up, partial-load and idle values and every duration are illustrative. The engine's pressure limit applies to the full exhaust system; the installation allowance must account for equipment outside the modeled cartridge, pipe and entered housing loss.

- Ordered duty-cycle points: duration in seconds, exhaust mass flow in kg/s and inlet gas temperature in °C. Temperatures are at the start of the modeled upstream pipe. The ordered history matters for the thermal node.
- Environment: absolute downstream pressure in kPa and ambient temperature in °C. Velocity and pressure drop are calculated rather than prescribed independently.
- User constraints: maximum loaded backpressure, installed outer diameter, total pipe-plus-cartridge length, entered build budget, required supplier-specified capture, maximum uniform-node filter temperature, and optional minimum time above an entered temperature threshold.
- Entered cartridge information: complete-cartridge effective axial permeability, capture specification, effective bulk density and heat capacity, loaded resistance multiplier, and minimum filter volume. The minimum volume is an engineering requirement, not calculated soot-storage capacity.
- Entered thermal information: external heat-transfer coefficient, insulation conductivity, gas heat capacity, gas-to-filter effectiveness and initial uniform filter temperature.
- Entered costs: fixed assembly cost plus filter-volume, insulation-volume, housing-area and pipe-length coefficients. These are not researched quotations.

The default grid is 120/160/200 mm cartridge diameter × 150/200/250 mm active length × 100/300/600 mm upstream pipe × 0/10/20 mm insulation, giving 81 installations. Only the nine diameter/length pairs have cloud cartridge solves; insulation and pipe placement are local installation calculations.

## Pressure and gas properties

The ideal dry-air approximation uses `rho = p_abs/(287.05 T_K)` and `Q = mass_flow/rho`. Dynamic viscosity varies with Kelvin temperature through Sutherland's law. The cartridge inlet temperature is first cooled through the pipe's cylindrical thermal resistance.

For frontal area `A`, cartridge length `L`, effective permeability `k` and gas viscosity `mu`, clean homogeneous pressure loss is:

`delta_p = pressure_factor * mu * L * Q/(A*k)`.

The entered loaded multiplier applies to the cartridge loss. Smooth/rough upstream pipe loss uses a local Churchill friction-factor correlation, and the entered housing loss coefficient multiplies the pipe dynamic pressure. These local correlations are not resolved by the cloud cartridge solve. Each duty point is screened for clean and loaded states; soot mass, ash mass and regeneration are not evolved.

Candidates with loaded loss greater than 10% of absolute downstream pressure or pipe Mach greater than 0.3 are excluded because the low-compressibility screening assumptions would be stretched. Input validation also enforces the explicit editable envelope recorded in `planner.normalize_inputs` rather than silently extrapolating gas properties to arbitrary engines.

## Local thermal history

Pipe gas cooling uses `T_out - T_ambient = (T_in - T_ambient) exp[-UA/(mass_flow*cp)]`. Insulation conduction and external convection are in series on the cylindrical lateral surface; end losses and radiation are omitted.

The filter has one uniform temperature and heat capacity `C = bulk_density * cp_filter * volume`. With entered gas-to-filter effectiveness `eta`, each constant duty step solves exactly:

`C*dT_filter/dt = eta*mass_flow*cp_gas*(T_pipe_out - T_filter) - UA_filter*(T_filter - T_ambient)`.

Mean temperature and the exact crossing time of the entered hot threshold are calculated for each step. The duty points run once, in order, from the entered initial temperature. This is a heat-retention and warm-up screen. It does not predict regeneration completion, oxidation rate, thermal gradients or peak temperatures caused by burning soot. The maximum-temperature constraint bounds only this uniform-node temperature.

Cloud thermal fields are a separate **steady plug-flow advection/diffusion benchmark**. Their exported steady outlet temperature and numerical validation are exposed as evidence. The steady cloud thermal factor is not multiplied into the unrelated transient lumped-node response.

## Allsolve provenance gate

`load_cloud_dataset` reads `runs/dpf_cloud_manifest.json`. Every usable cloud case must have passed validation, successful archived simulation status, project and simulation job IDs, a bounded pressure normalization factor, and matching SHA256 hashes for its archived source files. Manifest geometry, identifiers and normalization factors must agree with the hashed state and validation. The cloud script includes state, sampled outputs, generated weak forms and validation among these sources. Source paths are constrained to `ExhaustLab`.

The complete study must also declare itself ready, contain its expected number of unique geometry pairs, and have passed mesh verification. Mesh and parallel-batch evidence files are hash-checked; mesh evidence source hashes include the independent refined case. Their reported summary values and case counts must match the archived evidence. Individually passed cases cannot authorize complete-study status while these readiness requirements remain unmet.

In verified mode, the planner uses the finite-element pressure normalization only for exact matching diameter/length pairs. A requested geometry without such evidence is excluded, not interpolated. Linear viscosity/flow/permeability scaling follows the homogeneous Darcy equation; it is not a claim of turbulent or nonlinear DPF validation. A missing, failed or replaced source produces explicit `analytic_screening` mode and exposes the cloud error. Analytical screening does not claim Allsolve provenance.

## What additional data would turn this into an engineering design tool?

Measured engine duty histories at the intended filter location, permissible backpressure, cartridge-family clean/loaded pressure curves over geometry and flow, capture specifications over particle distributions, thermal mass and heat-transfer characterization, soot/ash capacity and validated soot oxidation kinetics. A real wall-flow resistance model should replace the homogeneous plug law before sizing a commercial DPF. Detailed 3D housings and spatial thermal gradients are also needed before judging flow maldistribution or regeneration damage.

Primary references checked on 2026-10-03:

- [EPA: DPF installation](https://www.epa.gov/sites/default/files/2016-03/documents/420f10028.pdf): selection depends on temperature duty history at the installation location; exhaust pipe insulation can retain heat. Temperature/time requirements differ by filter design. Its example thresholds are not adopted as universal regeneration criteria here.
- [EPA: DPF operation and maintenance](https://www.epa.gov/sites/default/files/2016-03/documents/420f10027.pdf): accumulated particulate raises backpressure; manufacturers specify engine limits; regeneration and periodic ash cleaning serve different functions.
- [Corning researchers: pressure-drop theory and experiment, SAE 2000-01-0184](https://saemobilus.sae.org/papers/predicting-pressure-drop-wall-flow-diesel-particulate-filters-theory-experiment-2000-01-0184): real wall-flow pressure comprises wall, channel and entrance/exit contributions and was calibrated against measured filter geometries. The public abstract supplies no transferable complete numerical coefficient set, so none is invented here.
- [Corning: development of particulate filters](https://www.corning.com/media/worldwide/cet/documents/American_Ceramic_Society_bulletin_042020.pdf): explains alternately plugged ceramic channels, wall porosity and the effects of soot deposits.
- [NASA Glenn: viscosity](https://www.grc.nasa.gov/www/BGH/viscosity.html): viscosity depends on gas temperature; Sutherland air approximation. The implementation uses SI reference constants `mu0=1.716e-5 Pa s`, `T0=273.15 K`, `S=110.4 K`.
- [Churchill: friction-factor equation, original paper](https://files.engineering.com/files/85c0f3a6-a102-4a22-9d35-f15858c0dd2b/CEM_-_Friction-factor_equation_%281977%29.pdf): local all-regime pipe correlation; no claim of CFD validation for bends, contractions or turbulent housings.

## Verification

Run from the workspace root:

```powershell
python -m unittest ExhaustLab.tests.test_planner -v
```

Tests check mass-flow/temperature/absolute-pressure coupling, Darcy dimensions and scaling, exact heating/cooling threshold crossings, insulation effects, clean versus loaded losses, pressure-driven geometry selection, strict finite-grid objectives, capture/envelope infeasibility with no fabricated winner, input validation, exact cloud geometry matching, and hash replacement invalidating cloud provenance.
