// Minimal PWA icon generator. Produces warm-paper "g" placeholder PNGs
// at 192x192 and 512x512 using pure Node (zlib for deflate, manual CRC).
// Run with: bun run apps/web/scripts/gen-pwa-icons.mjs
//
// Self-contained — no image-processing dependency. The render is a solid
// paper-colored square with a round-ish amber "g" glyph sampled from a tiny
// hand-drawn bitmap. Good enough for install prompts; designer swap later.

import { writeFileSync, mkdirSync } from "node:fs";
import { deflateSync } from "node:zlib";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = resolve(__dirname, "../public/icons");
mkdirSync(OUT_DIR, { recursive: true });

// Warm-paper palette, matches globals.css light theme.
const PAPER = [0xf7, 0xf2, 0xe8]; // #f7f2e8
const AMBER = [0xb5, 0x80, 0x2b]; // #b5802b

// 16x16 hand-drawn "g" glyph, 1 = amber, 0 = paper.
const G16 = [
  "0000000000000000",
  "0000000000000000",
  "0000011111100000",
  "0000110000110000",
  "0001100000011000",
  "0001100000011000",
  "0001100000011000",
  "0001100000011000",
  "0000110000110000",
  "0000011111110000",
  "0000000000011000",
  "0000000000011000",
  "0001100000011000",
  "0000110000110000",
  "0000011111100000",
  "0000000000000000",
].map((row) => row.split("").map(Number));

function renderPixels(size) {
  // scale the 16x16 glyph up to `size` with nearest-neighbor; add a 1px
  // rounded-corner-ish inset so the square doesn't look like a button.
  const px = new Uint8Array(size * size * 4);
  const cell = size / 16;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const gx = Math.min(15, Math.floor(x / cell));
      const gy = Math.min(15, Math.floor(y / cell));
      const on = G16[gy][gx] === 1;
      const color = on ? AMBER : PAPER;
      const i = (y * size + x) * 4;
      px[i] = color[0];
      px[i + 1] = color[1];
      px[i + 2] = color[2];
      px[i + 3] = 0xff;
    }
  }
  return px;
}

// --- PNG encoder (RGBA, no filter) ---------------------------------------
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const typeBuf = Buffer.from(type, "ascii");
  const crcInput = Buffer.concat([typeBuf, data]);
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(crcInput), 0);
  return Buffer.concat([len, typeBuf, data, crcBuf]);
}

function encodePng(size, pixels) {
  const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  // add filter byte (0 = None) before each scanline
  const stride = size * 4;
  const raw = Buffer.alloc((stride + 1) * size);
  for (let y = 0; y < size; y++) {
    raw[y * (stride + 1)] = 0;
    Buffer.from(pixels.buffer, pixels.byteOffset + y * stride, stride).copy(
      raw,
      y * (stride + 1) + 1
    );
  }
  const idat = deflateSync(raw);
  return Buffer.concat([
    sig,
    chunk("IHDR", ihdr),
    chunk("IDAT", idat),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

for (const size of [192, 512]) {
  const pixels = renderPixels(size);
  const png = encodePng(size, pixels);
  const out = resolve(OUT_DIR, `icon-${size}.png`);
  writeFileSync(out, png);
  console.log(`wrote ${out} (${png.length} bytes)`);
}
