# Architecture

The full technical architecture of this app lives in one living document:

**[CPA App — Technical Architecture](https://claude.ai/artifact/A5WZV9Rwf5dt5No5PGAS6Q)**

It covers:

1. Overview, tech stack and repository layout
2. High-level design (layers, deployment diagram, runtime modes)
3. Agent mesh (19 agents, skills, tool allowlists, workflow graphs, state partitions, audit callbacks)
4. Least Deployable Units (manifest, units, mapping to `AST.md` DU-01..DU-12)
5. Low-level design (step lifecycle, queue, heartbeats, retries, process bootstrap)
6. Data and persistence (tables, hash-chained audit, human write path)
7. Rules, policy and tools (calculations, DT-2 gate R1..R8, `policy.yaml`)
8. Workbench and human gates (API, roles, ARCH-H09 prerequisites, live updates)
9. End-to-end flows
10. Build, run and deploy (single-process, Docker Compose, environment variables, tests)
11. Before you add or change files (invariants and checklists)
12. Known trade-offs, gaps and open points

## Keeping it current

Update the document in the same change as the code whenever you change any of:

- agents, skills or the workflow graph (`cpa_agents/mesh/`, `cpa_agents/skills/`)
- tools, rules or policy parameters (`cpa_agents/tools/`, `cpa_agents/rules/`, `cpa_agents/policy.yaml`)
- LDUs, the queue or the runtime (`cpa_agents/ldu/`, `docker-compose.yml`, `Dockerfile`)
- tables or the audit/human-write path (`cpa_agents/store/`)
- workbench endpoints, roles or gates (`workbench/`)
- environment variables or how the app is built and run

Claude Code sessions in this project do this automatically (see `../CLAUDE.md`).
