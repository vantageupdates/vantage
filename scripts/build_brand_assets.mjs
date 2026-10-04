import fs from "node:fs/promises";
import {createRequire} from "node:module";
import path from "node:path";
import process from "node:process";

const require = createRequire(import.meta.url);
const sharp = require("sharp");

const ROOT = path.resolve(import.meta.dirname, "..");
const SOURCE = path.join(
  ROOT, "data", "assets", "vantage-companion-logo-source.png");
const MASTER = path.join(ROOT, "data", "ui", "icon-master.png");
const ICON = path.join(ROOT, "data", "ui", "icon.png");
const ICO = path.join(ROOT, "data", "ui", "icon.ico");
const ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256];

function alphaMask(width, height) {
  // The selected artwork contains a baked checkerboard. This measured ellipse
  // follows its outer black rim and turns only the area outside it transparent.
  const centerX = width * (624 / 1254);
  const centerY = height * (611 / 1254);
  const radiusX = width * (566 / 1254);
  const radiusY = height * (556 / 1254);
  const feather = Math.max(1, width / 1254 * 1.5);
  const mask = Buffer.alloc(width * height);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const dx = (x - centerX) / radiusX;
      const dy = (y - centerY) / radiusY;
      const normalized = Math.sqrt(dx * dx + dy * dy);
      const distance = (1 - normalized) * Math.min(radiusX, radiusY);
      mask[y * width + x] = Math.round(
        255 * Math.max(0, Math.min(1, distance / feather)));
    }
  }
  return mask;
}

async function makeTransparentMaster() {
  const image = sharp(SOURCE).removeAlpha();
  const metadata = await image.metadata();
  if (metadata.width !== 1254 || metadata.height !== 1254) {
    throw new Error(
      `Unexpected selected artwork size ${metadata.width}x${metadata.height}`);
  }
  const mask = alphaMask(metadata.width, metadata.height);
  const rgb = await image.raw().toBuffer();
  const rgba = Buffer.alloc(metadata.width * metadata.height * 4);
  for (let pixel = 0; pixel < metadata.width * metadata.height; pixel += 1) {
    rgba[pixel * 4] = rgb[pixel * 3];
    rgba[pixel * 4 + 1] = rgb[pixel * 3 + 1];
    rgba[pixel * 4 + 2] = rgb[pixel * 3 + 2];
    rgba[pixel * 4 + 3] = mask[pixel];
  }
  await sharp(rgba, {
    raw: {width: metadata.width, height: metadata.height, channels: 4},
  })
    .png({compressionLevel: 9, adaptiveFiltering: true})
    .toFile(MASTER);
}

async function sizedPng(size) {
  let pipeline = sharp(MASTER).resize(size, size, {
    fit: "contain",
    kernel: sharp.kernel.lanczos3,
  });
  if (size <= 64) {
    pipeline = pipeline.sharpen({sigma: 0.45, m1: 0.65, m2: 1.2});
  }
  return pipeline.png({compressionLevel: 9, adaptiveFiltering: true}).toBuffer();
}

function makeIco(entries) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(entries.length, 4);
  const directory = Buffer.alloc(entries.length * 16);
  let offset = header.length + directory.length;
  entries.forEach(({size, png}, index) => {
    const start = index * 16;
    directory.writeUInt8(size === 256 ? 0 : size, start);
    directory.writeUInt8(size === 256 ? 0 : size, start + 1);
    directory.writeUInt8(0, start + 2);
    directory.writeUInt8(0, start + 3);
    directory.writeUInt16LE(1, start + 4);
    directory.writeUInt16LE(32, start + 6);
    directory.writeUInt32LE(png.length, start + 8);
    directory.writeUInt32LE(offset, start + 12);
    offset += png.length;
  });
  return Buffer.concat([header, directory, ...entries.map(entry => entry.png)]);
}

async function main() {
  await makeTransparentMaster();
  const entries = [];
  for (const size of ICO_SIZES) {
    entries.push({size, png: await sizedPng(size)});
  }
  await fs.writeFile(ICON, entries.at(-1).png);
  await fs.writeFile(ICO, makeIco(entries));
  process.stdout.write(
    `Built ${path.relative(ROOT, MASTER)}, ${path.relative(ROOT, ICON)}, ` +
    `${path.relative(ROOT, ICO)}\n`);
}

await main();
