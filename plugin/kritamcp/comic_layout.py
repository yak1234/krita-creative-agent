"""Comic page layouts: panels from rows of relative heights, each with relative column widths.

The format follows Manga Panel Creator (MIT, Alaxus-Megas): a row has a height weight and its
own list of column weights, so `{rows: [1, 1], cols: [[1, 1], [1]]}` is two panels over one.
Weights are normalised per row; margin, gutter and border are pixels. Panels are numbered
P1…Pn in reading order: rows top to bottom, columns left to right, or right to left for manga.

Pure Python with no Krita import: the comic_page operation, the panel's layout picker and the
tests all use `panels()`.
"""
from .creative_validation import color, fields, numeric

LAYOUT_FIELDS = ('preset', 'rows', 'cols', 'margin', 'gutter', 'border', 'reading', 'page_color', 'border_color')
PRESETS = {
    'single': {'rows': [1], 'cols': [[1]]},
    'grid-2x2': {'rows': [1, 1], 'cols': [[1, 1], [1, 1]]},
    'grid-2x3': {'rows': [1, 1, 1], 'cols': [[1, 1], [1, 1], [1, 1]]},
    'grid-2x4': {'rows': [1, 1, 1, 1], 'cols': [[1, 1], [1, 1], [1, 1], [1, 1]]},
    'manga-3-tier': {'rows': [1, 1.2, 1], 'cols': [[1, 1], [1], [1.4, 1]]},
    'splash-strip': {'rows': [2.2, 1], 'cols': [[1], [1, 1, 1]]},
    'two-plus-one': {'rows': [1, 1], 'cols': [[1, 1], [1]]},
    'four-strip': {'rows': [1], 'cols': [[1, 1, 1, 1]]},
}
DEFAULTS = {'margin': 48, 'gutter': 24, 'border': 6, 'reading': 'ltr', 'page_color': '#ffffff', 'border_color': '#000000'}
MAX_PANELS = 24
MIN_SIDE = 32


def resolve(layout):
    """The layout with its preset expanded and defaults filled in; raises ValueError if invalid."""
    fields(layout, LAYOUT_FIELDS)
    if 'preset' in layout:
        if layout['preset'] not in PRESETS:
            raise ValueError('preset must be one of: ' + ', '.join(PRESETS))
        if 'rows' in layout or 'cols' in layout:
            raise ValueError('Give a preset or rows and cols, not both.')
    elif 'rows' not in layout or 'cols' not in layout:
        raise ValueError('Give a preset, or rows (relative heights) and cols (relative widths per row).')
    full = dict(DEFAULTS, **PRESETS.get(layout.get('preset'), {}), **{k: v for k, v in layout.items() if k != 'preset'})
    rows, cols = full['rows'], full['cols']
    if not isinstance(rows, list) or not rows or not isinstance(cols, list) or len(cols) != len(rows):
        raise ValueError('rows is a list of heights and cols has one list of widths per row.')
    for value in rows:
        numeric(value, 'row height', 0.05, 100)
    for row in cols:
        if not isinstance(row, list) or not row:
            raise ValueError('Each row in cols is a nonempty list of relative widths.')
        for value in row:
            numeric(value, 'column width', 0.05, 100)
    if sum(len(row) for row in cols) > MAX_PANELS:
        raise ValueError('A page holds at most %d panels.' % MAX_PANELS)
    numeric(full['margin'], 'margin', 0, 2000)
    numeric(full['gutter'], 'gutter', 0, 1000)
    numeric(full['border'], 'border', 0, 100)
    if full['reading'] not in ('ltr', 'rtl'):
        raise ValueError('reading must be ltr or rtl')
    color(full['page_color']); color(full['border_color'])
    if 'preset' in layout:
        full['preset'] = layout['preset']
    return full


def panels(layout, width, height):
    """[{id, bounds: [x, y, w, h], order, row}] in reading order, in whole pixels."""
    full = resolve(layout)
    margin, gutter = full['margin'], full['gutter']
    rows, cols = full['rows'], full['cols']
    inner_h = height - 2 * margin - gutter * (len(rows) - 1)
    result = []
    y = margin
    for index, (row_weight, columns) in enumerate(zip(rows, cols)):
        row_h = inner_h * row_weight / sum(rows)
        inner_w = width - 2 * margin - gutter * (len(columns) - 1)
        x = margin
        cells = []
        for weight in columns:
            cell_w = inner_w * weight / sum(columns)
            cells.append((x, cell_w))
            x += cell_w + gutter
        if full['reading'] == 'rtl':
            cells.reverse()
        for x, cell_w in cells:
            box = [round(x), round(y), round(x + cell_w) - round(x), round(y + row_h) - round(y)]
            if box[2] < MIN_SIDE or box[3] < MIN_SIDE:
                raise ValueError('Panels would be smaller than %d pixels. Use fewer panels or smaller margins and gutters.' % MIN_SIDE)
            result.append({'id': 'P%d' % (len(result) + 1), 'bounds': box, 'order': len(result) + 1, 'row': index + 1})
        y += row_h + gutter
    return result
