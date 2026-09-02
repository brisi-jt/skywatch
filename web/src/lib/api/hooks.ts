"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  api,
  asProblem,
  type ProblemDetail,
  type RecordingListResponse,
  type TuningApplyRequest,
} from "./client";

export class ApiError extends Error {
  problem: ProblemDetail | null;
  status: number;

  constructor(status: number, problem: ProblemDetail | null) {
    super(problem?.detail ?? `Request failed (${status})`);
    this.status = status;
    this.problem = problem;
  }
}

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

function unwrap<T>(result: FetchResult<T>): T {
  if (result.data === undefined) {
    throw new ApiError(result.response.status, asProblem(result.error));
  }
  return result.data;
}

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: async () => {
      const result = await api.GET("/status");
      return unwrap(result);
    },
    refetchInterval: 30_000,
  });
}

export function useFrequencies() {
  return useQuery({
    queryKey: ["frequencies"],
    queryFn: async () => {
      const result = await api.GET("/frequencies");
      return unwrap(result);
    },
  });
}

export function useDigest(date: string) {
  return useQuery({
    queryKey: ["digest", date],
    queryFn: async () => {
      const result = await api.GET("/digest", {
        params: { query: { date } },
      });
      return unwrap(result);
    },
  });
}

/** True once any recording has ever been captured — the day-one signal. */
export function useHasAnyRecording() {
  return useQuery({
    queryKey: ["recordings-any"],
    queryFn: async () => {
      const result = await api.GET("/recordings", {
        params: { query: { limit: 1 } },
      });
      return unwrap(result).total > 0;
    },
  });
}

export interface ClipFilters {
  from_date?: string;
  to_date?: string;
  freq_id?: number;
  interesting?: true;
  category?: string;
  has_match?: true;
}

const PAGE_SIZE = 20;

export function useRecordings(filters: ClipFilters) {
  return useInfiniteQuery({
    queryKey: ["recordings", filters],
    queryFn: async ({ pageParam }) => {
      const result = await api.GET("/recordings", {
        params: {
          query: {
            ...filters,
            category: filters.category as never,
            limit: PAGE_SIZE,
            offset: pageParam,
          },
        },
      });
      return unwrap(result);
    },
    initialPageParam: 0,
    getNextPageParam: (last: RecordingListResponse) => {
      const next = last.offset + last.items.length;
      return next < last.total ? next : undefined;
    },
  });
}

/** A clip's waveform peaks for the scrubber; cached indefinitely per clip. */
export function usePeaks(id: number | null) {
  return useQuery({
    queryKey: ["peaks", id],
    queryFn: async () => {
      const result = await api.GET("/recordings/{recording_id}/peaks", {
        params: { path: { recording_id: id! } },
      });
      return unwrap(result);
    },
    enabled: id != null,
    staleTime: Infinity,
    retry: false,
  });
}

export function useRecordingDetail(id: number, enabled: boolean) {
  return useQuery({
    queryKey: ["recording", id],
    queryFn: async () => {
      const result = await api.GET("/recordings/{recording_id}", {
        params: { path: { recording_id: id } },
      });
      return unwrap(result);
    },
    enabled,
  });
}

export function useDocument(name: "runbook" | "glossary") {
  return useQuery({
    queryKey: ["document", name],
    queryFn: async () => {
      const result = await api.GET(name === "runbook" ? "/runbook" : "/glossary");
      return unwrap(result);
    },
    staleTime: 5 * 60_000,
  });
}

export function useFrequencyAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { freqId: number; action: "activate" | "deactivate" }) => {
      const path =
        input.action === "activate"
          ? ("/frequencies/{freq_id}/activate" as const)
          : ("/frequencies/{freq_id}/deactivate" as const);
      const result = await api.POST(path, {
        params: { path: { freq_id: input.freqId } },
      });
      return unwrap(result);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["frequencies"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
}

export function useFeedback() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { recordingId: number; verdict: "up" | "down" }) => {
      const result = await api.POST("/recordings/{recording_id}/feedback", {
        params: { path: { recording_id: input.recordingId } },
        body: { verdict: input.verdict },
      });
      return unwrap(result);
    },
    onSuccess: (_data, input) => {
      queryClient.invalidateQueries({ queryKey: ["recording", input.recordingId] });
      queryClient.invalidateQueries({ queryKey: ["recordings"] });
      queryClient.invalidateQueries({ queryKey: ["digest"] });
    },
  });
}

export function useReclassify() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (recordingId: number) => {
      const result = await api.POST("/recordings/{recording_id}/reclassify", {
        params: { path: { recording_id: recordingId } },
      });
      return unwrap(result);
    },
    onSuccess: (_data, recordingId) => {
      queryClient.invalidateQueries({ queryKey: ["recording", recordingId] });
      // a re-look can flip the verdict, so the lists and today's digest that
      // render it must refetch too
      queryClient.invalidateQueries({ queryKey: ["recordings"] });
      queryClient.invalidateQueries({ queryKey: ["digest"] });
    },
  });
}

export function useSaveSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: Record<string, string>) => {
      const result = await api.PATCH("/settings", { body: payload });
      return unwrap(result);
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["status"] });
      queryClient.setQueryData(["settings"], data);
    },
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: async () => {
      const result = await api.GET("/settings");
      return unwrap(result);
    },
  });
}

// -- tuning bench -------------------------------------------------------------------

export function useTuning() {
  return useQuery({
    queryKey: ["tuning"],
    queryFn: async () => {
      const result = await api.GET("/tuning");
      return unwrap(result);
    },
  });
}

/** Live meters, polled at the capture process's own 15 s stats cadence. */
export function useTuningMeters() {
  return useQuery({
    queryKey: ["tuning-meters"],
    queryFn: async () => {
      const result = await api.GET("/tuning/meters");
      return unwrap(result);
    },
    refetchInterval: 15_000,
  });
}

export function useApplyTuning() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: TuningApplyRequest) => {
      const result = await api.POST("/tuning/apply", { body: payload });
      return unwrap(result);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["tuning"], data);
      queryClient.invalidateQueries({ queryKey: ["tuning-meters"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
}

export function useSaveBaseline() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const result = await api.POST("/tuning/baseline");
      return unwrap(result);
    },
    onSuccess: (data) => {
      queryClient.setQueryData(["tuning"], data);
    },
  });
}

// -- deep tune sessions ---------------------------------------------------------------

export function useStartDeepTune() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const result = await api.POST("/tuning/deep-tune/start");
      return unwrap(result);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["tuning"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
    },
  });
}

export function useStopDeepTune() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const result = await api.POST("/tuning/deep-tune/stop");
      return unwrap(result);
    },
    onSettled: () => {
      // the stop endpoint returns after capture is already restarted
      queryClient.invalidateQueries({ queryKey: ["tuning"] });
      queryClient.invalidateQueries({ queryKey: ["status"] });
      queryClient.invalidateQueries({ queryKey: ["tuning-meters"] });
    },
  });
}

/** Interaction keep-alive; callers throttle, the server resets its countdown. */
export function usePingDeepTune() {
  return useMutation({
    mutationFn: async () => {
      const result = await api.POST("/tuning/deep-tune/ping");
      return unwrap(result);
    },
  });
}
