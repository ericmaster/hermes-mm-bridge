"""
Hermes-Mattermost Bridge — FastAPI webhook endpoint.

Receives Mattermost custom slash commands with prefix /ha_ and echoes
them back as !commands for the Hermes gateway to process.
"""

import logging
import os
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import Config, load_config, setup_logging

logger = logging.getLogger(__name__)

cfg: Config = load_config()
setup_logging(cfg)

app = FastAPI(title="Hermes-Mattermost Bridge", version="1.0.0")

COMMAND_PREFIX = "/ha_"
HERMES_PREFIX = "/"


def _validate_token(request: Request) -> bool:
    """Validate the bearer token from Mattermost. Skip if not configured."""
    if not cfg.hermes_token:
        return True
    auth = request.headers.get("Authorization", "")
    return auth == f"Token {cfg.hermes_token}" or auth == f"Bearer {cfg.hermes_token}"


def _strip_prefix(command: str) -> str | None:
    """Strip /ha_ prefix from a command name. Returns None if prefix mismatches."""
    cmd = command.strip().lower()
    if not cmd.startswith(COMMAND_PREFIX):
        return None
    return cmd[len(COMMAND_PREFIX):]


@app.post("/ha/webhook")
async def receive_slash_command(request: Request):
    """Receive a Mattermost slash command callback and echo it as !command."""
    source_ip = request.client.host if request.client else "unknown"

    if not _validate_token(request):
        logger.warning(f"Invalid token from {source_ip}")
        return JSONResponse(
            status_code=403,
            content={"text": "Invalid token", "response_type": "ephemeral"},
        )

    form = await request.form()
    command = form.get("command", "")
    text = form.get("text", "").strip()
    channel_id = form.get("channel_id", "")
    user_id = form.get("user_id", "")
    user_name = form.get("user_name", "")

    # Strip /ha_ prefix to get the Hermes command name
    hermes_cmd = _strip_prefix(command)

    if not hermes_cmd:
        logger.info(f"Unknown command from {user_name} ({user_id}): {command}")
        return JSONResponse(
            content={
                "text": f"Unknown command: {command}. Use /ha_ prefix (e.g. /ha_help)",
                "response_type": "ephemeral",
            },
        )

    # Build echo response: !<command> [args]
    response_text = f"{HERMES_PREFIX}{hermes_cmd}{(' ' + text) if text else ''}"

    logger.info(
        f"CMD | user={user_name}({user_id}) | channel={channel_id} | "
        f"cmd={hermes_cmd} | args={text!r} | echo={response_text!r}"
    )

    return JSONResponse(
        content={
            "response_type": "in_channel",
            "text": response_text,
        },
    )


@app.get("/ha/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=cfg.port,
        log_level="info",
    )
