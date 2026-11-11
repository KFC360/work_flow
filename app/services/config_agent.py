from __future__ import annotations

import os
from pathlib import Path

import yaml

from app.core.settings import get_settings

ALLOWED = {"opencode", "claude"}


def read_agent() -> str | None:
    path = get_settings().config_yaml_path
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    agent = data.get("agent")
    if agent in ALLOWED:
        return agent
    return None


def write_agent(agent: str) -> None:
    if agent not in ALLOWED:
        raise ValueError("invalid agent")
    path = get_settings().config_yaml_path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".yaml.tmp")
    content = yaml.safe_dump({"agent": agent}, allow_unicode=True, sort_keys=False)
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
