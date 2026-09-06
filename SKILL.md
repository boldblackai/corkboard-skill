---
name: corkboard
description: Use when the user wants to read/write Corkboard wikis via the HTTP API.
version: "1.0.0"
license: MIT
---

# Corkboard Skill

A stdlib-only Python CLI that reads and writes Corkboard wikis over the
**HTTP API v1** with an API token.  Designed for CLI-driven agents
(Hermes, Claude Code, Codex, …) — an alternative to MCP for
script-and-shell workflows.

## Setup

1. **Get an API token.**  Open your Corkboard workspace, go to
   **Settings → API tokens**, and create a personal access token
   (`cb_…`).  The token is bound to your workspace and used as a
   Bearer token.

2. **Set environment variables** in your agent's shell profile:

   ```bash
   export CORKBOARD_URL="https://your-workspace.corkboard.wiki"
   export CORKBOARD_TOKEN="cb_your_token_here"
   ```

   Both are required — the CLI will exit with a clear error if either
   is missing.

3. **Install the skill.**  Clone or curl the skill into your agent's
   skills directory (see [README.md](README.md) for one-liners).

4. **Verify.**  `python3 script/corkboard.py list` should print your
   workspace's top-level pages.

## Command Reference

Invoke every command through the entrypoint:

```
python3 script/corkboard.py <command> [options]
```

### Pages

| Command | Arguments | Description |
|---------|-----------|-------------|
| `get` | `<page>` | Fetch a page by id (JSON to stdout). |
| `put` | `<page>` [`--file PATH` \| `--text TEXT`] [`--sum MSG`] | Create or replace a page. Reads body from `--file`, `--text`, or stdin. Uses CAS (If-Match) to avoid overwriting concurrent edits. |
| `append` | `<page>` [`--file PATH` \| `--text TEXT`] [`--sum MSG`] | Append text to the end of a page. |
| `delete` | `<page>` [`--sum MSG`] | Delete a page. |
| `edit` | `<page>` (`--old OLD --new NEW` …) [`--edits FILE`] [`--sum MSG`] | Surgical edit. Fetch-mutate-put_cas flow: each `--old` must match exactly once in the current body; pairs are applied sequentially. Use `--edits` for a tab-separated file (`old\tnew` per line). |
| `insert` | `<page>` (`--under H` \| `--after L` \| `--before L`) [`--file PATH` \| `--text TEXT`] [`--sum MSG`] | Insert content at an anchor position. `--under` places content under a Markdown heading (ends at next same-or-higher-level heading). `--after` and `--before` target an exact line. The anchor must match exactly one line. |
| `find` | `<page>` `<pattern>` [`-E`] [`-i`] | Search a page body. `-E` enables extended regex; `-i` makes the search case-insensitive. |
| `move` | `<src>` `<dst>` [`--sum MSG`] | Move/rename a page. Server-side: backlinks are rewritten and history is preserved. |
| `links` | `<page>` | List outgoing wiki-links from a page. |
| `backlinks` | `<page>` | List pages that link to this page. |
| `revisions` | `<page>` | List revision history for a page. |
| `revision-show` | `<page>` `<rev>` | Show a specific revision's content. |

### Collections & Search

| Command | Arguments | Description |
|---------|-----------|-------------|
| `list` | [`--ns NS`] [`--depth N`] | List pages in a namespace. `--depth 0` = full recursion. |
| `search` | `<query>` [`--ns NS`] | Full-text search across pages. |
| `sitemap` | [`--ns NS`] [`--depth N`] | Render an ASCII tree of the page hierarchy. |
| `wanted` | *(none)* | List pages referenced by internal links but not yet created. |
| `orphans` | *(none)* | List pages with no inbound links. |
| `semantic` | `<query>` | Semantic (vector) search. On Free plans this may be unavailable (exits gracefully with a message). |

### Media

| Command | Arguments | Description |
|---------|-----------|-------------|
| `media-upload` | `<file>` `<ns>` `<name>` [`--no-overwrite`] | Upload a file. Tries raw binary PUT first; falls back to base64 JSON on content-type rejection. |
| `media-get` | `<id>` [`-o PATH`] | Download a media file. Writes to `-o` path or stdout. |
| `media-list` | [`--ns NS`] | List media files, optionally filtered by namespace. |
| `media-delete` | `<id>` | Delete a media file. |
| `media-move` | `<src>` `<dst>` | Move/rename a media file. |
| `media-orphans` | *(none)* | List media files not referenced by any page. |
| `media-usage` | `<id>` | Show which pages reference a media file. |

### Common Flags

| Flag | Applies to | Meaning |
|------|-----------|---------|
| `--sum MSG` | `put`, `append`, `delete`, `edit`, `insert`, `move` | Edit summary recorded in the page revision. |
| `--file PATH` / `-F` | `put`, `append`, `insert` | Read body from a file (mutually exclusive with `--text`). |
| `--text TEXT` / `-T` | `put`, `append`, `insert` | Inline body text (mutually exclusive with `--file`). |

When neither `--file` nor `--text` is given, the body is read from **stdin**.

## Conventions

### Page IDs and Linking

Corkboard page IDs use `/`-separated paths (e.g. `projects/alpha`).
Wiki-links use GFM syntax: `[link text](page_id)`.  By convention:

- **Absolute-link default.**  `[Projects](projects/start)` links to the
  root-level `projects/start`, regardless of the current page's
  namespace.  This keeps the link graph simple and predictable.

- **Dense link graph.**  Every page should link to at least one other
  page and be linked from another.  Use the `wanted` and `orphans`
  commands regularly to find gaps.

- **Self-describing pages.**  Every page should open with a level-1
  heading (`# Title`) and a one-paragraph summary.  This makes search
  results and link previews useful.

- **Shallow namespaces.**  Prefer one or two levels of nesting
  (`projects/`, `projects/reports`) over deep hierarchies.

### Edit Safety

All mutating page commands use **optimistic concurrency (CAS):**

1. Fetch the current revision of the page.
2. Apply the mutation locally.
3. PUT with `If-Match: "<revision>"`.
4. On HTTP 412 (conflict), re-fetch once and retry.
5. On a second 412, fail with `CONFLICT`.

The `edit` command additionally enforces **unique-match assertions:**
every `--old` string must appear exactly once in the page body.  This
prevents accidental or ambiguous replacements.  The `insert` command
requires the anchor line to match exactly one line.

### Gardening

Keep the workspace healthy with periodic sweeps:

```
python3 script/corkboard.py wanted         # broken internal links
python3 script/corkboard.py orphans        # pages with no inbound links
python3 script/corkboard.py media-orphans  # unreferenced media files
```

**Link-health check.**  After editing a page, verify its links:

```
python3 script/corkboard.py links <page>   # get the server-side link list
```

Diff the output against the wiki-links in the page body to catch typos
and dangling references.  There is no dedicated link-health endpoint;
the CLI-side equivalent is `links` + manual diff.

### Page-Naming Hygiene

- Use lowercase, hyphen-separated words (`getting-started`, not
  `GettingStarted` or `getting_started`).
- Start pages are named `start` within their namespace.
- Avoid special characters except `/` (namespace separator) and `-`
  (word separator).

## Zero Dependencies

This skill uses only the Python 3 standard library (`urllib`, `json`,
`argparse`, `http.server` for testing).  No pip packages, no SDKs, no
MCP client libraries.  Python 3.11+.

## Product Docs

- [Corkboard Skill documentation](https://corkboard.wiki/docs/skill) —
  install, configuration, and usage.
- [Corkboard workspace](https://corkboard.wiki) — create an account and
  workspace.