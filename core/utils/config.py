import yaml
from pathlib import Path
from typing import Dict


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge override into base without mutating either."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml(path: str) -> Dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_config(*paths: str) -> Dict:
    """Load and deep-merge multiple YAML config files left-to-right."""
    result: Dict = {}
    for path in paths:
        result = _deep_merge(result, load_yaml(path))
    return result
