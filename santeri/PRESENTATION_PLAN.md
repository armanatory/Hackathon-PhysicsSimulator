# Hackathon presentation plan — 3 October 2026

Demo slots begin at **16:00** and project submissions close at **17:00**. Rehearse a three-minute core pitch that can be shortened if the slot is tighter.

## Lead demo decision

Lead with **RoomValue** at <http://127.0.0.1:5175/>. It currently has a real 3D Allsolve acoustic room, cloud job provenance, a 3D placement planner, and concrete SDK feedback. The other two cases can be mentioned as parallel exploration if asked. MetaSense has a validated optical slab but not yet a full sensor; ExhaustLab has validated cloud calculations but its current planner reads archived cases rather than launching new cloud jobs from each UI request.

If the full RoomValue search is still running at the presentation checkpoint, use its already [verified 3D baseline/east-wall/ceiling comparison](RoomValue/experiments/room3d/VERIFIED_3D.json) and [Allsolve project](https://allsolve.quanscient.com/#/projects/poAAljkgyCczG-Khjn/model). Do not substitute the older 2D result for the required 3D model.

## Four-slide story

1. **Problem and buyer.** School/cafeteria facilities teams have limited budgets and need to choose *where* to put acoustic treatment. Show the 3D room, source, listener/quiet zones, and candidate wall/ceiling positions.
2. **Physics and decision.** The app builds a 3D room-acoustics model, retrieves real Allsolve pressure fields, evaluates selected quiet areas, and searches affordable treatment layouts. Explain the precise modeled target: pressure reduction at **125 Hz**, not broadband speech clarity.
3. **Live result.** Show one complete, saved result with its project/job IDs, baseline, proposed placement(s), cost input, and receiver or quiet-area change. Then submit a small fresh input that needs a missing Allsolve solve, or show the job state while keeping the complete result ready. Avoid relying on a long many-layout cloud run to finish during the speaking slot.
4. **SDK experience and next step.** Show three specific findings: mesh-size settings differed from measured maximum tetrahedron edges; source/probe placement mistakes were detected late; a larger direct solve failed without a clear memory reason. Ask for geometry/probe preflight, acoustic point probes, and memory estimates. State the scientific next steps: measured treatment loss and source calibration, more frequencies, and a transient room impulse response.

## Three-minute talk track

- **0:00–0:30:** “A school can afford only a few treatments. Placing them by intuition can waste the budget. Our app asks which placement protects the selected quiet areas.”
- **0:30–1:30:** Show the 3D room and inputs; set source, quiet zones, budget and allowed wall/ceiling positions; show the optimizer's chosen layout or an honest infeasible outcome.
- **1:30–2:15:** Show the real Allsolve project/job and the baseline-versus-treatment pressure result. State the modeled frequency, room/source assumptions, and that prices are user inputs.
- **2:15–2:50:** Give SDK pain points and concrete improvements from [`RoomValue/SDK_FEEDBACK.md`](RoomValue/SDK_FEEDBACK.md).
- **2:50–3:00:** Close with the decision the user can make today and the data needed before recommending a commercial product.

## Preparation before 16:00

- **By 15:15:** Freeze one completed RoomValue 3D demo scenario and verify the local page, API, cloud project link, and result provenance. Decide whether the full optimizer or the simpler verified 3D comparison is the onstage result.
- **By 15:30:** Make four visual slides/screenshots. Put the exact 125 Hz limitation and illustrative material loss on the result slide. Assign one person to speak, one to operate the site, and one to keep the backup result ready.
- **By 15:45:** Rehearse twice, including an offline/slow-cloud fallback. Have the completed result and screenshots open in separate tabs. Avoid typing API keys or showing `.env`.
- **Before 17:00:** Submit the app URL or local access instructions, source folder, README, real Allsolve project/job evidence, and SDK feedback. Verify the submission requirements from the organizer page. Do not submit credentials.

## Exact claim discipline

The current 3D room is a calibrated **laboratory fixture** from dEchorate, not a measured school cafeteria. The harmonic solver result is at **125 Hz** with rigid boundaries, a normalized source and illustrative volumetric damping. It supports a comparative prototype. It does **not** establish measured dB(A), speech intelligibility, a commercial product rating, or a full room impulse response.
