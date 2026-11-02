# Copy this file to config.py and fill in your own values.
# config.py is listed in .gitignore, so your real password and keys are never uploaded to GitHub.

ADMIN_PASSWORD = "change-me"
SECRET_KEY = "change-this-to-a-long-random-string"

# Which AI reads result screenshots: "gemini" or "anthropic".
# The AI scan is optional: manual entry, quick add and pasting a result work without any key.
AI_PROVIDER = "gemini"

GEMINI_API_KEY = "PASTE-YOUR-API-KEY-HERE"
GEMINI_MODEL = "gemini-3.8-flash"
GEMINI_FALLBACK_MODELS = ["gemini-3.5-flash-lite"]

ANTHROPIC_API_KEY = "PASTE-YOUR-API-KEY-HERE"
AI_MODEL = "claude-sonnet-4-6"
