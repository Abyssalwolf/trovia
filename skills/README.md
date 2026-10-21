# Trovia skills

Ready-made [agent skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) that
teach an AI agent how to use Trovia. Each folder is one skill: a `SKILL.md` with a name, a description
that tells the agent when to use it, and instructions.

| Skill | Use it when |
|---|---|
| [trovia-rest-api](trovia-rest-api/SKILL.md) | the agent should call Trovia's REST API directly (curl, scripts, any HTTP client) |
| [trovia-mcp](trovia-mcp/SKILL.md) | the agent should install Trovia, register its MCP server, and use the `web_search` tool |

## Before you publish them

Both skills contain the placeholder `https://YOUR-SITE/` in the install commands. Replace it with the
address where you host `scripts/install.sh` and `scripts/install.ps1`:

```bash
grep -rl "YOUR-SITE" skills README.md docs scripts
```

(The same placeholder appears in the README and the docs.)

## Offering them for download

Zip each skill folder so that the folder itself is the top level of the archive:

```bash
cd skills
zip -r trovia-rest-api.zip trovia-rest-api
zip -r trovia-mcp.zip trovia-mcp
```

On Windows PowerShell: `Compress-Archive -Path trovia-mcp -DestinationPath trovia-mcp.zip`.

The skills only work with agents that run on the user's own machine (for example Claude Code or Claude
Desktop), because Trovia listens on `localhost`; a cloud-hosted agent cannot reach it.
