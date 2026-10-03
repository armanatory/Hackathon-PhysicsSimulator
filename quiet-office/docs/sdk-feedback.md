# Allsolve SDK feedback (QuietOffice)

SDK usability notes, pain points and suggestions found while building QuietOffice.
Kept here so it does not conflict with the shared [docs/sdk-feedback.md](../../docs/sdk-feedback.md); copy rows over when the team merges.

| When | Who | What we tried | What happened | Suggestion |
|------|-----|---------------|---------------|------------|
| 3 Oct | Arman (with Claude) | Find the keyword arguments for the acoustic boundary conditions (`AcousticWavesNormalAcceleration`, `AcousticWavesAcousticDamping`, `AcousticWavesAbsorbingBoundary`) | The acoustics skill only covers transducers and PML. The SDK reference page is one very long page, so the entries were out of reach. We had to read `src/allsolve/physics/generated/interactions.py` on GitHub. The generated docstrings repeat the parameter name ("acoustic waves normal acceleration") with no unit or meaning | One reference page per physics, and docstrings with unit and sign convention. A room-acoustics example (source + absorbing walls + probe points) next to the PMUT one |
| 3 Oct | Arman (with Claude) | Set up credentials by following the docs | The SDK skill says `ALLSOLVE_ACCESS_KEY` / `ALLSOLVE_SECRET_KEY`, the example app uses `QS_ACCESS_KEY` / `QS_SECRET_KEY` | Pick one naming and use it in both |
| 3 Oct | Arman (with Claude) | Use the beer-cooling app as the template for our backend | It uses the older style: a config dict into `import_project()` plus a hand-written solver script. The skills teach the builder API (`geometry_builder`, `PhysicsSet`, `create_simulation_harmonic`) and warn off some of what the example does | Update the example app to the current API, or say at the top which style new projects should copy |
