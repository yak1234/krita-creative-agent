"""Semantic controls for Krita's misleadingly named sensor properties."""
import math

CONTROL_MAP = {
    'pigment': ('ColorRateValue', 'PressureColorRate'),
    'blend': ('SmudgeRateValue', 'PressureSmudgeRate'),
    'scatter': ('ScatterValue', 'PressureScatter'),
    'pigment_dynamics': ('ColorRateUseCurve', None),
    'blend_dynamics': ('SmudgeRateUseCurve', None),
}

def control_changes(controls, available):
    if not isinstance(controls, dict) or not controls:
        raise ValueError('controls must be a nonempty object')
    changes = {}
    for name, value in controls.items():
        if name not in CONTROL_MAP:
            raise ValueError('Unknown brush control: ' + name)
        prop, enable = CONTROL_MAP[name]
        if prop not in available or (enable and enable not in available):
            raise ValueError('Current preset does not support: ' + name)
        if name.endswith('_dynamics'):
            if not isinstance(value, bool):
                raise ValueError(name + ' must be boolean')
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(name + ' must be between 0 and 1')
        changes[prop] = value
        if enable:
            # PressureColorRate enables pigment itself, not pressure modulation.
            changes[enable] = True
    return changes
