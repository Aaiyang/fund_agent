"""This file contains the prompts for the agent."""

import os
from typing import Optional

from app.core.config import settings
from app.utils.clock import business_now

_PROMPTS_DIR = os.path.dirname(__file__)

# Read templates once at module load — no file I/O per request
with open(os.path.join(_PROMPTS_DIR, "system.md"), "r") as _f:
    _SYSTEM_PROMPT_TEMPLATE = _f.read()

with open(os.path.join(_PROMPTS_DIR, "session_title.md"), "r") as _f:
    SESSION_TITLE_PROMPT = _f.read()


def load_system_prompt(username: Optional[str] = None, **kwargs):
    """Load the system prompt from the cached template."""
    user_context = f"# User\nYou are talking to {username}.\n" if username else ""
    return _SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=settings.PROJECT_NAME + " Agent",
        # The market's clock, not the host's: the host zone would tell the
        # model the wrong hour and therefore the wrong trading session.
        current_date_and_time=business_now().strftime("%Y-%m-%d %H:%M:%S %Z"),
        user_context=user_context,
        **kwargs,
    )
