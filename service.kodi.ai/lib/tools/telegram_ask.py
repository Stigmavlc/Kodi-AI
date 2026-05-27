# service.kodi.ai/lib/tools/telegram_ask.py
"""ask_user — triggers reasoner pause + Telegram inline keyboard.

The tool itself just returns the NEEDS_USER marker. The reasoner detects
.requires_user_confirmation=True and serializes state + sends Telegram via
lib/telegram/bot.py.

Spec: §1.7.
"""
from . import tool, ToolResult


@tool(
    name="ask_user",
    description="Ask the user a yes/no/option question via Telegram. Pauses the agent until the user replies.",
    schema={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"},
                        "default": ["Yes", "No"]},
        },
        "required": ["question"],
    },
    tier="confirm",
)
def ask_user(question: str, options: list[str] | None = None) -> ToolResult:
    return ToolResult(
        success=False, requested=f"ask_user(...)", output={
            "question": question, "options": options or ["Yes", "No"],
        },
        actual_state_after=None, error="NEEDS_USER",
        snapshot_id=None, cost_seconds=0.0,
    )


ask_user.requires_user_confirmation = True
