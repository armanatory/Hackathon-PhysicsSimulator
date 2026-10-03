# Hackathon-PhysicsSimulator

Our entry for **Hack for Humanity: Finland** (Tampere, 3 Oct 2026) — the Quanscient challenge:

> Pick a real engineering problem. Build an app that solves it with Allsolve simulations.

**Idea: TBD** — everyone brainstorms in their own file ([Arman](docs/idea-Arman.md), [Santeri](docs/idea-Santeri.md), [Veli](docs/idea-Veli.md)), the chosen one goes in [docs/idea.md](docs/idea.md).

## Repo layout

Each idea is built in its own folder, with its own backend, frontend, simulations and docs, so
work on different ideas does not collide. Shared material stays in `docs/`.

```
├── quiet-office/   # Arman: acoustic screen placement for open offices (see its README)
├── <your-idea>/    # one self-contained folder per idea
└── docs/
    ├── idea.md             # the chosen idea
    ├── idea-<name>.md      # personal brainstorm files (Arman, Santeri, Veli)
    ├── sdk-feedback.md     # SDK pain points & insights (a judging criterion!)
    ├── pitch.md            # pitch / demo notes
    ├── ui-exploring/       # static UI sketches, one numbered folder each
    └── quanscient-docs/    # challenge brief, example app, SDK agent skills
```

## What the judges look for

1. A meaningful industry problem that provides value for the user
2. Creativity / originality of the use case
3. SDK experience and insights — usability, pain points, improvement ideas
4. A working demo — real physics, logic that seems correct

## Getting started

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r <your-idea>/backend/requirements.txt
cp .env.example .env            # then fill in your Allsolve access + secret key
```

Never commit `.env` or API keys.

## Reference material

- Challenge brief: [docs/quanscient-docs/HackForHumanity.pdf](docs/quanscient-docs/HackForHumanity.pdf)
- Example app (beer cooling): [docs/quanscient-docs/beer_cooling_app](docs/quanscient-docs/beer_cooling_app)
- SDK agent skills (for Cursor / Claude Code): [docs/quanscient-docs/sdk-skills](docs/quanscient-docs/sdk-skills)
- Allsolve: https://allsolve.quanscient.com/
- SDK documentation: https://allsolve.quanscient.com/documentation/start-here/introduction
- SDK: https://github.com/Quanscient-Public/allsolve-sdk-python

## Working together

- Work on a branch (`<name>/<short-topic>`), open a PR or merge small and often.
- Log every SDK surprise in [docs/sdk-feedback.md](docs/sdk-feedback.md) as it happens.
