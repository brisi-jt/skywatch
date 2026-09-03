import createClient from "openapi-fetch";
import type { components, paths } from "./types.gen";

/**
 * The dashboard is served by the station API itself, so requests default to
 * the same origin. `NEXT_PUBLIC_API_BASE` overrides that during `bun dev`,
 * where the Next dev server and the API run on different ports.
 */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export const api = createClient<paths>({ baseUrl: API_BASE || "/" });

export type Schemas = components["schemas"];
export type RecordingSummary = Schemas["RecordingSummary"];
export type RecordingDetail = Schemas["RecordingDetail"];
export type RecordingStage = Schemas["RecordingStage"];
export type FrequencyResource = Schemas["FrequencyResource"];
export type FrequencyRef = Schemas["FrequencyRef"];
export type StatusResponse = Schemas["StatusResponse"];
export type DigestResponse = Schemas["DigestResponse"];
export type ClassificationResource = Schemas["ClassificationResource"];
export type ClassificationCategory = Schemas["ClassificationCategory"];
export type AircraftMatchResource = Schemas["AircraftMatchResource"];
export type TranscriptResource = Schemas["TranscriptResource"];
export type ProblemDetail = Schemas["ProblemDetail"];
export type RecordingListResponse = Schemas["RecordingListResponse"];
export type SettingsResponse = Schemas["SettingsResponse"];
export type DocumentResponse = Schemas["DocumentResponse"];
export type BudgetInfo = Schemas["BudgetInfo"];
export type TuningResponse = Schemas["TuningResponse"];
export type TuningApplyRequest = Schemas["TuningApplyRequest"];
export type TuningApplyResponse = Schemas["TuningApplyResponse"];
export type AppliedTuning = Schemas["AppliedTuning"];
export type FactoryTuning = Schemas["FactoryTuning"];
export type SquelchOverride = Schemas["SquelchOverride"];
export type MetersResponse = Schemas["MetersResponse"];
export type ChannelMeter = Schemas["ChannelMeter"];
export type DeepTuneState = Schemas["DeepTuneState"];
export type StatsResponse = Schemas["StatsResponse"];
export type DailyMovementCount = Schemas["DailyMovementCount"];
export type HourlyHeatCell = Schemas["HourlyHeatCell"];
export type AirlineCount = Schemas["AirlineCount"];
export type NotableDay = Schemas["NotableDay"];
export type NotableDaysResponse = Schemas["NotableDaysResponse"];
export type EvalFeedbackResponse = Schemas["EvalFeedbackResponse"];
export type EvalDisagreement = Schemas["EvalDisagreement"];
export type SkyResponse = Schemas["SkyResponse"];
export type SkyAircraftResource = Schemas["SkyAircraftResource"];
export type SkySource = Schemas["SkySource"];
export type StarResponse = Schemas["StarResponse"];
export type IncidentSummary = Schemas["IncidentSummary"];
export type IncidentListResponse = Schemas["IncidentListResponse"];
export type IncidentDetail = Schemas["IncidentDetail"];
export type IncidentClipResource = Schemas["IncidentClipResource"];
export type HealthHistoryResponse = Schemas["HealthHistoryResponse"];
export type HeartbeatResource = Schemas["HeartbeatResource"];

export function audioUrl(recordingId: number): string {
  return `${API_BASE}/recordings/${recordingId}/audio`;
}

export function wsUrl(): string {
  const base =
    API_BASE || (typeof window !== "undefined" ? window.location.origin : "");
  return base.replace(/^http/, "ws") + "/stream";
}

/** Narrow an unknown error payload to an RFC 7807 problem detail. */
export function asProblem(value: unknown): ProblemDetail | null {
  if (
    value &&
    typeof value === "object" &&
    "code" in value &&
    "detail" in value
  ) {
    return value as ProblemDetail;
  }
  return null;
}
