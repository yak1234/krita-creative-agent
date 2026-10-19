"""Exercise visible-region retouch on a disposable Krita copy, never the source."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import urllib.request
import uuid
import zipfile

from PIL import Image, ImageChops


def command(operation, params=None, session_id=None, operation_id=None):
    request = {'operation': operation, 'params': params or {}}
    if session_id: request['session_id'] = session_id
    if operation_id: request['operation_id'] = operation_id
    body = json.dumps({'action':'creative', 'params':request, 'timeout':120}).encode()
    call = urllib.request.Request('http://127.0.0.1:5678', body, {'Content-Type':'application/json'})
    with urllib.request.urlopen(call, timeout=140) as response:
        value = json.load(response)
    if value.get('error'): raise RuntimeError('%s: %s' % (operation,value['error']))
    return value


def merged(path):
    with zipfile.ZipFile(path) as archive:
        return Image.open(BytesIO(archive.read('mergedimage.png'))).convert('RGBA')


def pixel_count(before, after, region=None, outside=False):
    pixels = ImageChops.difference(before,after)
    x,y,w,h = region or (0,0,before.width,before.height)
    points=((px,py) for py in range(before.height) for px in range(before.width)
            if (x <= px < x+w and y <= py < y+h) != outside)
    return sum(1 for px,py in points if any(pixels.getpixel((px,py))[:3]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--copy',required=True,type=Path)
    args=parser.parse_args()
    source=args.source.resolve(); copy=args.copy.resolve()
    if not source.is_file() or copy.exists(): raise SystemExit('Source must exist and test copy must not exist.')
    context=command('context')
    if Path(context['filename']).resolve()!=source or context['modified']:
        raise SystemExit('Open the saved source painting in Krita before this disposable test.')
    health=command('health')
    if health['session_active']: raise SystemExit('A painting session is active; stop it before this test.')
    session=str(uuid.uuid4())
    output=source.parent/'.creative-agent'/'live-tests'/session
    output.mkdir(parents=True)
    region=[400,480,60,60]
    began=False; paint=None; rejected=False
    try:
        first=command('begin',{'mode':'copy','name':'Lower-retouch acceptance copy','output_dir':str(output),
            'painting_path':str(copy),'source_document_id':context['document_id']},session)
        began=True
        before=merged(copy)
        if ImageChops.difference(before,merged(source)).getbbox():
            raise RuntimeError('The test copy differs from the source before painting.')
        paint=command('painting_toolbox',{'name':'Visible-region retouch acceptance mark',
            'projection_region':region,'projection_feather':8,'expected_revision':first['revision'],
            'commands':[{'tool':'curve_stroke','parameters_json':json.dumps({
                'start':[390,510],'segments':[[410,510,450,510,470,510]],
                'size':9,'opacity':1,'flow':1,'color':'#ff00ff'})}]},session,'projection-test')
        altered=merged(copy)
        changed=pixel_count(before,altered,region)
        outside=pixel_count(before,altered,region,True)
        if not changed or outside: raise RuntimeError('Retouch changed %d inside pixels and %d outside pixels.'%(changed,outside))
        rejection=command('review_pass',{'pass_id':'projection-test','action':'reject',
            'expected_revision':paint['revision']},session,'projection-reject')
        rejected=True
        restored=merged(copy)
        if ImageChops.difference(before,restored).getbbox():
            raise RuntimeError('Reject did not restore the original visible pixels.')
        print(json.dumps({'status':'passed','build_id':health['build']['build_id'],
            'source':str(source),'test_copy':str(copy),'changed_inside':changed,
            'changed_outside':outside,'rejected':rejection['status']}))
    finally:
        if began and paint and not rejected:
            command('review_pass',{'pass_id':'projection-test','action':'reject',
                'expected_revision':paint['revision']},session,'projection-reject')
        if began: command('end',{},session)


if __name__=='__main__': main()
