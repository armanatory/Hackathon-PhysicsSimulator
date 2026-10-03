# Ideas — Arman

Copy the block below for each idea.

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




-------
The main prompt that I used:

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