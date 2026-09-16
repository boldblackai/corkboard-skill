# Corkboard Skill

A **zero-dependency, stdlib-only Python CLI** that lets AI agents read
and write Corkboard wikis through the HTTP API v1.  Install once and
your agent (Hermes, Claude Code, Codex, or any shell-capable assistant)
can create pages, edit content, upload media, search, and garden a
workspace — all with API-token auth and optimistic concurrency.

Corkboard is a fast, Markdown-native wiki with full-text and semantic
search.  This skill is the CLI bridge: no MCP client, no SDK, no `pip
install` — just Python 3 and a shell.

## Install

Pick the agent you use and run the one-liner in your terminal.

### Hermes

```bash
git clone https://github.com/boldblackai/corkboard-skill.git ~/.hermes/skills/corkboard
```

### Claude Code

```bash
git clone https://github.com/boldblackai/corkboard-skill.git ~/.claude/skills/corkboard
```

### Codex (OpenAI)

```bash
git clone https://github.com/boldblackai/corkboard-skill.git ~/.codex/skills/corkboard
```

### Curl (single-file, any agent)

```bash
mkdir -p ~/agent-skills/corkboard/script
curl -sSL https://raw.githubusercontent.com/boldblackai/corkboard-skill/main/SKILL.md -o ~/agent-skills/corkboard/SKILL.md
curl -sSL https://raw.githubusercontent.com/boldblackai/corkboard-skill/main/script/corkboard.py -o ~/agent-skills/corkboard/script/corkboard.py
curl -sSL https://raw.githubusercontent.com/boldblackai/corkboard-skill/main/script/cb_client.py -o ~/agent-skills/corkboard/script/cb_client.py
curl -sSL https://raw.githubusercontent.com/boldblackai/corkboard-skill/main/script/cb_pages.py -o ~/agent-skills/corkboard/script/cb_pages.py
curl -sSL https://raw.githubusercontent.com/boldblackai/corkboard-skill/main/script/cb_collections.py -o ~/agent-skills/corkboard/script/cb_collections.py
curl -sSL https://raw.githubusercontent.com/boldblackai/corkboard-skill/main/script/cb_media.py -o ~/agent-skills/corkboard/script/cb_media.py
curl -sSL https://raw.githubusercontent.com/boldblackai/corkboard-skill/main/script/cb_me.py -o ~/agent-skills/corkboard/script/cb_me.py
```

The skill uses a **plain-directory layout:** `SKILL.md` at the root,
`script/` for Python modules.  No `pip install`, no virtualenv,
no post-install step.

## Configuration

Set the API token in your agent's shell profile:

```bash
export CORKBOARD_TOKEN="cb_your_api_token"
```

`CORKBOARD_TOKEN` is required — the CLI exits with a clear error if it
is missing.  The token is **user-scoped**: one token reaches every
workspace you can access.

Content endpoints are **workspace-scoped**, so the CLI also needs an
`org_slug/ws_slug` pair — see *Workspaces* below.

For self-hosted or development instances, you may optionally override
the default base URL:

```bash
export CORKBOARD_URL="https://your-instance.example.com"  # defaults to https://corkboard.wiki
```

**Getting a token:** open Corkboard, go to **Settings → API tokens**,
and create a personal access token.  The token is a `cb_…` string — never
hardcode it in files.

## Workspaces

The API is workspace-scoped:

```
content:  {CORKBOARD_URL}/api/v1/o/{org_slug}/{ws_slug}/{path}
me:       {CORKBOARD_URL}/api/v1/me          (unscoped)
```

The old unscoped content grammar (`/api/v1/{path}`) returns **404**
(BREAKING since corkboard-app #214).

Run `me` to list your accessible workspaces:

```bash
python3 script/corkboard.py me
```

The CLI picks a workspace in this order:

1. `--workspace ORG/WS` (before the command name),
2. `CORKBOARD_WORKSPACE` (optional):

   ```bash
   export CORKBOARD_WORKSPACE="acme/main"
   ```

3. the first accessible workspace from `me`, resolved once per client.

If none of the three yields a workspace, the CLI exits with
`no accessible workspace for this token`.

## Quick Start

```bash
# Discover identity + accessible workspaces
python3 script/corkboard.py me

# List top-level pages
python3 script/corkboard.py list

# Create a page from stdin
echo "# Hello" | python3 script/corkboard.py put my/new-page --sum "first save"

# Append a section
echo "More content here." | python3 script/corkboard.py append my/new-page --sum "add section"

# Search
python3 script/corkboard.py search "hello"

# View a page
python3 script/corkboard.py get my/new-page
```

The full command reference is in [SKILL.md](SKILL.md).

## Zero Dependencies

This skill uses only the **Python 3 standard library** (`urllib`,
`json`, `argparse`).  Python 3.11 or later.  No pip packages, no
SDKs, no MCP client libraries, no third-party imports of any kind.

## MCP vs Skill

Corkboard also offers an MCP server for MCP-native clients (OAuth 2.1
flow).  This **skill** is the alternative for CLI-driven agents: a
plain `.py` file your agent shells out to.  Pick whichever fits your
workflow — both talk to the same HTTP API.

## Documentation

- [Corkboard Skill docs](https://corkboard.wiki/docs/skill) — install,
  configuration, usage, examples.
- [Corkboard](https://corkboard.wiki) — create a workspace.

## License

MIT — see [LICENSE](LICENSE).