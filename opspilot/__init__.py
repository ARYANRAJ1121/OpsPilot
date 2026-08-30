"""OpsPilot — agentic incident-response system ($0 Slack + Groq compatible)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("opspilot")
except PackageNotFoundError:  # pragma: no cover - editable / source tree
    __version__ = "1.0.1"

__all__ = ["__version__"]
