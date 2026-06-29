import type { SpeakerLabels } from '../types';

/** Підпис спікера для показу: «Іван (PM)» / «Іван» / оригінальний токен, якщо не підписано. */
export function displaySpeaker(labels: SpeakerLabels | undefined, original: string): string {
  const l = labels?.[original];
  if (!l) return original;
  const name = (l.name || '').trim();
  const role = (l.role || '').trim();
  if (!name) return original;
  return role ? `${name} (${role})` : name;
}

// HITL-гейт — дзеркало порогів бекенду (entities.py: AUTO_OK=0.85, NEEDS_HUMAN=0.60).
export type Gate = 'auto' | 'review' | 'reject';

export function gateFor(confidence: number | null | undefined): Gate {
  const c = confidence ?? 0;
  if (c >= 0.85) return 'auto';
  if (c >= 0.6) return 'review';
  return 'reject';
}

export const GATE_META: Record<
  Gate,
  { label: string; tone: 'success' | 'warning' | 'danger'; hint: string }
> = {
  auto: { label: 'Авто-підтвердження', tone: 'success', hint: 'висока впевненість (≥ 0.85)' },
  review: { label: 'Потрібен перегляд', tone: 'warning', hint: 'середня впевненість (0.60–0.85)' },
  reject: { label: 'Відхилити / перегенерувати', tone: 'danger', hint: 'низька впевненість (< 0.60)' },
};

/** "local:neural-chat" -> «Локальна · neural-chat»; "cloud:gpt-4o-mini" -> «Хмара · gpt-4o-mini». */
export function engineLabel(engine: string | null): string {
  if (!engine) return '—';
  const [kind, model] = engine.split(':');
  const k = kind === 'cloud' ? 'Хмара' : 'Локальна';
  return model ? `${k} · ${model}` : k;
}

/** Прокрутити транскрипт до сегмента-джерела цитати [#N] (N 1-based -> DOM id seg-{N-1}). */
export function scrollToSegment(n: number): void {
  const el = document.getElementById(`seg-${n - 1}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('ring-2', 'ring-brand');
    window.setTimeout(() => el.classList.remove('ring-2', 'ring-brand'), 1600);
  }
}
