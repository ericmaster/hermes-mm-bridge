# Hermes-Mattermost Bridge

A lightweight FastAPI bridge that exposes [Hermes Agent](https://github.com/) commands as native Mattermost slash commands.

It registers each Hermes command as a Mattermost custom slash command (prefixed `/ha_`) and forwards invocations back into the channel as a `/command` echo, which the Hermes gateway then picks up and processes.

No bot tokens. No outbound Mattermost API calls at runtime. Pure echo.

## How it works

```
Mattermost client
  │  /ha_status arg1 arg2
  ▼
Mattermost server
  │  POST /ha/webhook  (form-data)
  ▼
hermes-mm-bridge  (FastAPI, port 3088)
  │  strip "ha_" prefix → "/status arg1 arg2"
  │  reply: {"response_type": "in_channel", "text": "/status arg1 arg2"}
  ▼
Hermes gateway  (listening in the channel)
  │  message starts with "/" → handled as a command
  ▼
Hermes replies in the channel
```

The bridge does two things:

1. **One-shot registration** (`register-commands.py`) — discovers Hermes commands and skills, then registers each one in Mattermost via the [Slash Commands API](https://api.mattermost.com/#tag/commands).
2. **Webhook echo** (`main.py`) — receives Mattermost slash command callbacks and responds with an in-channel message the Hermes gateway can react to.

## Endpoints

| Method | Path           | Purpose                          |
| ------ | -------------- | -------------------------------- |
| POST   | `/ha/webhook`  | Mattermost slash command callback |
| GET    | `/ha/health`   | Health check                     |

## Requirements

- Python 3.11+
- A Mattermost server you can administer
- A Mattermost Personal Access Token with the `manage_slash_commands` permission
- A reachable Hermes Agent gateway connected to the same Mattermost channel(s)

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/ericmaster/hermes-mm-bridge.git
cd hermes-mm-bridge
cp .env.example .env
# Edit .env with your values
```

### 2. Run with Docker Compose

```bash
docker compose up -d
```

The webhook listens on port `3088`. Expose it publicly (behind a reverse proxy / TLS) so Mattermost can reach it.

### 3. Register commands

```bash
python register-commands.py --dry-run   # preview
python register-commands.py             # apply
python register-commands.py --cleanup   # remove all /ha_* commands
```

The script is idempotent — re-running it only adds missing commands.

## Configuration

Environment variables (see [`.env.example`](.env.example)):

| Variable                | Required | Default | Description                                                              |
| ----------------------- | -------- | ------- | ------------------------------------------------------------------------ |
| `HERMES_MM_BRIDGE_PORT` | no       | `3088`  | Port the FastAPI app listens on                                          |
| `HERMES_TOKEN`          | no       | _empty_ | If set, validates `Authorization: Token <value>` on incoming webhooks    |
| `LOG_DIR`               | no       | `./logs`| Directory for `bridge.log`                                               |
| `MATTERMOST_URL`        | yes\*    | _empty_ | Base URL of your Mattermost server (\*used by `register-commands.py`)    |
| `MATTERMOST_PAT`        | yes\*    | _empty_ | Personal Access Token with `manage_slash_commands` (\*registration only) |

Secrets can also be loaded at container start from an external secret manager — see [`entrypoint.sh`](entrypoint.sh).

## Project layout

```
.
├── main.py                 # FastAPI webhook endpoint
├── config.py               # Config dataclass + env loader
├── register-commands.py    # Discovers + registers commands in Mattermost
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── AGENTS.md               # Single source of truth for contributors / AI agents
└── README.md
```

## Contributing

Project context, architecture details, and the contributor playbook live in [AGENTS.md](AGENTS.md). Read it before opening a PR.

## License

MIT
