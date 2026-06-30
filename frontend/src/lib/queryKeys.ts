export const qk = {
  health: ['health'] as const,
  projects: ['projects'] as const,
  project: (id: string) => ['projects', id] as const,
  meetings: (pid: string) => ['projects', pid, 'meetings'] as const,
  meeting: (mid: string) => ['meetings', mid] as const,
  transcript: (mid: string) => ['meetings', mid, 'transcript'] as const,
  summary: (mid: string) => ['meetings', mid, 'summary'] as const,
  ask: (askId: string) => ['ask', askId] as const,
  // FUTURE (reserved):
  // approvals: (pid: string) => ['projects', pid, 'approvals'] as const,
};
