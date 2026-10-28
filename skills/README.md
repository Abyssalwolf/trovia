# Trovia skills

Ready-made [agent skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) that
teach an AI agent how to use Trovia. Each folder is one skill: a `SKILL.md` with a name, a description
that tells the agent when to use it, and instructions.

| Skill | Use it when |
|---|---|
| [trovia-rest-api](trovia-rest-api/SKILL.md) | the agent should call Trovia's REST API directly (curl, scripts, any HTTP client) |
| [trovia-mcp](trovia-mcp/SKILL.md) | the agent should install Trovia, register its MCP server, and use the `web_search` tool |

## Downloads

The `Pages` workflow zips each skill folder on every push to `main` and publishes it with the website:

- https://abyssalwolf.github.io/trovia/skills/trovia-mcp.zip
- https://abyssalwolf.github.io/trovia/skills/trovia-rest-api.zip

Each archive has the skill's folder at its top level, so unzipping it into a skills folder (for Claude
Code, `~/.claude/skills/`) is all an install takes.

The skills only work with agents that run on the user's own machine (for example Claude Code or Claude
Desktop), because Trovia listens on `localhost`; a cloud-hosted agent cannot reach it.
