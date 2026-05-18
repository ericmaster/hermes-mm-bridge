"""
Register Hermes Agent commands as Mattermost custom slash commands with /ha_ prefix.

Usage:
    python register-commands.py            # Register missing commands
    python register-commands.py --dry-run  # Preview only
    python register-commands.py --cleanup  # Remove stale registered commands
    python register-commands.py --verbose  # Show detailed output

Environment variables:
    MATTERMOST_URL            — Base URL of Mattermost server
    MATTERMOST_PAT            — Personal Access Token with manage_slash_commands permission
    MATTERMOST_TEAM_ID        — Optional; auto-resolved from user's teams if omitted
    HA_WEBHOOK_URL            — Public URL for the bridge webhook (default: http://localhost:3088/ha/webhook)
    HERMES_AGENT_PATH         — Path to hermes-agent repo (default: ~/.hermes/hermes-agent)
"""

import argparse
import logging
import os
import re
import sys
import time
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("register-commands")

HA_TRIGGER_PREFIX = "ha_"

# Default webhook URL — override via HA_WEBHOOK_URL env var
DEFAULT_WEBHOOK_URL = "http://localhost:3088/ha/webhook"


# ---------------------------------------------------------------------------
# Hermes command discovery
# ---------------------------------------------------------------------------

def _load_hermes_commands() -> list[dict]:
    """Import COMMAND_REGISTRY from the hermes-agent codebase."""
    hermes_path = os.environ.get(
        "HERMES_AGENT_PATH",
        str(Path.home() / ".hermes" / "hermes-agent"),
    )
    if hermes_path not in sys.path:
        sys.path.insert(0, hermes_path)

    try:
        from hermes_cli.commands import COMMAND_REGISTRY  # type: ignore[import-untyped]
    except ImportError:
        logger.error(
            "Cannot import COMMAND_REGISTRY. Is HERMES_AGENT_PATH (%s) correct?",
            hermes_path,
        )
        sys.exit(1)

    commands: list[dict] = []
    for cmd in COMMAND_REGISTRY:
        # Skip CLI-only commands that have no gateway config gate
        if getattr(cmd, "cli_only", False) and not getattr(cmd, "gateway_config_gate", None):
            continue

        commands.append({
            "name": cmd.name,
            "description": cmd.description,
            "aliases": list(getattr(cmd, "aliases", ())),
            "args_hint": getattr(cmd, "args_hint", ""),
            "category": getattr(cmd, "category", ""),
            "subcommands": list(getattr(cmd, "subcommands", ())),
        })

    return commands


def _scan_skills() -> list[dict]:
    """Recursively scan ~/.hermes/skills/ for SKILL.md files."""
    skills_dir = Path.home() / ".hermes" / "skills"
    if not skills_dir.exists():
        return []

    skills: list[dict] = []
    name_pattern = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,31}$")

    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        entry = skill_md.parent
        # Use the deepest directory name as the skill name
        name = entry.name
        if not name_pattern.match(name):
            continue

        # Extract description from SKILL.md frontmatter
        description = f"Run skill: {name}"
        content = skill_md.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
        if m:
            description = m.group(1).strip()

        skills.append({
            "name": name,
            "description": description,
            "category": "Skills",
            "args_hint": "[args]",
        })

    return skills


# ---------------------------------------------------------------------------
# Mattermost API helpers
# ---------------------------------------------------------------------------

def _get_team_id(client: httpx.Client, base_url: str, token: str) -> str:
    """Resolve the Mattermost team ID."""
    team_id = os.environ.get("MATTERMOST_TEAM_ID", "")
    if team_id:
        return team_id

    resp = client.get(
        f"{base_url}/api/v4/users/me/teams",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    teams = resp.json()
    if not teams:
        logger.error("User belongs to no teams. Set MATTERMOST_TEAM_ID.")
        sys.exit(1)

    tid = teams[0]["id"]
    logger.info("Auto-resolved team: %s (%s)", teams[0].get("display_name", ""), tid)
    return tid


def _list_existing_commands(
    client: httpx.Client, base_url: str, token: str, team_id: str,
) -> dict[str, str]:
    """Return dict of trigger -> command_id for existing commands (GET /api/v4/commands?team_id=...)."""
    resp = client.get(
        f"{base_url}/api/v4/commands",
        params={"team_id": team_id},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    existing: dict[str, str] = {}
    for cmd in resp.json():
        trigger = cmd.get("trigger", "")
        if trigger:
            existing[trigger] = cmd["id"]
    return existing


def _create_command(
    client: httpx.Client, base_url: str, token: str, team_id: str,
    trigger: str, display_name: str, description: str,
    hint: str, webhook_url: str,
) -> bool:
    """Create a single slash command. Returns True on success."""
    payload = {
        "team_id": team_id,
        "trigger": trigger,
        "url": webhook_url,
        "method": "P",
        "auto_complete": True,
        "auto_complete_hint": hint or "",
        "auto_complete_desc": description[:100] if description else "",
        "display_name": display_name,
    }
    try:
        resp = client.post(
            f"{base_url}/api/v4/commands",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=30,
        )
        if resp.status_code >= 400:
            logger.warning(
                "  FAILED create %s (HTTP %d): %s",
                trigger, resp.status_code, resp.text[:200],
            )
            return False
        return True
    except httpx.RequestError as exc:
        logger.warning("  NETWORK ERROR creating %s: %s", trigger, exc)
        return False


def _delete_command(
    client: httpx.Client, base_url: str, token: str, command_id: str,
) -> bool:
    """Delete a registered slash command by ID."""
    try:
        resp = client.delete(
            f"{base_url}/api/v4/commands/{command_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        return resp.status_code < 400
    except httpx.RequestError as exc:
        logger.warning("  NETWORK ERROR deleting command %s: %s", command_id, exc)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register Hermes commands as Mattermost slash commands",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no API calls")
    parser.add_argument("--verbose", action="store_true", help="Show filtered commands")
    parser.add_argument("--cleanup", action="store_true", help="Remove stale registered commands")
    args = parser.parse_args()

    # 1. Discover commands
    hermes_commands = _load_hermes_commands()
    skill_commands = _scan_skills()
    all_commands = hermes_commands + skill_commands

    if args.verbose:
        logger.info("Discovered %d Hermes commands + %d skill commands", len(hermes_commands), len(skill_commands))
        for cmd in hermes_commands:
            logger.info("  [hermes] /%s — %s", cmd["name"], cmd["description"][:60])
        for cmd in skill_commands:
            logger.info("  [skill]  /%s — %s", cmd["name"], cmd["description"][:60])

    if not all_commands:
        logger.warning("No commands discovered. Nothing to register.")
        return

    # 2. Read config
    base_url = os.environ.get("MATTERMOST_URL", "")
    token = os.environ.get("MATTERMOST_PAT", "")
    webhook_url = os.environ.get("HA_WEBHOOK_URL", DEFAULT_WEBHOOK_URL)

    if not base_url or not token:
        logger.error("MATTERMOST_URL and MATTERMOST_PAT must be set")
        sys.exit(1)

    base_url = base_url.rstrip("/")

    # 3. Build triggers
    triggers_to_create: list[dict] = []
    for cmd in all_commands:
        triggers_to_create.append({
            "trigger": f"{HA_TRIGGER_PREFIX}{cmd['name']}",
            "display_name": f"Hermes: /{cmd['name']}",
            "description": cmd["description"],
            "hint": cmd.get("args_hint", ""),
        })

    if args.dry_run:
        logger.info("=== DRY RUN ===")
        logger.info("Would register %d commands:", len(triggers_to_create))
        for t in triggers_to_create:
            logger.info("  /%s → %s", t["trigger"], t["description"][:80])
        return

    # 4. Connect to Mattermost API
    with httpx.Client() as client:
        try:
            team_id = _get_team_id(client, base_url, token)
            existing = _list_existing_commands(client, base_url, token, team_id)
        except (httpx.RequestError, KeyError, IndexError) as exc:
            logger.error("Failed to connect to Mattermost API: %s", exc)
            sys.exit(1)

        existing_triggers = set(existing.keys())

        # 5. Create missing commands with rate limiting
        new_count = 0
        already_count = 0
        RATE_LIMIT_DELAY = 0.5  # seconds between POSTs to avoid rate limiting

        for idx, tc in enumerate(triggers_to_create):
            if tc["trigger"] in existing_triggers:
                already_count += 1
                continue

            # Rate limiting: delay between POSTs (skip delay for first request)
            if idx > 0 and new_count > 0:
                time.sleep(RATE_LIMIT_DELAY)

            ok = _create_command(
                client, base_url, token, team_id,
                trigger=tc["trigger"],
                display_name=tc["display_name"],
                description=tc["description"],
                hint=tc["hint"],
                webhook_url=webhook_url,
            )
            if ok:
                new_count += 1
                if args.verbose:
                    logger.info("  CREATED /%s", tc["trigger"])

        logger.info(
            "Slash commands: %d new, %d already present (total %d)",
            new_count, already_count, len(triggers_to_create),
        )

        # 6. Cleanup stale commands (optional)
        if args.cleanup:
            valid_triggers = {t["trigger"] for t in triggers_to_create}
            stale = {
                trigger: cid
                for trigger, cid in existing.items()
                if trigger.startswith(HA_TRIGGER_PREFIX) and trigger not in valid_triggers
            }
            deleted = 0
            for trigger, cid in stale.items():
                if _delete_command(client, base_url, token, cid):
                    deleted += 1
                    logger.info("  DELETED /%s (stale)", trigger)

            if not stale:
                logger.info("No stale commands to clean up.")
            else:
                logger.info("Cleaned up %d/%d stale command(s)", deleted, len(stale))


if __name__ == "__main__":
    main()
