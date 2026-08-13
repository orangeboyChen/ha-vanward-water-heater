"""Pytest fixtures: stub homeassistant + load protocol/const without executing
the package __init__.py (which uses Python 3.12 `type` syntax — local env is 3.11)."""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── Stub homeassistant.const (本地无 HA 包，纯逻辑测试不需要完整 HA) ──
_ha = types.ModuleType("homeassistant")
_ha_const = types.ModuleType("homeassistant.const")

class _Platform:
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    NUMBER = "number"
    SELECT = "select"
    SENSOR = "sensor"
    SWITCH = "switch"
    WATER_HEATER = "water_heater"

_ha_const.Platform = _Platform
sys.modules["homeassistant"] = _ha
sys.modules["homeassistant.const"] = _ha_const

# ── 手工注册包结构（不执行 __init__.py）──
CC = types.ModuleType("custom_components")
CC.__path__ = [str(ROOT / "custom_components")]
sys.modules["custom_components"] = CC

PKG = types.ModuleType("custom_components.vanward_water_heater")
PKG.__path__ = [str(ROOT / "custom_components" / "vanward_water_heater")]
sys.modules["custom_components.vanward_water_heater"] = PKG

def _load(mod_name: str) -> types.ModuleType:
    path = ROOT / "custom_components" / "vanward_water_heater" / f"{mod_name}.py"
    spec = importlib.util.spec_from_file_location(
        f"custom_components.vanward_water_heater.{mod_name}", path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

_load("const")
_load("protocol")
