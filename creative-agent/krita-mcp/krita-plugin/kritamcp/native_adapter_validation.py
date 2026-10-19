"""Pure validation for native UI tool commands; no Qt initialization required."""
import math

def validated_parameters(kind, p, width, height):
    """Validate the complete command before the transaction clones a layer."""
    def number(v, lo, hi):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
            raise ValueError('Invalid native tool numeric parameter')
        return v
    def point(v):
        if not isinstance(v, list) or len(v) != 2: raise ValueError('Use [x,y] canvas coordinates')
        number(v[0], 0, width - 1); number(v[1], 0, height - 1)
    if kind == 'gradient':
        if set(p) != {'shape','start','end','foreground','background','opacity'}: raise ValueError('Supply shape,start,end,foreground,background,opacity')
        if p['shape'] not in ('linear','radial'): raise ValueError('Use linear or radial')
        point(p['start']); point(p['end'])
        if p['start'] == p['end']: raise ValueError('Gradient endpoints must differ')
        for k in ('foreground','background'):
            import re
            if not isinstance(p[k],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',p[k]): raise ValueError('Use #RRGGBB colors')
        number(p['opacity'],0,1)
    elif kind == 'smart_patch':
        if set(p) != {'paths','diameter','accuracy','patch_radius'}: raise ValueError('Supply paths,diameter,accuracy,patch_radius; precede with an explicit selection')
        if not isinstance(p['paths'],list) or not 1 <= len(p['paths']) <= 64: raise ValueError('Use 1–64 mask paths')
        count=0
        for path in p['paths']:
            if not isinstance(path,list) or len(path)<2: raise ValueError('Mask paths need at least two points')
            for pt in path: point(pt)
            count+=len(path)
        if count>4096: raise ValueError('Use at most 4096 mask points')
        number(p['diameter'],1,512)
        for k,lo,hi in [('accuracy',0,100),('patch_radius',1,50)]:
            number(p[k],lo,hi)
            if int(p[k])!=p[k]: raise ValueError('Patch parameters must be integers')
    else: raise ValueError('Unknown native adapter')
    return p

