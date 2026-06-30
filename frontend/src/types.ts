// ---- API contract (matches FastAPI exactly) ----
export type MeetingStatus =
  | 'uploaded'
  | 'transcribing'
  | 'transcribed'
  | 'ingesting'
  | 'ingested'
  | 'failed';

export interface HealthOut {
  status: 'ok' | 'degraded';
  app: string;
  components: { postgres: boolean; redis: boolean; qdrant: boolean };
}

export interface ProjectIn {
  slug: string;
  name: string;
  description?: string | null;
}

export interface ProjectOut {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  created_at: string;
}

export interface MeetingOut {
  id: string;
  project_id: string;
  title: string;
  filename: string;
  content_type: string | null;
  size_bytes: number;
  consent: boolean;
  status: MeetingStatus;
  error: string | null;
  created_at: string;
}

export interface Segment {
  speaker: string;
  start: number;
  end: number;
  text: string;
}

/** Relabel: original speaker token → display name + role. */
export interface SpeakerLabel {
  name: string;
  role: string;
}
export type SpeakerLabels = Record<string, SpeakerLabel>;

export interface TranscriptOut {
  meeting_id: string;
  language: string | null;
  model: string;
  diarizer: string | null;
  glossary: boolean;
  num_speakers: number;
  duration_s: number;
  compute_secs: number | null;
  segments: Segment[];
  speaker_labels: SpeakerLabels;
  created_at: string;
}

// Allowed upload extensions (mirror server; lowercase, with dot)
export const ALLOWED_EXT = ['.wav', '.mp4', '.m4a', '.mp3', '.webm', '.ogg', '.flac'] as const;
export type AllowedExt = (typeof ALLOWED_EXT)[number];

// Non-terminal statuses that should keep polling
export const ACTIVE_STATUSES: readonly MeetingStatus[] = [
  'uploaded',
  'transcribing',
  'ingesting',
];

// Upload form input (UI-side)
export interface UploadMeetingInput {
  file: File;
  title?: string;
  consent: boolean;
}

// ---- FUTURE seams (declared now; backend not shipped — never fetched today) ----
export interface Citation {
  n: number;
  segment_index: number;
  start: number;
  end: number;
  quote?: string;
}

// ---- Summary (Агент-2, Фаза 7) — real backend contract ----
export type SummaryEngine = 'local' | 'cloud';      // приватність зустрічі -> рушій
export type SummaryJobStatus = 'pending' | 'ready' | 'failed';

export interface ActionItemOut {
  owner?: string | null;
  task?: string;
  deadline?: string | null;
  citations?: number[];
}
export interface DecisionOut {
  decision?: string;
  citations?: number[];
}
export interface RiskOut {
  item?: string;
  citations?: number[];
}

export interface SummaryOut {
  meeting_id: string;
  project_id: string;
  summary: string;
  action_items: ActionItemOut[];
  decisions: DecisionOut[];
  risks: RiskOut[];
  confidence: number | null;
  engine: string | null;              // "local:neural-chat" / "cloud:gpt-4o-mini"
  status: SummaryJobStatus;
  error: string | null;
  updated_at: string;
}

// ---- Ask / retrieval (Фаза 5) — Q&A до памʼяті проєкту ----
export type AskEngine = 'local' | 'cloud';
export type AskJobStatus = 'pending' | 'ready' | 'failed';

export interface AskCitation {
  n: number;
  meeting_id: string | null;
  title: string | null;
  date: string | null;
  speaker: string | null;
  start: number | null;
  end: number | null;
  score: number;
  text: string;
}

export interface AskOut {
  id: string;
  project_id: string;
  question: string;
  answer: string;
  citations: AskCitation[];
  abstained: boolean;
  engine: string | null;
  status: AskJobStatus;
  error: string | null;
  created_at: string;
}

export type ApprovalKind = 'jira' | 'slack' | 'email' | 'note';
export type ApprovalStatus =
  | 'proposed'
  | 'approved'
  | 'rejected'
  | 'executed'
  | 'failed'
  | 'expired';

export interface ProposedAction {
  id: string;
  project_id: string;
  meeting_id: string | null;
  kind: ApprovalKind;
  title: string;
  payload: Record<string, unknown>;
  rationale: string;
  citations: AskCitation[];        // ask-стиль джерела {n, meeting_id, title, speaker, ...}
  status: ApprovalStatus;
  result: string | null;
  created_at: string;
}

// ---- Agent run (Фаза 6) ----
export interface AgentRunOut {
  id: string;
  project_id: string;
  goal: string;
  meeting_id: string | null;
  engine: string | null;
  status: AskJobStatus;            // pending | ready | failed
  n_proposed: number;
  error: string | null;
  created_at: string;
}
