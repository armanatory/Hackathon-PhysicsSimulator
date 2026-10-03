# Three parallel Quanscient case threads

This chat is the master coordination thread. Create three separate Codex threads in the **same `F:\H4H quanscient` project**. Give each new thread one of the prompts below. Each case has its own `AGENTS.md`; later case-specific user prompts can be appended there without mixing the work.

The shared teammate repository `Hackathon-PhysicsSimulator` must stay untouched unless the team explicitly coordinates a change. Never put the Allsolve API keys in chat, frontend code, or Git. The root `.env` already holds them for local server-side use.

## Prompt 1 — MetaSense optical protein sensor

> Own the MetaSense case in `F:\H4H quanscient\MetaSense`. Read `MetaSense\AGENTS.md` and `MetaSense\README.md` first. Advance the real Allsolve optical modeling of the dielectric metasurface sensor. The current surrogate is synthetic and the Allsolve mode returns 501. Prioritize proving a physically valid optical source and reflected/transmitted readout in the installed SDK, then a unit cell, materials, binding layer, spectral sweep, and validation. Keep synthetic and real results separate, and address whether the streptavidin–biotin assay actually has a protein analyte. Work only in this case folder and use local ports 5174/8001. Do not edit or push the shared teammate repository. Report real job provenance and concrete SDK friction.

## Prompt 2 — RoomValue 3D cafeteria acoustics

> Own the acoustic case in `F:\H4H quanscient\RoomValue`. Read `RoomValue\AGENTS.md`, `RoomValue\README.md`, and `RoomValue\SDK_FEEDBACK.md` first. The user requires the finished app to use a **real 3D Allsolve model of a room or space** for school/cafeteria noise and cost-aware acoustic treatment placement. The current 2D 250 Hz app is a verified feasibility test only. Build a 3D room with source/receiver heights and at least two treatment locations, run genuine Allsolve baseline and candidate jobs, validate the mesh and outputs, then investigate a 3D transient room impulse response. Keep modeled frequency limits and uncalibrated product properties explicit. Work only in this case folder and use local ports 5175/8002. Do not edit or push the shared teammate repository.

## Prompt 3 — Exhaust particle collector

> Own the third case in `F:\H4H quanscient\ExhaustLab`. Read `ExhaustLab\AGENTS.md` first. Explore particle collection from combustion exhaust for an application relevant to cars, ships, or power plants, beginning with one bounded device and operating range. Verify real Allsolve physics before building claims: a promising pilot is a precharged-aerosol electrostatic collector with Allsolve airflow and electric-field solves, plus clearly separated particle-trajectory postprocessing if no particle-tracing API is available. Compare actual geometries by conditional capture, pressure drop, and entered cost or power. Do not call the pilot a measured emissions reduction or claim CO2/NOx removal. Use separate local ports 5176/8003, keep credentials server-side, and do not edit or push the shared teammate repository. Record SDK pain points and exact solver provenance.

## Master-thread role

Track scope, judge criteria, cross-case blockers, working URLs, and which idea has the strongest validated demo. Let each case thread own its folder and implementation. Forward later requirements to the appropriate case thread and its `AGENTS.md`.
