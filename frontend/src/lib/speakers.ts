import type { Segment } from '../types';

// 8-hue palette — mirrors tailwind.config `colors.spk.0..7`.
const SPK_PALETTE = [
  '#38bdf8',
  '#a78bfa',
  '#34d399',
  '#fbbf24',
  '#fb7185',
  '#22d3ee',
  '#f472b6',
  '#818cf8',
] as const;

const PALETTE_LEN = SPK_PALETTE.length;

/** Deterministic small hash → non-negative int (djb2). */
function hashLabel(label: string): number {
  let h = 5381;
  for (let i = 0; i < label.length; i++) {
    h = (h * 33) ^ label.charCodeAt(i);
  }
  return Math.abs(h | 0);
}

/**
 * "Speaker 3" -> 3 (parse trailing digits). Falls back to a stable hash of the
 * label so unknown formats still map deterministically.
 */
export function speakerIndex(label: string): number {
  const m = label.match(/(\d+)\s*$/);
  if (m) {
    return parseInt(m[1], 10);
  }
  return hashLabel(label);
}

/**
 * Stable palette slot for a speaker label across meetings (8 hues).
 * Returns inline colors for dot / text / border so callers can use style props
 * (the palette is dynamic per speaker and cannot be a static Tailwind class).
 */
export function speakerToken(label: string): { dot: string; text: string; border: string } {
  const slot = ((speakerIndex(label) % PALETTE_LEN) + PALETTE_LEN) % PALETTE_LEN;
  const hue = SPK_PALETTE[slot];
  return { dot: hue, text: hue, border: hue };
}

/** Distinct speaker labels in first-appearance order. */
export function distinctSpeakers(segments: Segment[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const seg of segments) {
    if (!seen.has(seg.speaker)) {
      seen.add(seg.speaker);
      out.push(seg.speaker);
    }
  }
  return out;
}
