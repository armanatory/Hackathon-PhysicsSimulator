# QuietOffice

**Physics-optimized acoustic panel placement for open-plan offices**

## One-line idea

Given an open-office layout, known speech/noise sources, employee desk locations, and a limited number of acoustic panels, use **Quanscient Allsolve** and its **Python SDK** to find panel placements that reduce simulated speech propagation across the workspace.

---

## The problem

Open-plan offices make communication and collaboration easy, but unwanted speech and background noise can also travel across the room and distract people who are trying to concentrate.

Companies often buy acoustic panels, desk dividers, or movable screens, but a practical question remains:

> **If we can afford only a few acoustic panels, where should we actually put them?**

The goal of QuietOffice is not simply to simulate office acoustics.  
The goal is to use physics simulation to make a **specific placement decision**.

---

## Core hackathon question

> **You have only three acoustic panels. Where should you place them to reduce speech noise for the most people?**

Possible extensions:

- What if only one panel can be added?
- Is it better to place panels near the speaker or near the affected desks?
- How much improvement comes from adding a second or third panel?
- Which layout gives the best acoustic improvement per euro spent?

---

## Why Allsolve is central

The project relies on physical simulation rather than an AI or rule-based guess.

Allsolve can be used to model acoustic-wave propagation through a simplified office geometry and evaluate how different panel placements change the acoustic field.

The **Python SDK** is essential because it can automate the experiment:

1. Generate or modify the office geometry.
2. Move acoustic panels to different candidate locations.
3. Change relevant simulation parameters.
4. Launch repeated Allsolve simulations.
5. Retrieve acoustic results at desk locations.
6. Calculate a score for every layout.
7. Select the best-performing configuration.

The core value comes from repeated physics simulations, not from an application that merely calls Allsolve once.

---

## Allsolve physics

### Main physics

- **Acoustic waves**
- **Harmonic simulations**
- **Acoustic damping / absorbing regions or appropriate acoustic boundary treatment**

### Possible later extensions

- Acoustic-structure interaction
- Multiple source locations
- Multiple frequencies
- Different panel materials
- Different office geometries

For the hackathon MVP, these extensions are optional.

---

## MVP scope

Keep the first version deliberately small.

### Geometry

Use a **simple 2D top-down office**.

Example:

```text
┌───────────────────────────────────────┐
│                                       │
│  Speaker                              │
│    🔊       Desk   Desk   Desk        │
│                                       │
│              █                        │
│              █ Panel                  │
│                                       │
│  Desk   Desk          Desk   Desk     │
│                                       │
│                           █           │
│                           █ Panel     │
│                                       │
└───────────────────────────────────────┘
```

Do not model every chair, monitor, lamp, person, or ceiling detail.

### Noise source

Start with:

- one speaking location
- one or a few representative speech frequencies

Possible frequencies for a simplified demonstration:

- 250 Hz
- 500 Hz
- 1000 Hz
- 2000 Hz

### Receiver points

Place measurement points at approximately 8–20 desk locations.

For each simulation, retrieve the acoustic pressure or another suitable acoustic quantity at these locations.

### Optimization variables

For the MVP, vary only:

- panel location
- optionally panel orientation
- optionally number of panels

Avoid optimizing panel dimensions, material properties, source locations, desk positions, and frequency simultaneously.

---

## Optimization concept

The Python SDK runs many candidate layouts.

```text
Layout A
   ↓
Allsolve simulation
   ↓
Desk noise score = 82

Layout B
   ↓
Allsolve simulation
   ↓
Desk noise score = 71

Layout C
   ↓
Allsolve simulation
   ↓
Desk noise score = 64   ← best

Layout D
   ↓
Allsolve simulation
   ↓
Desk noise score = 69
```

A simple objective function could minimize:

```text
average acoustic pressure across desks
```

or:

```text
worst affected desk
```

A stronger objective may combine both:

```text
score =
    average desk exposure
    +
    penalty for very noisy desks
```

This prevents the optimizer from making most desks quiet while leaving one person in a very bad location.

---

## Budget-constrained version

A strong extension is to introduce a fixed budget.

Example:

| Treatment | Cost |
|---|---:|
| Small desk divider | €100 |
| Medium acoustic screen | €180 |
| Large movable partition | €300 |

Constraint:

```text
Total cost <= €500
```

Then the question becomes:

> **What is the best use of €500 to reduce simulated speech propagation in this office?**

This turns QuietOffice from a pure simulation into a practical workplace decision-support tool.

---

## Suggested result visualization

### Before

Show an acoustic heatmap of the office.

```text
Speaker →   🔴 🔴 🔴
             🔴 🔴
          🟠 🟠 🔴
```

### After optimization

Show the optimized panel positions and a second heatmap.

```text
Speaker →  █ PANEL

            🟢 🟢 🟡
        █
        █ PANEL

            🟢 🟢 🟢
```

Then show a simple comparison:

```text
BEFORE
Noise score: 100

AFTER
Noise score: 68

Relative improvement: 32%
```

The number should be described as improvement **within the simulation model**, not as a certified real-world dB reduction unless the model has been properly calibrated.

---

## Scientific grounding

The project can be backed by research and standards related to open-plan office acoustics.

A particularly relevant standard is:

### ISO 3382-3:2022

**Acoustics — Measurement of room acoustic parameters — Part 3: Open plan offices**

It focuses specifically on acoustic conditions in open-plan offices and includes concepts related to the propagation and decay of speech across workplaces.

QuietOffice does **not** need to claim compliance with ISO 3382-3.

A safer framing is:

> **Inspired by established open-plan office acoustic metrics such as those described in ISO 3382-3.**

Research on open-plan offices also supports the general premise that intelligible speech can be distracting and that room acoustic design, screens, absorption, and spatial treatment affect perceived acoustic conditions.

For the hackathon, one standard and one or two papers are enough. The purpose is to show that the human problem is real, not to reproduce an academic study.

---

## CAD / geometry strategy

Do **not** begin with a detailed real-office CAD model.

Recommended progression:

### Stage 1 — MVP

Programmatically create a synthetic rectangular office using simple geometry.

### Stage 2 — Better demo

Approximate a real office floor plan.

### Stage 3 — Stretch goal

Import a simplified STEP or other supported CAD model into Allsolve.

A detailed CAD model should only be attempted after the simulation and optimization loop already works.

---

## Team split

A four-person team could work in parallel.

### Person 1 — Physics / Allsolve

- build office geometry
- configure acoustic simulation
- define source and boundaries
- model acoustic panels
- validate that the model produces sensible results

### Person 2 — Python SDK / optimization

- automate geometry or panel placement
- run parameter sweeps
- retrieve results
- calculate layout scores
- select the best configuration

### Person 3 — UI / visualization

- office floor-plan visualization
- before/after heatmaps
- panel-placement display
- optimization progress/results
- simple controls for number of panels or budget

### Person 4 — Product / pitch

- problem framing
- scientific references
- cost assumptions
- demo script
- presentation
- storytelling

---

## Suggested hackathon implementation path

### Step 1

Create one simple 2D office.

### Step 2

Place one acoustic source and a set of desk measurement points.

### Step 3

Run one successful acoustic simulation manually.

### Step 4

Add one movable acoustic panel.

### Step 5

Use the Python SDK to test several panel locations automatically.

### Step 6

Retrieve the acoustic result at the desks and calculate a score.

### Step 7

Select the best layout.

### Step 8

Create a before/after visualization.

### Step 9

If time remains, add:

- multiple panels
- several frequencies
- a € budget constraint
- a simplified real office layout

---

## Demo flow

A short demo could be:

### 1. Show the problem

> "This is an open office. A conversation here can disturb people several desks away."

### 2. Show the untreated simulation

Display the acoustic field.

### 3. Introduce the constraint

> "We have money for only three acoustic screens."

### 4. Start the optimizer

The Python SDK generates layouts and launches Allsolve simulations.

```text
Testing layout 1...
Testing layout 2...
Testing layout 3...
...
Testing layout 30...
```

### 5. Reveal the result

Show the optimized panel positions.

### 6. Show before vs after

Display both acoustic heatmaps and the relative score improvement.

### 7. Finish with the practical message

> **Instead of asking whether acoustic panels work, QuietOffice asks where limited acoustic treatment will have the greatest simulated impact.**

---

## What NOT to do during the hackathon

Avoid:

- full 3D office reconstruction
- detailed chairs and furniture
- turbulent HVAC simulation
- natural-convection modeling
- people as dynamic acoustic objects
- dozens of material types
- optimization of every possible variable
- claiming ISO certification
- claiming medically or scientifically exact real-world noise reductions
- spending most of the hackathon creating CAD

The winning scope is:

> **One office. One noise source. A few panels. A few frequencies. One optimization metric. One clear answer.**

---

## Success criteria for the MVP

By the end of the hackathon, QuietOffice should be able to:

- [ ] simulate acoustic propagation in a simplified open office
- [ ] place at least one acoustic screen/panel
- [ ] run multiple configurations automatically with the Allsolve Python SDK
- [ ] retrieve acoustic results at desk locations
- [ ] calculate a comparative layout score
- [ ] identify the best tested panel placement
- [ ] visualize before vs after
- [ ] explain the result in less than 30 seconds

---

## Final pitch

> **QuietOffice uses physics simulation to answer a practical workplace question: if an open office can afford only a limited amount of acoustic treatment, where should it go?**
>
> Using Quanscient Allsolve, we simulate speech propagation through the office. Using the Allsolve Python SDK, we automatically test different acoustic-panel layouts, measure the simulated exposure at employee desks, and select the configuration that performs best.
>
> Instead of buying acoustic panels and guessing where to put them, QuietOffice turns acoustic treatment into a physics-based optimization problem.

---

## Working title options

- **QuietOffice**
- **QuietPlan**
- **AcoustiPlan**
- **SoundSpace**
- **OfficeSilence**
- **QuietDesk**
- **Acoustic Optimizer**
- **LessTalk**
- **HushOffice**

**Recommended:** **QuietOffice**

### Tagline

> **Put acoustic treatment where physics says it matters.**
