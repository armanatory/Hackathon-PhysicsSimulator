# QuietOffice frontend

Vue 3 + Vite + TypeScript + Pinia. Structure follows the reference app in
[beer_cooling_app/frontend](../../docs/quanscient-docs/beer_cooling_app/frontend); the look comes
from the sketch in [docs/ui-exploring/03-quiet-office](../../docs/ui-exploring/03-quiet-office).

```
frontend/src/
├── api/optimization.ts          # backend client
├── components/
│   ├── OfficePlan.vue           # floor plan, sound map, before/after divider
│   ├── ControlPanel.vue         # screens, speech bands, search, run on Allsolve
│   ├── ScoreCard.vue            # noise score before and after
│   ├── PlacementList.vue        # where each screen goes
│   └── SearchChart.vue          # every layout tested
├── physics/estimate.ts          # quick in-browser estimate (not the solver)
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

The sound map is always the quick estimate, also after an Allsolve run. Showing the solver's
pressure field is not built yet.

## Build

```bash
npm run build
```

Type-checks with `vue-tsc` and writes `dist/`.
