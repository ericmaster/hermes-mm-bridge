# Hermes-Mattermost Bridge

> [!IMPORTANT]
> **AGENT.MD CRITICAL RULES:**
> **No Fluff:** Minimum characters. Concise but 100% complete.
> **Current State Only:** Keep this file current. Do not use AGENTS.md, specs, or other
> non-ADR docs as changelogs, timelines, release notes, or historical change logs. Only
> `docs/adr/` retains historical decision rationale or superseded choices.
> **ADR Lifecycle:** Before release, ADRs may be squashed to retain the latest decision; after
> release, preserve published ADRs and use a new superseding ADR.
> **Live Sync:** Always keep AGENTS.md file updated with the latest relevant code changes after code is updated.
> **Context Hygiene:** Apply the `context-hygiene` skill before writing or revising any
> documentation or spec; keep each fact in its SSOT and link instead of repeating it.

> [!WARNING]
> **Avoid Redundant Documentation**
> AGENTS.md is the **Single Source of Truth**. Do NOT create separate MAINTENANCE.md, ARCHITECTURE.md, or other documentation files that duplicate information here.
> When you need development guidance, update README.md with quick refs and links back to AGENTS.md sections.

## Purpose

Bridge that registers Hermes Agent commands as Mattermost custom slash commands (prefixed `/ha_`) and forwards them to the Hermes gateway via in-channel echo.

## Project Structure

```
~/hermes-mm-bridge/
├── AGENTS.md           # Full project context (READ THIS FIRST)
├── CLAUDE.md           # This file
├── main.py             # FastAPI webhook endpoint (implement me)
├── config.py           # Config dataclass + loader (implement me)
├── register-commands.py# Register Hermes commands as MM slash commands (implement me)
├── requirements.txt    # Python dependencies (implement me)
├── docker-compose.yml  # Container deployment (implement me)
└── Dockerfile          # Container build (implement me)
```

## Key Implementation Notes

- The webhook is a **pure echo** — receives `/ha_command args`, responds `{"response_type": "in_channel", "text": "!command args"}`
- register-commands.py needs to import from `~/.hermes/hermes-agent/hermes_cli/commands.py` and scan `~/.hermes/skills/`
- Mattermost API calls use httpx with Bearer token auth
- Server runs on port 3088

## Architecture

After receiving /ha_status, the bridge responds with direct echo in the channel. The `!` workaround has been reverted:
- `command_prefix` in `base.py` is now `"/"` (previously `"!"`)
- Bridge responds with `/{cmd}` instead of `!{cmd}`

```
Mattermost Client
  │  /ha_status arg1 arg2
  ▼
Mattermost Server (mmchat.nimblersoft.com)
  │  POST /ha/webhook (form-data)
  ▼
FastAPI endpoint (hermes-mm-bridge)
  │  strip "ha_" prefix → echo "/status arg1 arg2"
  │  {"response_type": "in_channel", "text": "/status arg1 arg2"}
  ▼
Hermes Gateway (WebSocket, command_prefix="/")
  │  message starts with "/" → processes as command
  ▼
Hermes responde en el canal
```

## Components

### 1. `register-commands.py` — One-shot registration script

- Imports `COMMAND_REGISTRY` from `~/.hermes/hermes-agent/hermes_cli/commands.py`
- Scans `~/.hermes/skills/` for skills invocable as commands
- Filters gateway-available commands (excludes `cli_only=True` without `gateway_config_gate`)
- For each command: `POST /api/v4/commands` to Mattermost
  - `trigger`: `ha_{name}` (e.g. `ha_status`, `ha_help`)
  - `url`: `https://wh-api.nimblersoft.com/ha/webhook`
  - `method`: `P` (POST)
  - `auto_complete`: `true`
  - `auto_complete_hint`: from `CommandDef.args_hint`
  - `auto_complete_desc`: from `CommandDef.description`
  - `display_name`: `Hermes: /{name}`
- Idempotent: compares against `GET /teams/{team_id}/commands`
- Cap: 50 commands
- Flags: `--dry-run`, `--cleanup`

### 2. `main.py` — Webhook endpoint

- `POST /ha/webhook` — receives slash command callback
  - Form-data: `command`, `text`, `channel_id`, `response_url`, `user_id`, `token`
  - Validates token against config (optional)
  - Extracts command: `/ha_status` → strip `/ha_` → `status`
  - Replies: `{"response_type": "in_channel", "text": "!status [args]"}`
  - Log: timestamp, command, user, channel
- `GET /ha/health` — health check

### 3. `config.py` — Config

- `HERMES_TOKEN` — webhook auth token (optional, from env var or Infisical)
- Server port (default: 3088)

## Commands to Register (~30)

Based on `COMMAND_REGISTRY` in `~/.hermes/hermes-agent/hermes_cli/commands.py`.
Filter by `not cmd.cli_only or cmd.gateway_config_gate`.

## Skills as Commands

In addition to built-in commands, scan `~/.hermes/skills/` for skills with an invocable command name. Each skill whose name is a legitimate command is registered as `/ha_{skill_name}`.

## Mattermost API Reference

- `POST /api/v4/commands` — create slash command
  - Body: `{trigger, url, method, auto_complete, auto_complete_hint, auto_complete_desc, display_name, team_id, icon_url}`
  - Auth: `Authorization: Bearer <token>` (bot token with `manage_slash_commands`)
- `GET /api/v4/teams/{team_id}/commands` — list for dedup
- `DELETE /api/v4/commands/{command_id}` — delete
- Team ID: from `GET /api/v4/users/me/teams`
