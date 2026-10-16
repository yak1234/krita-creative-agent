import { readFile, realpath, stat } from 'node:fs/promises';
import { isAbsolute, relative, sep } from 'node:path';

export async function containedFile(root, filename) {
  const [base, path] = await Promise.all([realpath(root), realpath(filename)]);
  const part = relative(base, path);
  if (part === '..' || part.startsWith('..' + sep) || isAbsolute(part)) throw new Error('Observation is outside this study.');
  if (!(await stat(path)).isFile()) throw new Error('Expected an image file.');
  return path;
}

export function imageInfo(data) {
  if (data.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])) && data.length >= 24)
    return { mimeType: 'image/png', width: data.readUInt32BE(16), height: data.readUInt32BE(20) };
  if (data.subarray(0, 3).toString() === 'GIF' && data.length >= 10)
    return { mimeType: 'image/gif', width: data.readUInt16LE(6), height: data.readUInt16LE(8) };
  if (data[0] === 255 && data[1] === 216) {
    let at = 2;
    while (at + 9 < data.length) {
      if (data[at] !== 255) break;
      const marker = data[at + 1];
      if ([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(marker))
        return { mimeType: 'image/jpeg', width: data.readUInt16BE(at + 7), height: data.readUInt16BE(at + 5) };
      if (marker === 218 || marker === 217) break;
      const length = data.readUInt16BE(at + 2);
      if (length < 2) break;
      at += 2 + length;
    }
  }
  throw new Error('Choose a PNG, JPEG, or GIF image with readable dimensions.');
}

export async function imageContent(root, filename) {
  const path = await containedFile(root, filename);
  if ((await stat(path)).size > 12 * 1024 * 1024) throw new Error('Use a reference smaller than 12 MB.');
  const data = await readFile(path);
  const info = imageInfo(data);
  return { info, content: { type: 'image', data: data.toString('base64'), mimeType: info.mimeType } };
}

export function splitJsonLines(buffer) {
  const lines = buffer.split('\n');
  return { lines: lines.slice(0, -1).map(line => line.endsWith('\r') ? line.slice(0, -1) : line), rest: lines.at(-1) };
}
