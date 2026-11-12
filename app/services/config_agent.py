from __future__ import annotations

# Compatibility layer: callers keep importing from config_agent, while the
# actual read/validate/atomic-write logic lives in app_config.
from app.services.app_config import read_agent, write_agent

__all__ = ["read_agent", "write_agent"]
