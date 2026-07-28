// Generates icon-180.png / icon-192.png / icon-512.png — a CRT-amber play
// triangle with scanline gaps on near-black blue, the Sound Test mark.
// Zero dependencies (hand-rolled PNG encoder + node's zlib). Run: node make-icons.js
const zlib = require('zlib');
const fs = require('fs');

// --- minimal PNG encoder (8-bit RGBA, filter 0) ---
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(buf) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}
function chunk(type, data) {
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0);
  out.write(type, 4, 'ascii');
  data.copy(out, 8);
  out.writeUInt32BE(crc32(out.subarray(4, 8 + data.length)), 8 + data.length);
  return out;
}
function encodePNG(width, height, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; ihdr[9] = 6; // 8-bit, RGBA
  const raw = Buffer.alloc(height * (1 + width * 4));
  for (let y = 0; y < height; y++) {
    raw[y * (1 + width * 4)] = 0; // filter: none
    rgba.copy(raw, y * (1 + width * 4) + 1, y * width * 4, (y + 1) * width * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// --- drawing: 2x supersampled ---
const BG = [0x0b, 0x0e, 0x14], AMBER = [0xf5, 0xa8, 0x3c], AMBER_HI = [0xff, 0xc8, 0x78];

function inTriangle(x, y) { // chunky right-pointing play glyph
  const x0 = 0.315, x1 = 0.735, cy = 0.46, half0 = 0.215;
  if (x < x0 || x > x1) return false;
  return Math.abs(y - cy) <= half0 * (1 - (x - x0) / (x1 - x0));
}
function inScanGap(y) { // two thin bg bands across the glyph: the CRT read
  return (y > 0.395 && y < 0.412) || (y > 0.505 && y < 0.522);
}
function inTrackBar(x, y) { // the "next track" underline below the glyph
  return y > 0.66 && y < 0.685 && x > 0.315 && x < 0.685;
}
function draw(size) {
  const SS = 2, N = size * SS;
  const acc = new Float64Array(size * size * 3);
  for (let py = 0; py < N; py++) {
    for (let px = 0; px < N; px++) {
      const x = (px + 0.5) / N, y = (py + 0.5) / N;
      let c;
      if (inTriangle(x, y) && !inScanGap(y)) {
        // vertical sheen toward the leading edge
        const sheen = Math.max(0, 1 - Math.abs(x - 0.40) * 3.4);
        c = [
          AMBER[0] + (AMBER_HI[0] - AMBER[0]) * sheen * 0.65,
          AMBER[1] + (AMBER_HI[1] - AMBER[1]) * sheen * 0.65,
          AMBER[2] + (AMBER_HI[2] - AMBER[2]) * sheen * 0.65,
        ];
      } else if (inTrackBar(x, y)) {
        c = [0x7d, 0x5a, 0x24]; // amberdim
      } else {
        // near-black blue with a phosphor glow behind the glyph
        const d = Math.hypot(x - 0.5, y - 0.46) / 0.62;
        const glow = Math.max(0, 1 - d) * 0.16;
        c = [BG[0] + AMBER[0] * glow * 0.35, BG[1] + AMBER[1] * glow * 0.3, BG[2] + AMBER[2] * glow * 0.2];
      }
      const ox = Math.floor(px / SS), oy = Math.floor(py / SS);
      const i = (oy * size + ox) * 3;
      acc[i] += c[0]; acc[i + 1] += c[1]; acc[i + 2] += c[2];
    }
  }
  const rgba = Buffer.alloc(size * size * 4);
  const div = SS * SS;
  for (let i = 0; i < size * size; i++) {
    rgba[i * 4] = Math.min(255, Math.round(acc[i * 3] / div));
    rgba[i * 4 + 1] = Math.min(255, Math.round(acc[i * 3 + 1] / div));
    rgba[i * 4 + 2] = Math.min(255, Math.round(acc[i * 3 + 2] / div));
    rgba[i * 4 + 3] = 255;
  }
  return encodePNG(size, size, rgba);
}

for (const size of [180, 192, 512]) {
  fs.writeFileSync(`icon-${size}.png`, draw(size));
  console.log(`wrote icon-${size}.png`);
}
