# QuietOffice frontend

Vue 3 + Vite + TypeScript + Pinia. Structure follows the reference app in
[beer_cooling_app/frontend](../../docs/quanscient-docs/beer_cooling_app/frontend); the look comes
from the sketch in [docs/ui-exploring/03-quiet-office](../../docs/ui-exploring/03-quiet-office).

```
frontend/src/
├── api/optimization.ts          # backend client
├── components/
│   ├── OfficePlan.vue           # floor plan, sound map, before/after divider
│   ├── OfficeEditor.vue         # drag walls, desks, conversation; open and trace a scan
│   ├── Office3D.vue             # 3D view of room, panels at their height, and the scan (three.js)
│   ├── ControlPanel.vue         # screens, speech bands, search, run on Allsolve
│   ├── ScoreCard.vue            # noise score before and after
│   ├── PlacementList.vue        # where each screen goes
│   ├── SearchChart.vue          # every layout tested
│   └── RunLog.vue               # live Allsolve run log, solver vs estimate table, AI explanation
├── physics/estimate.ts          # quick in-browser estimate (not the solver)
├── physics/geometry.ts          # polygon helpers for the floor plan
├── scan/glb.ts                  # reads a phone scan (.glb) and slices it into a floor plan
├── stores/optimizationStore.ts  # Pinia state
├── types/index.ts               # types shared with the backend
└── App.vue
```

## Setup

Needs Node.js 18 or newer.

```bash
npm install
```

```bash
npm run dev
```

Open http://localhost:5173. Requests to `/api` are proxied to the backend on port 8000.

## Two sources of numbers

- **Quick estimate**: a simple geometric model in [`src/physics/estimate.ts`](src/physics/estimate.ts).
  It runs in the browser, answers instantly and draws the coloured sound map. The page uses it on
  load and whenever the backend is not reachable, so the UI works without Python or credentials.
- **Allsolve simulation**: "Run on Allsolve" sends the same request to the backend, polls the
  status and replaces the desk levels and scores with the solver's. The badge in the top bar says
  which one is on screen.

The sound map is always the quick estimate. After an Allsolve run it is faded, because the
solver returns values at the listening points only; the numbers on the desks and zones are
then the solver's.

The **Where these numbers come from** panel makes the source explicit. Before a run it says
plainly that nothing has been sent to Allsolve. During a run it lists every request and answer
as it happens. Afterwards it shows the Allsolve project, the cloud jobs, and a table with the
estimate, the Allsolve level and the raw solver pressure for every listening point.
**Explain this result** asks an AI model to put the result and the record in plain language.

## Editing the office

The **Edit office** tab is a floor-plan editor: drag the room corners, desks, the conversation
and the places a screen may stand, or open a phone scan and trace the room over it. Every
change re-runs the quick estimate, and the office is remembered in the browser. See
[docs/scan-import.md](../docs/scan-import.md).

## Noise sources, quiet zones and suggested positions

In the editor you can place several noise sources, each with a name and a level, and draw
quiet zones: rectangles that should be quiet, resized with their corner handle. Desks still
work as single listening points. The result shows the average level over each zone, before
and after.

**Suggest screen positions** fills in the places a screen could stand, so you do not have to
mark them by hand. It tries both directions on a 1 m grid and keeps the positions that stand
in the way of the most sound travelling from a source to a listening point, skipping spots on
top of sources, desks, zones or walls. The search then picks the best of those.

## Panels and the 3D view

Panels differ in height and surface. The control panel offers a desk divider (1.2 m), an
acoustic screen (1.6 m) and a tall partition (2.0 m), each hard or absorbing. The quick
estimate takes this into account: sound goes round both ends and over the top of a panel, and a
panel lower than the line from mouth (1.5 m) to ear (1.2 m) does nothing at all.

The **3D view** tab shows the room, the chosen panels at their real height, desks coloured by
the speech level left there, and the phone scan if one is loaded. The 3D library is only
downloaded when that tab is opened.

"Allsolve model" chooses what the backend solves: the full 3D room or the cheaper 2D slice.

## Build

```bash
npm run build
```

Type-checks with `vue-tsc` and writes `dist/`.
