// ---- API contract (matches FastAPI exactly) ----
export type MeetingStatus = 'uploaded' | 'transcribing' | 'transcribed' | 'failed';

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
  created_at: string;
}

// Allowed upload extensions (mirror server; lowercase, with dot)
export const ALLOWED_EXT = ['.wav', '.mp4', '.m4a', '.mp3', '.webm', '.ogg', '.flac'] as const;
export type AllowedExt = (typeof ALLOWED_EXT)[number];

// Non-terminal statuses that should keep polling
export const ACTIVE_STATUSES: readonly MeetingStatus[] = ['uploaded', 'transcribing'];

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

export type SummaryStatus = 'draft' | 'awaiting_review' | 'approved' | 'rejected';

export interface SummaryOut {
  meeting_id: string;
  markdown: string;
  citations: Citation[];
  confidence: number;
  status: SummaryStatus;
  created_at: string;
}

export type ApprovalKind = 'jira' | 'slack';
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
  citations: Citation[];
  status: ApprovalStatus;
  result: string | null;
  created_at: string;
}
