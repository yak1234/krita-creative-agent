"""Compare real exported pixels, independent of model/self-reported success."""
import json,sys,zipfile,io
from PIL import Image
def load(path):
    if path.lower().endswith('.kra'):
        with zipfile.ZipFile(path) as archive:return Image.open(io.BytesIO(archive.read('mergedimage.png'))).convert('RGBA')
    return Image.open(path).convert('RGBA')
before=load(sys.argv[1]);after=load(sys.argv[2])
if before.size!=after.size: raise SystemExit('Snapshot dimensions changed')
mode=sys.argv[3];a=list(before.getdata());b=list(after.getdata());w,h=before.size
changed=[i for i,(x,y) in enumerate(zip(a,b)) if x!=y]
result={'changed_pixels':len(changed),'width':w,'height':h}
if mode=='unchanged':result['passed']=not changed
elif mode=='gradient':
 x,y,rw,rh=map(int,sys.argv[4:8]);outside=sum(not(x<=i%w<x+rw and y<=i//w<y+rh) for i in changed)
 left=after.getpixel((x+10,y+rh//2));right=after.getpixel((x+rw-11,y+rh//2))
 result.update(outside_region_changes=outside,left=list(left),right=list(right))
 result['passed']=len(changed)>rw*rh*.8 and outside==0 and left[2]>left[0]+40 and right[0]>right[2]+80
elif mode=='reject_patch':
 x,y,rw,rh=map(int,sys.argv[4:8]);outside=sum(not(x<=i%w<x+rw and y<=i//w<y+rh) for i in changed)
 center=list(after.getpixel((200,410)))
 result.update(outside_region_changes=outside,center=center)
 result['passed']=len(changed)==400 and outside==0 and center==[220,30,30,255]
elif mode=='patch':
 x,y,rw,rh=map(int,sys.argv[4:8]);outside=sum(not(x<=i%w<x+rw and y<=i//w<y+rh) for i in changed)
 center=list(after.getpixel((200,410)))
 result.update(outside_region_changes=outside,center=center)
 result['passed']=len(changed)==400 and outside==0 and center==[190,180,160,255]
else:raise SystemExit('Unknown pixel check')
print(json.dumps(result));sys.exit(0 if result['passed'] else 1)
