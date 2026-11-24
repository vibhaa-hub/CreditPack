# Project instructions

## Architecture document

The technical architecture doc is a Claude Doc: https://claude.ai/artifact/A5WZV9Rwf5dt5No5PGAS6Q
(linked from `cpa_app/ARCHITECTURE.md`).

After any change to architecture-relevant code, update the matching section of that doc in the
same task, using the Claude Docs tools: read only the section you need, edit only what changed,
and keep the diagrams in step (widget nodes under sections 2, 3.4 and 5.1). Architecture-relevant
means agents, skills, the workflow graph, tools, rules, `policy.yaml`, the LDU manifest or runtime,
store tables, workbench endpoints, roles or gates, environment variables, the Dockerfile or
docker-compose. Pure refactors, tests and copy changes need no doc update.

When you finish such a change, say in your reply which doc section you updated, or that none
needed it.
