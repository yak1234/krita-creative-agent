# SPDX-FileCopyrightText: 2026 Yakub Rabiutheen <yakub.rabiutheen@gmail.com>
# SPDX-License-Identifier: GPL-3.0-or-later
"""The names of the resources material stamps make (material_stamp.py) and how brush lists leave them out.

A Krita-brush stamp makes a brush tip and a preset for each variant of each material it stamps ("Agent stamp <material>
<hash> t0 r0 s1"). They belong to the stamp, not to the painter's brush choices, so brush lists and the capability manifest
hide them. Hiding happens BEFORE any limit is applied and the total counts only visible presets: with hundreds of them a
list cut at a limit would otherwise lose real brushes.
"""
PREFIX = 'Agent stamp'


def is_stamp_resource(name):
    return isinstance(name, str) and name.startswith(PREFIX + ' ')


def list_presets(names, filter_str='', limit=None, exclude_prefix=''):
    """(brushes, total): the sorted preset names containing `filter_str`, without those starting with `exclude_prefix`, at
    most `limit` of them; total is how many presets are visible at all."""
    visible = [name for name in sorted(names) if not (exclude_prefix and name.startswith(exclude_prefix))]
    found = [name for name in visible if filter_str.lower() in name.lower()]
    return (found if limit is None else found[:limit]), len(visible)
