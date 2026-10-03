# MetaSense frontend

React 18 + TypeScript + Vite scaffold for the streptavidin–biotin metasurface sensor concept.

## Run locally

1. Start the FastAPI backend on `127.0.0.1:8001` as described in the parent `MetaSense/README.md`.
2. From this folder, run `pnpm install --frozen-lockfile` and `pnpm dev`.
3. Open <http://127.0.0.1:5174/>. Vite proxies `/api` to the backend.

Build and type-check with `pnpm run build` and `pnpm run typecheck`.

The **Surrogate demo** mode calls `POST /api/jobs` and displays only server-returned synthetic spectra and indicative metrics. The **Allsolve** mode is visible but cannot run until a real, validated optical workflow is connected. No API keys belong in this frontend; the server reads them from its environment.
