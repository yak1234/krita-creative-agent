"""How heavy a painting is for Krita, and why, from layer metadata only (never pixels): every observation carries it
(creative_tools._creative_observe), the painter is told when it rises (extensions/painting-weight.ts) and the artist
once per chat. Pure Python: records come from `records(doc)`, tests pass their own.

Measured on new_moscow_finished.kra (2026-10-18): 147 groups each caching a projection, 92 paint layers and 10 live
filter masks (a wavelet noise reducer among them) made one observe take 909 s and Krita reach 9 GB."""

AGENT_GROUP = 'Creative Agent ·'
# Filters that cost seconds per megapixel and rerun on every recomposite while they live in a mask.
EXPENSIVE = ('waveletnoisereducer', 'gaussiannoisereducer', 'oilpaint', 'kuwahara', 'unsharp', 'lens blur')
FILTER_NAMES = {'waveletnoisereducer': 'wavelet noise reducer', 'gaussiannoisereducer': 'gaussian noise reducer', 'oilpaint': 'oil paint',
                'kuwahara': 'kuwahara', 'unsharp': 'unsharp mask', 'lens blur': 'lens blur'}
TOO_HEAVY_MB, HEAVY_MB = 6000, 2500
LARGE_CANVAS = 8_000_000          # pixels: an expensive filter mask on a canvas this size stalls every refresh
MANY_GROUPS, MANY_LEFTOVERS = 60, 30
PIXEL_KINDS = ('paintlayer', 'filtermask', 'transparencymask', 'filterlayer', 'clonelayer')


def _area(bounds, width, height):
    x, y, w, h = bounds
    return max(0, min(x + w, width) - max(x, 0)) * max(0, min(y + h, height) - max(y, 0))


def weight(rows, width, height):
    """rows: dicts with type, name, visible (shown, ancestors included), agent (inside an agent group), bounds, filter."""
    groups = [r for r in rows if r['type'] == 'grouplayer']
    masks = [r for r in rows if r['type'] == 'filtermask']
    expensive = [r['filter'] for r in masks if r['visible'] and r['filter'] in EXPENSIVE]
    leftovers = [r for r in rows if r['agent'] and not r['visible'] and r['type'] != 'grouplayer']
    # Visible pixel layers hold their tiles; visible groups hold a cached projection. An upper estimate: Krita stores
    # only tiles with paint.
    group_mb = sum(_area(r['bounds'], width, height) for r in groups if r['visible']) * 4 / 1e6
    estimated = group_mb + sum(_area(r['bounds'], width, height) for r in rows if r['visible'] and r['type'] in PIXEL_KINDS) * 4 / 1e6
    large = width * height > LARGE_CANVAS
    level = ('too_heavy' if estimated > TOO_HEAVY_MB or (expensive and large)
             else 'heavy' if estimated > HEAVY_MB or len(groups) > MANY_GROUPS or len(leftovers) > MANY_LEFTOVERS else 'ok')
    reasons, fixes = [], []
    if level != 'ok':
        if expensive:
            names = ', '.join(dict.fromkeys(FILTER_NAMES.get(f, f) for f in expensive))
            reasons.append('%d live filter masks (%s) recompute on every refresh' % (len([m for m in masks if m['visible']]), names))
            fixes.append('bake_filters')
        if len(groups) > MANY_GROUPS or estimated > HEAVY_MB:
            reasons.append('%d groups each cache a projection (about %d MB)' % (len(groups), round(group_mb)))
            fixes.append('merge_kept')
        if len(leftovers) > MANY_LEFTOVERS:
            reasons.append('%d hidden agent layers left over' % len(leftovers))
            fixes.append('tidy')
        reasons.append('about %d MB estimated in memory' % round(estimated))
    return {'nodes': len(rows), 'groups': len(groups), 'paint_layers': len([r for r in rows if r['type'] == 'paintlayer']),
            'filter_masks': len(masks), 'expensive_filters': expensive, 'hidden_agent_layers': len(leftovers),
            'estimated_mb': round(estimated), 'level': level, 'reasons': reasons, 'fixes': fixes}


def records(doc):
    """The rows weight() reads, from a Krita document: one walk, metadata only."""
    rows = []
    def visit(node, shown, agent):
        for child in node.childNodes():
            kind = child.type()
            visible = shown and child.visible()
            inside = agent or (kind == 'grouplayer' and child.name().startswith(AGENT_GROUP))
            rect = child.bounds()
            krita_filter = child.filter() if kind == 'filtermask' and hasattr(child, 'filter') else None
            rows.append({'type': kind, 'name': child.name(), 'visible': visible, 'agent': inside,
                         'bounds': (rect.x(), rect.y(), rect.width(), rect.height()),
                         'filter': krita_filter.name() if krita_filter is not None else None})
            visit(child, visible, inside)
    visit(doc.rootNode(), True, False)
    return rows
