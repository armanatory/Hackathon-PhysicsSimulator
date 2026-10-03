# Quanscient shared agentic AI tools

This repo contains useful skills and links to external resources for improving agentic AI for coding, design, marketing and other relevant topics at Quanscient.

## Main skill: Allsolve SDK

The primary skill in this repo is **`skills/sdk-skills/allsolve-sdk`** — it teaches AI agents how to build multiphysics cloud simulations with the Quanscient Allsolve Python SDK. Point your Cursor skill configuration at this path to get started.

The skill also references several domain-specific and building-block sub-skills under `skills/sdk-skills/` (RF, structural, thermal, acoustics, geometry, mesh, etc.).

## Prerequisites for Cursor usage: 

**`allsolve-docs` MCP server** (recommended)

- The `allsolve-docs` MCP server gives the agent instant local search across all Allsolve documentation: skill files, REST API spec, solver scripting type stubs, SDK examples, and the documentation website. Setting it up is recommended but not required — the skills and online docs provide enough context to work without it.

- Instructions to set it up are in https://github.com/Quanscient/allsolve-docs-mcp

**Add these skills**

- Cursor discovers skills from `~/.cursor/skills/` (personal, all projects) or `.cursor/skills/` (project-specific). Add these skills to one of the locations.