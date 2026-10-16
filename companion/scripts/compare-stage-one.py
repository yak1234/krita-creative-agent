"""Measure protected pixels and build a standalone before/after review from a real evaluation."""
import argparse
import base64
import hashlib
import html
import json
from pathlib import Path


def pixel_checks(before, after, region):
    if before.size != after.size:
        raise ValueError('Before and after images have different dimensions.')
    width, height = before.size
    x, y, w, h = region
    if any(not isinstance(n, int) for n in region) or min(x, y) < 0 or min(w, h) <= 0 or x+w > width or y+h > height:
        raise ValueError('The protected-region test needs valid document pixel bounds.')
    inside_changed = outside_changed = 0
    greatest_change = 0
    total_change = 0
    for index, (a, b) in enumerate(zip(before.convert('RGBA').getdata(), after.convert('RGBA').getdata())):
        px, py = index % width, index // width
        change = max(abs(a[c]-b[c]) for c in range(4))
        if x <= px < x+w and y <= py < y+h:
            inside_changed += int(change > 0)
            total_change += sum(abs(a[c]-b[c]) for c in range(3))
            greatest_change = max(greatest_change, change)
        else:
            outside_changed += int(change > 0)
    return {'region': region, 'size': [width, height], 'inside_changed_pixels': inside_changed,
            'inside_changed_fraction': inside_changed / (w*h), 'outside_changed_pixels': outside_changed,
            'protected_pixels_unchanged': outside_changed == 0,
            'mean_absolute_rgb_change_inside': total_change / (w*h*3), 'maximum_channel_change_inside': greatest_change,
            'artistic_success': None,
            'interpretation': 'Pixel differences verify where paint changed. They do not establish convincing dry texture or artistic quality.'}


def build_report(evaluation_path):
    from PIL import Image
    evaluation_path = Path(evaluation_path).resolve()
    report = json.loads(evaluation_path.read_text())
    before_record, after_record = report.get('before_full_snapshot'), report.get('final_full_snapshot')
    if not before_record or not after_record:
        raise ValueError('This run lacks both full-resolution snapshots; preserve the failed run and inspect its error.')
    before, after = (Path(item['image_path']) for item in (before_record, after_record))
    result = pixel_checks(Image.open(before), Image.open(after), [100,150,580,330])
    result.update(build_id=report['build']['build_id'], provider=report['provider'], model=report['model'],
                  original_disk_unchanged=report.get('original_unchanged'), original_live_unchanged=report.get('original_live_unchanged'),
                  stage_boundary_respected=report.get('stage_boundary_respected'),
                  before_sha256=hashlib.sha256(before.read_bytes()).hexdigest(),
                  after_sha256=hashlib.sha256(after.read_bytes()).hexdigest())
    output = evaluation_path.parent
    (output/'comparison.json').write_text(json.dumps(result, indent=2)+'\n')
    images = ['data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode() for path in (before,after)]
    cards = ''.join('<figure><figcaption>'+label+'</figcaption><div class="viewport"><img src="'+image+'" alt="'+label+' painting"></div></figure>' for label,image in zip(('Before','After'), images))
    protected = 'Unchanged' if result['protected_pixels_unchanged'] else str(result['outside_changed_pixels'])+' pixels changed — constraint failed'
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Stage One · Material review</title><style>
:root{color-scheme:dark;font:15px/1.55 -apple-system,BlinkMacSystemFont,sans-serif;background:#191b1e;color:#ececef}
body{margin:0 auto;padding:32px;max-width:1500px}h1{font-size:27px;margin:0 0 6px}p{max-width:850px;color:#b9bdc7}
button{font:inherit;color:inherit;background:#30343c;border:1px solid #505663;border-radius:7px;padding:7px 13px;cursor:pointer}
button[aria-pressed=true]{background:#3c5571;border-color:#7794b6}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0}
.pair{display:flex;gap:24px;align-items:flex-start;overflow:auto;padding-bottom:15px}figure{margin:0;flex:none}figcaption{margin-bottom:10px;color:#c8cbd2}
.viewport{overflow:auto;max-width:100%;background:#24262a}img{display:block;width:768px;height:1024px;max-width:none}
.thumbnail img{width:192px;height:256px}.crop .viewport{width:580px;height:330px;overflow:hidden}.crop img{transform:translate(-100px,-150px)}
dl{display:grid;grid-template-columns:max-content 1fr;gap:7px 20px;font-size:14px}dt{color:#b9bdc7}dd{margin:0}code{overflow-wrap:anywhere}
@media(max-width:650px){body{padding:18px}dl{grid-template-columns:1fr;gap:3px}dd{margin-bottom:8px}}
</style><h1>Stage One: Material</h1><p>Compare the actual saved snapshots. At 100%, look for granular breakup and unwanted stripes. At thumbnail size, check that the field keeps its colour, weight and shape. A reviewer’s approval does not replace this inspection.</p>
<div class="toolbar" role="group" aria-label="Review scale"><button data-mode="full" aria-pressed="true">Full resolution · 100%</button><button data-mode="crop" aria-pressed="false">Upper-field core · 100%</button><button data-mode="thumbnail" aria-pressed="false">Thumbnail · 25%</button></div>
<div class="pair">'''+cards+'''</div><dl><dt>Outside the agreed region</dt><dd>'''+protected+'''</dd><dt>Changed inside the region</dt><dd>'''+str(result['inside_changed_pixels'])+''' pixels</dd><dt>Model</dt><dd>'''+html.escape(report['model']+' · '+report['provider'])+'''</dd><dt>Build</dt><dd><code>'''+html.escape(report['build']['build_id'])+'''</code></dd></dl>
<p>The original painting must remain unchanged on disk and in Krita. Read comparison.json and evaluation.json for preservation checks, stopping boundaries and retained failures. No automatic artistic-success score is assigned.</p>
<script>for(const button of document.querySelectorAll('button'))button.addEventListener('click',()=>{document.querySelector('.pair').className='pair '+button.dataset.mode;for(const peer of document.querySelectorAll('button'))peer.setAttribute('aria-pressed',String(peer===button));});</script></html>'''
    (output/'review.html').write_text(page)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evaluation', type=Path)
    args = parser.parse_args()
    print(json.dumps(build_report(args.evaluation), indent=2))
