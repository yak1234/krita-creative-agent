"""Create a deterministic woven grayscale texture fixture using PNG's standard format."""
import math, struct, zlib
from pathlib import Path
n=128
rows=[]
for y in range(n):
    row=bytearray([0])
    for x in range(n):
        v=128+52*math.sin(x*math.pi/8)*math.sin(y*math.pi/8)+30*math.cos(x*math.pi/2)+20*math.cos(y*math.pi/2)
        row.append(max(0,min(255,round(v))))
    rows.append(bytes(row))
def chunk(t,data):
    return struct.pack('>I',len(data))+t+data+struct.pack('>I',zlib.crc32(t+data)&0xffffffff)
png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',n,n,8,0,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')
Path(__file__).with_name('woven_canvas.png').write_bytes(png)
