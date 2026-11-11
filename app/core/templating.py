from __future__ import annotations

from datetime import datetime, timezone

from fastapi.templating import Jinja2Templates

from app.core.settings import PROJECT_ROOT


def _as_datetime(value):
    if hasattr(value, "strftime"):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed
    return None


def gw_time(value: datetime | str | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Render a timestamp as UTC to the minute, with an em dash for empty values."""
    if value is None or value == "":
        return "—"
    parsed = _as_datetime(value)
    if parsed is None:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime(fmt)


def gw_iso(value: datetime | str | None) -> str:
    """Full ISO timestamp for title attributes; empty string when missing."""
    if value is None or value == "":
        return ""
    parsed = _as_datetime(value)
    if parsed is None:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def iteration_label(value: int | None) -> str:
    if not value:
        return "—"
    return f"v{int(value):04d}"


def build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))
    templates.env.filters["gw_time"] = gw_time
    templates.env.filters["gw_iso"] = gw_iso
    templates.env.filters["iteration_label"] = iteration_label
    return templates
