import { useCallback, useState } from 'react';
import { Check, UsersRound } from 'lucide-react';

import { speakerToken } from '../lib/speakers';
import { useRelabel } from '../lib/queries';
import type { SpeakerLabels } from '../types';
import { Button, Card, Input, useToast } from './ui';

interface SpeakerRelabelProps {
  meetingId: string;
  speakers: string[];          // оригінальні токени («Speaker 1»…) у порядку появи
  labels: SpeakerLabels;       // поточні підписи (для seed форми)
}

type Form = Record<string, { name: string; role: string }>;

/** Панель підписів спікерів: «Speaker N» -> імʼя + роль. Зберігає недеструктивно (relabel). */
export function SpeakerRelabel({ meetingId, speakers, labels }: SpeakerRelabelProps) {
  const { toast } = useToast();
  const relabel = useRelabel(meetingId);

  const [form, setForm] = useState<Form>(() => {
    const init: Form = {};
    for (const s of speakers) {
      init[s] = { name: labels[s]?.name ?? '', role: labels[s]?.role ?? '' };
    }
    return init;
  });

  const set = useCallback((spk: string, field: 'name' | 'role', value: string) => {
    setForm((prev) => ({ ...prev, [spk]: { ...prev[spk], [field]: value } }));
  }, []);

  const onSave = useCallback(() => {
    const payload: SpeakerLabels = {};
    for (const s of speakers) {
      const f = form[s];
      const name = (f?.name ?? '').trim();
      const role = (f?.role ?? '').trim();
      if (name || role) payload[s] = { name, role };
    }
    relabel.mutate(payload, {
      onSuccess: () =>
        toast({
          title: 'Підписи збережено',
          description: 'Спікерів підписано — резюме використає імена.',
          tone: 'success',
        }),
      onError: (err) =>
        toast({
          title: 'Не вдалося зберегти підписи',
          description: err.detail || 'Спробуйте ще раз.',
          tone: 'danger',
        }),
    });
  }, [form, speakers, relabel, toast]);

  if (speakers.length === 0) return null;

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <UsersRound className="h-4 w-4 text-brand" aria-hidden="true" />
        <h2 className="text-sm font-semibold text-fg">Підписати спікерів</h2>
        <span className="text-xs text-muted">імена застосуються до резюме</span>
      </div>

      <div className="flex flex-col gap-2.5">
        {speakers.map((spk) => {
          const tok = speakerToken(spk);
          return (
            <div
              key={spk}
              className="grid grid-cols-[auto_1fr_1fr] items-center gap-2 sm:grid-cols-[7rem_1fr_1fr]"
            >
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-muted">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: tok.dot }}
                  aria-hidden="true"
                />
                <span className="truncate" title={spk}>
                  {spk}
                </span>
              </span>
              <Input
                placeholder="Імʼя"
                aria-label={`Імʼя для ${spk}`}
                value={form[spk]?.name ?? ''}
                onChange={(e) => set(spk, 'name', e.target.value)}
                disabled={relabel.isPending}
              />
              <Input
                placeholder="Роль (напр. PM)"
                aria-label={`Роль для ${spk}`}
                value={form[spk]?.role ?? ''}
                onChange={(e) => set(spk, 'role', e.target.value)}
                disabled={relabel.isPending}
              />
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex justify-end">
        <Button
          variant="secondary"
          size="sm"
          icon={Check}
          loading={relabel.isPending}
          onClick={onSave}
        >
          Зберегти підписи
        </Button>
      </div>
    </Card>
  );
}

export default SpeakerRelabel;
