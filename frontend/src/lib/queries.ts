import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { api, type ApiError } from './api';
import { qk } from './queryKeys';
import { queryClient } from './queryClient';
import {
  ACTIVE_STATUSES,
  type HealthOut,
  type MeetingOut,
  type MeetingStatus,
  type ProjectIn,
  type ProjectOut,
  type SpeakerLabels,
  type SummaryEngine,
  type SummaryOut,
  type TranscriptOut,
  type UploadMeetingInput,
} from '../types';

// ---------------------------------------------------------------- health
export function useHealth(): UseQueryResult<HealthOut, ApiError> {
  return useQuery<HealthOut, ApiError>({
    queryKey: qk.health,
    queryFn: () => api.health(),
    refetchInterval: 30_000,
  });
}

// ---------------------------------------------------------------- projects
export function useProjects(): UseQueryResult<ProjectOut[], ApiError> {
  return useQuery<ProjectOut[], ApiError>({
    queryKey: qk.projects,
    queryFn: () => api.listProjects(),
  });
}

export function useProject(projectId: string): UseQueryResult<ProjectOut, ApiError> {
  return useQuery<ProjectOut, ApiError>({
    queryKey: qk.project(projectId),
    queryFn: () => api.getProject(projectId),
    enabled: !!projectId,
  });
}

export function useCreateProject(): UseMutationResult<ProjectOut, ApiError, ProjectIn> {
  const qc = useQueryClient();
  return useMutation<ProjectOut, ApiError, ProjectIn>({
    mutationFn: (body) => api.createProject(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.projects });
    },
  });
}

// ---------------------------------------------------------------- meetings (list, polls while any row active)
export function useMeetings(projectId: string): UseQueryResult<MeetingOut[], ApiError> {
  return useQuery<MeetingOut[], ApiError>({
    queryKey: qk.meetings(projectId),
    queryFn: () => api.listMeetings(projectId),
    enabled: !!projectId,
    refetchInterval: (q) =>
      q.state.data?.some((m) => ACTIVE_STATUSES.includes(m.status)) ? 5000 : false,
  });
}

// ---------------------------------------------------------------- meeting (detail, polls while active)
export function useMeeting(meetingId: string): UseQueryResult<MeetingOut, ApiError> {
  return useQuery<MeetingOut, ApiError>({
    queryKey: qk.meeting(meetingId),
    queryFn: () => api.getMeeting(meetingId),
    enabled: !!meetingId,
    refetchInterval: (q) =>
      q.state.data && ACTIVE_STATUSES.includes(q.state.data.status) ? 2500 : false,
  });
}

// ---------------------------------------------------------------- upload (multipart, exposes progress)
export function useUploadMeeting(
  projectId: string,
): UseMutationResult<
  MeetingOut,
  ApiError,
  { input: UploadMeetingInput; onProgress?: (pct: number) => void }
> {
  const qc = useQueryClient();
  return useMutation<
    MeetingOut,
    ApiError,
    { input: UploadMeetingInput; onProgress?: (pct: number) => void }
  >({
    mutationFn: ({ input, onProgress }) =>
      api.uploadMeeting(projectId, input, onProgress),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.meetings(projectId) });
    },
  });
}

// ---------------------------------------------------------------- transcribe / re-enqueue
export function useTranscribe(meetingId: string): UseMutationResult<MeetingOut, ApiError, void> {
  const qc = useQueryClient();
  return useMutation<MeetingOut, ApiError, void>({
    mutationFn: () => api.transcribe(meetingId),
    onSuccess: (updated) => {
      qc.setQueryData(qk.meeting(meetingId), updated);
      qc.invalidateQueries({ queryKey: qk.transcript(meetingId) });
      qc.invalidateQueries({ queryKey: qk.meetings(updated.project_id) });
    },
  });
}

// ---------------------------------------------------------------- transcript (gated on status; 404 = not-ready)
// staleTime drop: транскрипт майже незмінний, АЛЕ relabel оновлює speaker_labels на тому ж
// записі, тож тримаємо помірний staleTime і інвалідуємо вручну з useRelabel (нижче).
export function useTranscript(
  meetingId: string,
  status: MeetingStatus | undefined,
): UseQueryResult<TranscriptOut, ApiError> {
  return useQuery<TranscriptOut, ApiError>({
    queryKey: qk.transcript(meetingId),
    queryFn: () => api.getTranscript(meetingId),
    // транскрипт доступний у будь-якому пост-transcribed стані (ingesting/ingested теж)
    enabled: status === 'transcribed' || status === 'ingesting' || status === 'ingested',
    retry: false,
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------- relabel (підписи спікерів)
export function useRelabel(
  meetingId: string,
): UseMutationResult<TranscriptOut, ApiError, SpeakerLabels> {
  const qc = useQueryClient();
  return useMutation<TranscriptOut, ApiError, SpeakerLabels>({
    mutationFn: (labels) => api.relabel(meetingId, labels),
    onSuccess: (updated) => {
      qc.setQueryData(qk.transcript(meetingId), updated);   // миттєво показуємо нові підписи
    },
  });
}

// ---------------------------------------------------------------- summary: request (enqueue) + poll
export function useRequestSummary(
  meetingId: string,
): UseMutationResult<SummaryOut, ApiError, SummaryEngine> {
  const qc = useQueryClient();
  return useMutation<SummaryOut, ApiError, SummaryEngine>({
    mutationFn: (engine) => api.requestSummary(meetingId, engine),
    onSuccess: (summ) => {
      qc.setQueryData(qk.summary(meetingId), summ);          // одразу pending -> запускає polling
    },
  });
}

// Опитуємо доки рушій працює (status=pending). 404 (ще не генерували) -> не ретраїмо.
export function useSummary(
  meetingId: string,
  enabled = true,
): UseQueryResult<SummaryOut, ApiError> {
  return useQuery<SummaryOut, ApiError>({
    queryKey: qk.summary(meetingId),
    queryFn: () => api.getSummary(meetingId),
    enabled: !!meetingId && enabled,
    retry: (_count, err) => err.status !== 404,              // 404 = ще не запитували
    refetchInterval: (q) => (q.state.data?.status === 'pending' ? 3000 : false),
  });
}

// Re-export the singleton so callers can import from one module if desired.
export { queryClient };
