/**
 * Client-side CV centering pipeline.
 *
 * Port of the Python pipeline (crops.py, edge_detect.py, reconstruct.py)
 * to run entirely in the browser using Canvas getImageData.
 *
 * Usage:
 *   const result = runCenteringCV(canvas, cropMode);
 *   // result = { lines, measurements, detections, crops, imageSize }
 */

// ── Slab crop constants ──────────────────────────────────────────────────────
const SLAB_CROPS = {
  psa:  { left: 0.095, right: 0.095, top: 0.26,  bottom: 0.0715 },
  cgc:  { left: 0.085, right: 0.085, top: 0.22,  bottom: 0.065 },
};

// ── Tuning knobs ─────────────────────────────────────────────────────────────
const EDGE_WINDOW_FRAC = 0.45;
const EDGE_DEPTH_FRAC = 0.10;
const EDGE_WINDOW_POSITIONS = [0.05, 0.50];

const DEFAULT_SAMPLE_BAND = [0.05, 0.75];
const HIST_BINS = 16;
const TOLERANCE_K = 3.0;
const TOLERANCE_FLOOR = 10.0;
const MIN_RUN_FRAC = 0.05;
const FALLBACK_THRESHOLD = 0.50;
const FALLBACK_CARD_FRAC = 0.10;
const FALLBACK_ART_FRAC = 0.50;
const MAD_K = 3.0;
const MAD_FLOOR_PX = 2.0;

const DEFAULT_CARD_FRAC = { top: 0.01, bottom: 0.99, left: 0.02, right: 0.98 };
const DEFAULT_ART_FRAC = { top: 0.06, bottom: 0.94, left: 0.10, right: 0.90 };
const MAX_DEVIATION_FRAC = 0.15;
const MAX_SLOPE = 0.05;
const MIN_CONFIDENCE_SUM = 0.5;

// ── RGB → Lab conversion ─────────────────────────────────────────────────────
function srgbToLinear(c) {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function rgbToLab(r, g, b) {
  // sRGB → XYZ (D65)
  const rl = srgbToLinear(r), gl = srgbToLinear(g), bl = srgbToLinear(b);
  let x = 0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl;
  let y = 0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl;
  let z = 0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl;
  // XYZ → Lab
  x /= 0.95047; y /= 1.00000; z /= 1.08883;
  const f = t => t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116;
  const fx = f(x), fy = f(y), fz = f(z);
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

// ── Image helpers ────────────────────────────────────────────────────────────
function cropImage(imageData, x0, y0, x1, y1) {
  const w = imageData.width, h = imageData.height;
  x0 = Math.max(0, Math.min(w, x0));
  x1 = Math.max(0, Math.min(w, x1));
  y0 = Math.max(0, Math.min(h, y0));
  y1 = Math.max(0, Math.min(h, y1));
  const cw = x1 - x0, ch = y1 - y0;
  const pixels = new Uint8Array(cw * ch * 4);
  const src = imageData.data;
  for (let row = 0; row < ch; row++) {
    const srcOff = ((y0 + row) * w + x0) * 4;
    const dstOff = row * cw * 4;
    pixels.set(src.subarray(srcOff, srcOff + cw * 4), dstOff);
  }
  return { data: pixels, width: cw, height: ch };
}

// Convert image region to Lab. Returns Float64Array of shape [h][w][3] flattened.
function imageToLab(img) {
  const { data, width: w, height: h } = img;
  const lab = new Float64Array(w * h * 3);
  for (let i = 0; i < w * h; i++) {
    const [L, a, b] = rgbToLab(data[i * 4], data[i * 4 + 1], data[i * 4 + 2]);
    lab[i * 3] = L; lab[i * 3 + 1] = a; lab[i * 3 + 2] = b;
  }
  return lab;
}

// ── Crop generation ──────────────────────────────────────────────────────────
function generateCrops(imageData, w, h) {
  const stripWH = Math.round(w * EDGE_WINDOW_FRAC);
  const stripHH = Math.round(h * EDGE_DEPTH_FRAC);
  const stripHV = Math.round(h * EDGE_WINDOW_FRAC);
  const stripWV = Math.round(w * EDGE_DEPTH_FRAC);

  const crops = [];
  EDGE_WINDOW_POSITIONS.forEach((pos, idx) => {
    const i = idx + 1;
    // Top strip — scan down
    let x0 = Math.round(w * pos), y0 = 0;
    crops.push({ name: `edge_top_w${i}`, side: 'top', scanDir: 'down',
      image: cropImage(imageData, x0, y0, x0 + stripWH, stripHH),
      offset: [x0, y0], size: [Math.min(stripWH, w - x0), stripHH] });

    // Bottom strip — scan up
    x0 = Math.round(w * pos); y0 = h - stripHH;
    crops.push({ name: `edge_bot_w${i}`, side: 'bottom', scanDir: 'up',
      image: cropImage(imageData, x0, y0, x0 + stripWH, h),
      offset: [x0, y0], size: [Math.min(stripWH, w - x0), h - y0] });

    // Left strip — scan right
    x0 = 0; y0 = Math.round(h * pos);
    crops.push({ name: `edge_left_w${i}`, side: 'left', scanDir: 'right',
      image: cropImage(imageData, x0, y0, stripWV, y0 + stripHV),
      offset: [x0, y0], size: [stripWV, Math.min(stripHV, h - y0)] });

    // Right strip — scan left
    x0 = w - stripWV; y0 = Math.round(h * pos);
    crops.push({ name: `edge_right_w${i}`, side: 'right', scanDir: 'left',
      image: cropImage(imageData, x0, y0, w, y0 + stripHV),
      offset: [x0, y0], size: [w - x0, Math.min(stripHV, h - y0)] });
  });
  return crops;
}

// ── Edge detection ───────────────────────────────────────────────────────────

// Orient scan lines: returns array of scan lines, each a Float64Array of Lab triples.
// Each line goes from outer (slab) to inner (card interior).
function orientedLines(lab, w, h, scanDir) {
  const lines = [];
  if (scanDir === 'down') {
    // Columns, top to bottom
    for (let x = 0; x < w; x++) {
      const line = new Float64Array(h * 3);
      for (let y = 0; y < h; y++) { const o = (y * w + x) * 3; line[y*3]=lab[o]; line[y*3+1]=lab[o+1]; line[y*3+2]=lab[o+2]; }
      lines.push(line);
    }
  } else if (scanDir === 'up') {
    for (let x = 0; x < w; x++) {
      const line = new Float64Array(h * 3);
      for (let y = 0; y < h; y++) { const o = ((h-1-y) * w + x) * 3; line[y*3]=lab[o]; line[y*3+1]=lab[o+1]; line[y*3+2]=lab[o+2]; }
      lines.push(line);
    }
  } else if (scanDir === 'right') {
    for (let y = 0; y < h; y++) {
      const line = new Float64Array(w * 3);
      for (let x = 0; x < w; x++) { const o = (y * w + x) * 3; line[x*3]=lab[o]; line[x*3+1]=lab[o+1]; line[x*3+2]=lab[o+2]; }
      lines.push(line);
    }
  } else { // left
    for (let y = 0; y < h; y++) {
      const line = new Float64Array(w * 3);
      for (let x = 0; x < w; x++) { const o = (y * w + (w-1-x)) * 3; line[x*3]=lab[o]; line[x*3+1]=lab[o+1]; line[x*3+2]=lab[o+2]; }
      lines.push(line);
    }
  }
  return lines;
}

function localPoint(scanDir, lineIdx, depth, cw, ch) {
  if (scanDir === 'down') return [lineIdx, depth];
  if (scanDir === 'up') return [lineIdx, ch - 1 - depth];
  if (scanDir === 'right') return [depth, lineIdx];
  return [cw - 1 - depth, lineIdx]; // left
}

function toParent(localXY, offset) {
  return [offset[0] + localXY[0], offset[1] + localXY[1]];
}

function borderColorAndTolerance(sampleLab, toleranceOverride) {
  const n = sampleLab.length / 3;
  if (n === 0) return { border: [0, 0, 0], tolerance: toleranceOverride || TOLERANCE_FLOOR };

  const binSize = Math.max(1, Math.floor(256 / HIST_BINS));
  // Quantize to bins (Lab values 0-100 for L, -128..127 for a,b → shift to 0-255 range for binning)
  // Actually our Lab is float: L∈[0,100], a∈[-128,127], b∈[-128,127]. Shift to 0-255 for binning.
  const counts = new Map();
  const qArr = new Int32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const L = Math.max(0, Math.min(255, Math.round(sampleLab[i*3] * 2.55)));
    const a = Math.max(0, Math.min(255, Math.round(sampleLab[i*3+1] + 128)));
    const b = Math.max(0, Math.min(255, Math.round(sampleLab[i*3+2] + 128)));
    const qL = Math.min(HIST_BINS - 1, Math.floor(L / binSize));
    const qA = Math.min(HIST_BINS - 1, Math.floor(a / binSize));
    const qB = Math.min(HIST_BINS - 1, Math.floor(b / binSize));
    qArr[i*3] = qL; qArr[i*3+1] = qA; qArr[i*3+2] = qB;
    const key = qL * HIST_BINS * HIST_BINS + qA * HIST_BINS + qB;
    counts.set(key, (counts.get(key) || 0) + 1);
  }

  let modeKey = 0, modeCount = 0;
  for (const [k, c] of counts) { if (c > modeCount) { modeKey = k; modeCount = c; } }
  const modeQ = [
    Math.floor(modeKey / (HIST_BINS * HIST_BINS)),
    Math.floor(modeKey / HIST_BINS) % HIST_BINS,
    modeKey % HIST_BINS,
  ];

  // Cluster: mode + 26 neighbors
  let sumL = 0, sumA = 0, sumB = 0, clusterN = 0;
  const clusterDists = [];
  for (let i = 0; i < n; i++) {
    if (Math.abs(qArr[i*3] - modeQ[0]) <= 1 &&
        Math.abs(qArr[i*3+1] - modeQ[1]) <= 1 &&
        Math.abs(qArr[i*3+2] - modeQ[2]) <= 1) {
      sumL += sampleLab[i*3]; sumA += sampleLab[i*3+1]; sumB += sampleLab[i*3+2];
      clusterN++;
    }
  }
  if (clusterN < 10) {
    // Fallback to mode-only
    sumL = 0; sumA = 0; sumB = 0; clusterN = 0;
    for (let i = 0; i < n; i++) {
      const key = qArr[i*3] * HIST_BINS * HIST_BINS + qArr[i*3+1] * HIST_BINS + qArr[i*3+2];
      if (key === modeKey) {
        sumL += sampleLab[i*3]; sumA += sampleLab[i*3+1]; sumB += sampleLab[i*3+2];
        clusterN++;
      }
    }
  }
  if (clusterN === 0) { sumL = 50; sumA = 0; sumB = 0; clusterN = 1; }

  const border = [sumL / clusterN, sumA / clusterN, sumB / clusterN];
  if (toleranceOverride != null) return { border, tolerance: toleranceOverride };

  // Compute std of distances within cluster
  let sumSq = 0, cN2 = 0;
  for (let i = 0; i < n; i++) {
    if (Math.abs(qArr[i*3] - modeQ[0]) <= 1 &&
        Math.abs(qArr[i*3+1] - modeQ[1]) <= 1 &&
        Math.abs(qArr[i*3+2] - modeQ[2]) <= 1) {
      const dL = sampleLab[i*3] - border[0], dA = sampleLab[i*3+1] - border[1], dB = sampleLab[i*3+2] - border[2];
      sumSq += Math.sqrt(dL*dL + dA*dA + dB*dB);
      cN2++;
    }
  }
  const meanDist = cN2 > 0 ? sumSq / cN2 : 0;
  // Recompute as std
  let varSum = 0;
  for (let i = 0; i < n; i++) {
    if (Math.abs(qArr[i*3] - modeQ[0]) <= 1 &&
        Math.abs(qArr[i*3+1] - modeQ[1]) <= 1 &&
        Math.abs(qArr[i*3+2] - modeQ[2]) <= 1) {
      const dL = sampleLab[i*3] - border[0], dA = sampleLab[i*3+1] - border[1], dB = sampleLab[i*3+2] - border[2];
      const d = Math.sqrt(dL*dL + dA*dA + dB*dB);
      varSum += (d - meanDist) ** 2;
    }
  }
  const std = cN2 > 1 ? Math.sqrt(varSum / (cN2 - 1)) : 0;
  const tolerance = Math.max(TOLERANCE_K * std, TOLERANCE_FLOOR);
  return { border, tolerance };
}

function longestRun(mask) {
  let bestStart = -1, bestLen = 0, curStart = -1, curLen = 0;
  for (let i = 0; i <= mask.length; i++) {
    if (i < mask.length && mask[i]) {
      if (curLen === 0) curStart = i;
      curLen++;
    } else {
      if (curLen > bestLen) { bestLen = curLen; bestStart = curStart; }
      curLen = 0;
    }
  }
  return bestLen > 0 ? [bestStart, bestStart + bestLen] : null;
}

function scanLineColor(lineLab, depth, border, tolerance, minRunFrac) {
  if (depth < 4) return [null, null];
  const mask = new Uint8Array(depth);
  for (let i = 0; i < depth; i++) {
    const dL = lineLab[i*3] - border[0], dA = lineLab[i*3+1] - border[1], dB = lineLab[i*3+2] - border[2];
    if (Math.sqrt(dL*dL + dA*dA + dB*dB) <= tolerance) mask[i] = 1;
  }
  const run = longestRun(mask);
  if (!run) return [null, null];
  const minLen = Math.max(3, Math.round(minRunFrac * depth));
  if (run[1] - run[0] < minLen) return [null, null];
  return [run[0], run[1]];
}

function median(arr) {
  if (arr.length === 0) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function madFilter(pointsLocal, scanDir) {
  if (pointsLocal.length < 3) return pointsLocal.map((_, i) => i);
  const axisIdx = (scanDir === 'down' || scanDir === 'up') ? 1 : 0;
  const vals = pointsLocal.map(p => p[axisIdx]);
  const med = median(vals);
  const resid = vals.map(v => Math.abs(v - med));
  const mad = median(resid);
  const threshold = Math.max(MAD_K * mad, MAD_FLOOR_PX);
  const kept = [];
  for (let i = 0; i < resid.length; i++) { if (resid[i] <= threshold) kept.push(i); }
  return kept.length > 0 ? kept : pointsLocal.map((_, i) => i);
}

function aggregateKept(pointsLocal, keptIdx, crop) {
  if (keptIdx.length === 0) return null;
  const kept = keptIdx.map(i => pointsLocal[i]);
  const axisIdx = (crop.scanDir === 'down' || crop.scanDir === 'up') ? 1 : 0;
  const medVal = median(kept.map(p => p[axisIdx]));
  const cx = crop.size[0] / 2, cy = crop.size[1] / 2;
  const local = (crop.scanDir === 'down' || crop.scanDir === 'up') ? [cx, medVal] : [medVal, cy];
  return toParent(local, crop.offset);
}

function defaultAtFraction(crop, frac) {
  const [w, h] = crop.size;
  const cx = w / 2, cy = h / 2;
  let local;
  if (crop.scanDir === 'down') local = [cx, frac * h];
  else if (crop.scanDir === 'up') local = [cx, (1 - frac) * h];
  else if (crop.scanDir === 'right') local = [frac * w, cy];
  else local = [(1 - frac) * w, cy];
  return toParent(local, crop.offset);
}

function detectCrop(crop) {
  const { image, scanDir, size } = crop;
  const [cw, ch] = size;
  const lab = imageToLab(image);
  const lines = orientedLines(lab, cw, ch, scanDir);
  const nLines = lines.length;
  const depth = lines.length > 0 ? lines[0].length / 3 : 0;

  // Sample band for border color
  const lo = Math.max(0, Math.round(DEFAULT_SAMPLE_BAND[0] * depth));
  const hi = Math.min(depth, Math.round(DEFAULT_SAMPLE_BAND[1] * depth));
  const sampleN = nLines * Math.max(1, hi - lo);
  const sampleLab = new Float64Array(sampleN * 3);
  let si = 0;
  for (let li = 0; li < nLines; li++) {
    const line = lines[li];
    for (let d = lo; d < hi; d++) {
      sampleLab[si*3] = line[d*3]; sampleLab[si*3+1] = line[d*3+1]; sampleLab[si*3+2] = line[d*3+2];
      si++;
    }
  }

  const { border, tolerance } = borderColorAndTolerance(sampleLab.subarray(0, si * 3), null);

  const cardPointsLocal = [], artPointsLocal = [];
  for (let li = 0; li < nLines; li++) {
    const [cardIdx, artIdx] = scanLineColor(lines[li], depth, border, tolerance, MIN_RUN_FRAC);
    if (cardIdx != null) cardPointsLocal.push(localPoint(scanDir, li, cardIdx, cw, ch));
    if (artIdx != null) artPointsLocal.push(localPoint(scanDir, li, artIdx, cw, ch));
  }

  const nCard = cardPointsLocal.length, nArt = artPointsLocal.length;
  const agree = Math.min(nCard, nArt) / Math.max(nLines, 1);

  const cardParent = cardPointsLocal.map(p => toParent(p, crop.offset));
  const artParent = artPointsLocal.map(p => toParent(p, crop.offset));

  let cardKept = madFilter(cardPointsLocal, scanDir);
  let artKept = madFilter(artPointsLocal, scanDir);

  let cardXY = aggregateKept(cardPointsLocal, cardKept, crop);
  let artXY = aggregateKept(artPointsLocal, artKept, crop);

  let usedFallback = false;
  if (agree < FALLBACK_THRESHOLD) {
    cardXY = defaultAtFraction(crop, FALLBACK_CARD_FRAC);
    artXY = defaultAtFraction(crop, FALLBACK_ART_FRAC);
    cardKept = Array.from({ length: Math.max(nCard, 1) }, (_, i) => i);
    artKept = Array.from({ length: Math.max(nArt, 1) }, (_, i) => i);
    usedFallback = true;
  }

  return {
    crop: crop.name, side: crop.side, scan_dir: scanDir,
    card_xy: cardXY, art_xy: artXY,
    confidence: agree, n_lines: nLines,
    card_points: cardParent, art_points: artParent,
    card_kept: cardKept, art_kept: artKept,
    card_score: cardKept.length / Math.max(nLines, 1),
    art_score: artKept.length / Math.max(nLines, 1),
    used_fallback: usedFallback,
    border_lab: border, tolerance,
  };
}

// ── Line reconstruction ──────────────────────────────────────────────────────
function weightedLineFit(points, axis, weights) {
  if (points.length < 2) return null;
  const indep = points.map(p => axis === 'x' ? p[0] : p[1]);
  const dep = points.map(p => axis === 'x' ? p[1] : p[0]);
  const w = weights || indep.map(() => 1);
  // Weighted least squares: y = mx + b
  let sw = 0, sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (let i = 0; i < indep.length; i++) {
    sw += w[i]; sx += w[i] * indep[i]; sy += w[i] * dep[i];
    sxx += w[i] * indep[i] * indep[i]; sxy += w[i] * indep[i] * dep[i];
  }
  const det = sw * sxx - sx * sx;
  if (Math.abs(det) < 1e-10) return null;
  const slope = (sw * sxy - sx * sy) / det;
  const intercept = (sxx * sy - sx * sxy) / det;
  return { axis, slope, intercept, n: points.length };
}

function defaultLine(side, kind, imgW, imgH) {
  const table = kind === 'card' ? DEFAULT_CARD_FRAC : DEFAULT_ART_FRAC;
  const frac = table[side];
  if (side === 'top' || side === 'bottom')
    return { axis: 'x', slope: 0, intercept: frac * imgH, n: 0 };
  return { axis: 'y', slope: 0, intercept: frac * imgW, n: 0 };
}

function anchoredFit(pts, ws, side, kind, imgW, imgH) {
  const def = defaultLine(side, kind, imgW, imgH);
  if (pts.length === 0) return def;

  const isHoriz = (side === 'top' || side === 'bottom');
  const tol = MAX_DEVIATION_FRAC * (isHoriz ? imgH : imgW);
  const axis = isHoriz ? 'x' : 'y';

  const kept = [];
  for (let i = 0; i < pts.length; i++) {
    const val = isHoriz ? pts[i][1] : pts[i][0];
    if (Math.abs(val - def.intercept) <= tol) kept.push(i);
  }

  const wSum = kept.reduce((s, i) => s + ws[i], 0);
  if (kept.length === 0 || wSum < MIN_CONFIDENCE_SUM) return def;

  const keptPts = kept.map(i => pts[i]);
  const keptWs = kept.map(i => ws[i]);

  if (keptPts.length < 2) {
    const p = keptPts[0];
    return { axis, slope: 0, intercept: isHoriz ? p[1] : p[0], n: 1 };
  }

  const fit = weightedLineFit(keptPts, axis, keptWs);
  if (!fit || Math.abs(fit.slope) > MAX_SLOPE) {
    const idx = isHoriz ? 1 : 0;
    const vals = keptPts.map(p => p[idx]);
    return { axis, slope: 0, intercept: median(vals), n: keptPts.length };
  }
  return fit;
}

function lineEval(line, t) { return line.slope * t + line.intercept; }

function reconstructLines(detections, imgW, imgH, minConf = 0.30) {
  const sides = ['top', 'bottom', 'left', 'right'];
  const cardPts = {}, cardWs = {}, artPts = {}, artWs = {};
  sides.forEach(s => { cardPts[s] = []; cardWs[s] = []; artPts[s] = []; artWs[s] = []; });

  for (const d of detections) {
    const n = Math.max(d.n_lines, 1);
    if (d.card_xy && d.card_score >= minConf) {
      cardPts[d.side].push(d.card_xy); cardWs[d.side].push(d.card_score);
    }
    if (d.art_xy && d.art_score >= minConf) {
      artPts[d.side].push(d.art_xy); artWs[d.side].push(d.art_score);
    }
  }

  const lines = {};
  sides.forEach(s => {
    lines[`card_${s === 'bottom' ? 'bot' : s}`] = anchoredFit(cardPts[s], cardWs[s], s, 'card', imgW, imgH);
    lines[`art_${s === 'bottom' ? 'bot' : s}`] = anchoredFit(artPts[s], artWs[s], s, 'art', imgW, imgH);
  });

  // Convert to the {x0,y0,x1,y1,kind} format the frontend expects
  const result = {};
  for (const [name, line] of Object.entries(lines)) {
    if (!line) continue;
    const kind = name.startsWith('card_') ? 'card' : 'art';
    let x0, y0, x1, y1;
    if (line.axis === 'x') {
      x0 = 0; y0 = lineEval(line, 0); x1 = imgW; y1 = lineEval(line, imgW);
    } else {
      y0 = 0; x0 = lineEval(line, 0); y1 = imgH; x1 = lineEval(line, imgH);
    }
    result[name] = { x0, y0, x1, y1, kind };
  }
  return result;
}

// ── Measurements ─────────────────────────────────────────────────────────────
function computeCenteringMeasurements(lines, imgW, imgH) {
  const lineEvalAt = (name, coord) => {
    const L = lines[name];
    if (!L) return null;
    if (L.axis === 'x') return L.slope * coord + L.intercept;  // given x, returns y
    return L.slope * coord + L.intercept; // given y, returns x
  };

  // Helper: for a line, what's the independent variable?
  const evalLine = (name, t) => {
    const L = lines[name]; if (!L) return null;
    return L.slope * t + L.intercept;
  };

  // Need the raw line objects for eval
  const rawLines = {};
  // Reconstruct raw lines from x0,y0,x1,y1
  for (const [name, L] of Object.entries(lines)) {
    if (!L) continue;
    // Determine axis from the line: vertical-ish lines have axis='y', horizontal have axis='x'
    const isVert = (name.includes('left') || name.includes('right'));
    if (isVert) {
      // axis=y: x = slope*y + intercept
      const dy = L.y1 - L.y0 || 1;
      const slope = (L.x1 - L.x0) / dy;
      const intercept = L.x0 - slope * L.y0;
      rawLines[name] = { axis: 'y', slope, intercept };
    } else {
      // axis=x: y = slope*x + intercept
      const dx = L.x1 - L.x0 || 1;
      const slope = (L.y1 - L.y0) / dx;
      const intercept = L.y0 - slope * L.x0;
      rawLines[name] = { axis: 'x', slope, intercept };
    }
  }

  const ev = (name, t) => { const L = rawLines[name]; return L ? L.slope * t + L.intercept : null; };

  const meas = [];
  const ratioStr = (a, b) => {
    a = Math.max(0, a); b = Math.max(0, b);
    const total = a + b;
    if (total <= 0) return '50/50';
    const pa = Math.round(a / total * 100);
    return `${pa}/${100 - pa}`;
  };

  // LR at top: at y = art_top at center x
  const cx = imgW / 2;
  const yTop = ev('art_top', cx);
  if (yTop != null) {
    const cl = ev('card_left', yTop), al = ev('art_left', yTop);
    const cr = ev('card_right', yTop), ar = ev('art_right', yTop);
    if (cl != null && al != null && cr != null && ar != null) {
      const left = Math.round(al - cl), right = Math.round(cr - ar);
      meas.push({ position: 'lr_top', left_px: left, right_px: right, ratio: ratioStr(left, right) });
    }
  }

  // LR at bottom
  const yBot = ev('art_bot', cx);
  if (yBot != null) {
    const cl = ev('card_left', yBot), al = ev('art_left', yBot);
    const cr = ev('card_right', yBot), ar = ev('art_right', yBot);
    if (cl != null && al != null && cr != null && ar != null) {
      const left = Math.round(al - cl), right = Math.round(cr - ar);
      meas.push({ position: 'lr_bot', left_px: left, right_px: right, ratio: ratioStr(left, right) });
    }
  }

  // TB at left
  const cy = imgH / 2;
  const xLeft = ev('art_left', cy);
  if (xLeft != null) {
    const ct = ev('card_top', xLeft), at_ = ev('art_top', xLeft);
    const cb = ev('card_bot', xLeft), ab = ev('art_bot', xLeft);
    if (ct != null && at_ != null && cb != null && ab != null) {
      const top = Math.round(at_ - ct), bot = Math.round(cb - ab);
      meas.push({ position: 'tb_left', left_px: top, right_px: bot, ratio: ratioStr(top, bot) });
    }
  }

  // TB at right
  const xRight = ev('art_right', cy);
  if (xRight != null) {
    const ct = ev('card_top', xRight), at_ = ev('art_top', xRight);
    const cb = ev('card_bot', xRight), ab = ev('art_bot', xRight);
    if (ct != null && at_ != null && cb != null && ab != null) {
      const top = Math.round(at_ - ct), bot = Math.round(cb - ab);
      meas.push({ position: 'tb_right', left_px: top, right_px: bot, ratio: ratioStr(top, bot) });
    }
  }

  return meas;
}

// ── Main entry point ─────────────────────────────────────────────────────────

/**
 * Run the full CV centering pipeline on a loaded image.
 *
 * @param {HTMLCanvasElement|HTMLImageElement} source - Image to analyze
 * @param {string} cropMode - 'psa', 'cgc', or 'none'
 * @returns {{ lines, measurements, detections, crops, image_size, base_png_b64 }}
 */
function runCenteringCV(source, cropMode) {
  // Draw source to a temp canvas to get ImageData
  const tmpCanvas = document.createElement('canvas');
  let srcW, srcH;
  if (source instanceof HTMLCanvasElement) {
    srcW = source.width; srcH = source.height;
  } else {
    srcW = source.naturalWidth || source.width;
    srcH = source.naturalHeight || source.height;
  }
  tmpCanvas.width = srcW; tmpCanvas.height = srcH;
  const tmpCtx = tmpCanvas.getContext('2d');
  tmpCtx.drawImage(source, 0, 0);

  // Apply slab crop
  let x0 = 0, y0 = 0, x1 = srcW, y1 = srcH;
  if (cropMode !== 'none' && SLAB_CROPS[cropMode]) {
    const c = SLAB_CROPS[cropMode];
    x0 = Math.round(srcW * c.left);
    y0 = Math.round(srcH * c.top);
    x1 = Math.round(srcW * (1 - c.right));
    y1 = Math.round(srcH * (1 - c.bottom));
  }

  // Create cropped canvas
  const cw = x1 - x0, ch = y1 - y0;
  const cropCanvas = document.createElement('canvas');
  cropCanvas.width = cw; cropCanvas.height = ch;
  const cropCtx = cropCanvas.getContext('2d');
  cropCtx.drawImage(tmpCanvas, x0, y0, cw, ch, 0, 0, cw, ch);
  const imageData = cropCtx.getImageData(0, 0, cw, ch);

  // Get base64 of cropped image for display
  const basePngB64 = cropCanvas.toDataURL('image/png').split(',')[1];

  // Generate crops
  const crops = generateCrops(imageData, cw, ch);

  // Detect edges
  const detections = crops.map(c => detectCrop(c));

  // Reconstruct lines
  const lines = reconstructLines(detections, cw, ch);

  // Compute measurements
  const measurements = computeCenteringMeasurements(lines, cw, ch);

  // Build crop metadata for UI (matches backend format)
  const cropMeta = crops.map(c => ({
    name: c.name, x: c.offset[0], y: c.offset[1],
    w: c.size[0], h: c.size[1], scan_dir: c.scanDir,
  }));

  return {
    lines,
    measurements,
    detections,
    crops: cropMeta,
    image_size: { w: cw, h: ch },
    base_png_b64: basePngB64,
  };
}

// ── Perspective correction ───────────────────────────────────────────────────

/**
 * Solve the 3x3 homography matrix H that maps 4 source points to 4 dest points.
 * src/dst: arrays of 4 {x,y} objects. Returns a 9-element array [h0..h8] where
 * H = [[h0,h1,h2],[h3,h4,h5],[h6,h7,1]].
 */
function solveHomography(src, dst) {
  // Build the 8x8 system Ah = b
  const A = [], b = [];
  for (let i = 0; i < 4; i++) {
    const sx = src[i].x, sy = src[i].y, dx = dst[i].x, dy = dst[i].y;
    A.push([sx, sy, 1, 0, 0, 0, -dx*sx, -dx*sy]);
    b.push(dx);
    A.push([0, 0, 0, sx, sy, 1, -dy*sx, -dy*sy]);
    b.push(dy);
  }
  // Gaussian elimination
  const n = 8;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let col = 0; col < n; col++) {
    let maxR = col;
    for (let r = col + 1; r < n; r++) if (Math.abs(M[r][col]) > Math.abs(M[maxR][col])) maxR = r;
    [M[col], M[maxR]] = [M[maxR], M[col]];
    const pivot = M[col][col];
    if (Math.abs(pivot) < 1e-12) continue;
    for (let j = col; j <= n; j++) M[col][j] /= pivot;
    for (let r = 0; r < n; r++) {
      if (r === col) continue;
      const f = M[r][col];
      for (let j = col; j <= n; j++) M[r][j] -= f * M[col][j];
    }
  }
  const h = M.map(row => row[n]);
  return [...h, 1]; // h0..h7, h8=1
}

/**
 * Apply perspective warp: given a source image (as HTMLImageElement or Canvas),
 * 4 source corner points, and output dimensions, produce a new Canvas with the
 * warped result.
 *
 * @param {HTMLImageElement|HTMLCanvasElement} source
 * @param {Array<{x:number,y:number}>} srcCorners - [TL, TR, BR, BL] in source image coords
 * @param {number} dstW - output width
 * @param {number} dstH - output height
 * @returns {HTMLCanvasElement}
 */
function perspectiveWarp(source, srcCorners, dstW, dstH) {
  // Source canvas for pixel reading
  const srcCanvas = document.createElement('canvas');
  const sw = source.naturalWidth || source.width;
  const sh = source.naturalHeight || source.height;
  srcCanvas.width = sw; srcCanvas.height = sh;
  const srcCtx = srcCanvas.getContext('2d');
  srcCtx.drawImage(source, 0, 0);
  const srcData = srcCtx.getImageData(0, 0, sw, sh);
  const srcPx = srcData.data;

  // Destination corners: rectangle
  const dstCorners = [
    { x: 0, y: 0 },        // TL
    { x: dstW, y: 0 },     // TR
    { x: dstW, y: dstH },  // BR
    { x: 0, y: dstH },     // BL
  ];

  // Inverse homography: maps dst→src so we can sample source for each dest pixel
  const H = solveHomography(dstCorners, srcCorners);

  const dstCanvas = document.createElement('canvas');
  dstCanvas.width = dstW; dstCanvas.height = dstH;
  const dstCtx = dstCanvas.getContext('2d');
  const dstData = dstCtx.createImageData(dstW, dstH);
  const dstPx = dstData.data;

  for (let dy = 0; dy < dstH; dy++) {
    for (let dx = 0; dx < dstW; dx++) {
      // Map dest pixel to source via H
      const w = H[6] * dx + H[7] * dy + H[8];
      const sx = (H[0] * dx + H[1] * dy + H[2]) / w;
      const sy = (H[3] * dx + H[4] * dy + H[5]) / w;

      // Bilinear interpolation
      const x0 = Math.floor(sx), y0 = Math.floor(sy);
      const x1 = x0 + 1, y1 = y0 + 1;
      if (x0 < 0 || y0 < 0 || x1 >= sw || y1 >= sh) continue;

      const fx = sx - x0, fy = sy - y0;
      const i00 = (y0 * sw + x0) * 4;
      const i10 = (y0 * sw + x1) * 4;
      const i01 = (y1 * sw + x0) * 4;
      const i11 = (y1 * sw + x1) * 4;
      const di = (dy * dstW + dx) * 4;

      for (let c = 0; c < 4; c++) {
        dstPx[di + c] = Math.round(
          srcPx[i00+c]*(1-fx)*(1-fy) + srcPx[i10+c]*fx*(1-fy) +
          srcPx[i01+c]*(1-fx)*fy     + srcPx[i11+c]*fx*fy
        );
      }
    }
  }
  dstCtx.putImageData(dstData, 0, 0);
  return dstCanvas;
}

/**
 * Estimate output dimensions for perspective warp from 4 source corners.
 * Uses average of opposite edge lengths.
 */
function estimateWarpDimensions(corners) {
  const dist = (a, b) => Math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2);
  const wTop = dist(corners[0], corners[1]);
  const wBot = dist(corners[3], corners[2]);
  const hLeft = dist(corners[0], corners[3]);
  const hRight = dist(corners[1], corners[2]);
  return { w: Math.round((wTop + wBot) / 2), h: Math.round((hLeft + hRight) / 2) };
}

/**
 * Apply a 3x3 homography H (9-element array) to a single (x, y) point.
 * Returns the transformed {x, y}.
 */
function applyHomography(H, x, y) {
  const w = H[6] * x + H[7] * y + H[8];
  return {
    x: (H[0] * x + H[1] * y + H[2]) / w,
    y: (H[3] * x + H[4] * y + H[5]) / w,
  };
}

/**
 * Transform an edge-spanning line `{x0, y0, x1, y1, kind}` from source image
 * coords to warped image coords, then rebuild it as edge-spanning in the new
 * image (y=0..newH for vertical lines, x=0..newW for horizontal). Projective
 * transforms preserve straightness but not parallelism to axes, so we
 * extrapolate through the two transformed endpoints.
 */
function transformLineViaHomography(name, line, H, newW, newH) {
  const p0 = applyHomography(H, line.x0, line.y0);
  const p1 = applyHomography(H, line.x1, line.y1);
  const isVert = /_left$|_right$/.test(name);

  if (isVert) {
    const dy = p1.y - p0.y;
    if (Math.abs(dy) < 1e-6) {
      return { kind: line.kind, x0: p0.x, y0: 0, x1: p0.x, y1: newH };
    }
    const xAtY0 = p0.x + (p1.x - p0.x) * (0 - p0.y) / dy;
    const xAtYH = p0.x + (p1.x - p0.x) * (newH - p0.y) / dy;
    return { kind: line.kind, x0: xAtY0, y0: 0, x1: xAtYH, y1: newH };
  }

  const dx = p1.x - p0.x;
  if (Math.abs(dx) < 1e-6) {
    return { kind: line.kind, x0: 0, y0: p0.y, x1: newW, y1: p0.y };
  }
  const yAtX0 = p0.y + (p1.y - p0.y) * (0 - p0.x) / dx;
  const yAtXW = p0.y + (p1.y - p0.y) * (newW - p0.x) / dx;
  return { kind: line.kind, x0: 0, y0: yAtX0, x1: newW, y1: yAtXW };
}

/**
 * Transform CV detection point clouds through a homography. Preserves kept
 * indices and all other fields; only card_points / art_points move.
 */
function transformDetectionsViaHomography(detections, H) {
  if (!Array.isArray(detections)) return [];
  return detections.map(d => ({
    ...d,
    card_points: (d.card_points || []).map(([x, y]) => {
      const p = applyHomography(H, x, y);
      return [p.x, p.y];
    }),
    art_points: (d.art_points || []).map(([x, y]) => {
      const p = applyHomography(H, x, y);
      return [p.x, p.y];
    }),
  }));
}
