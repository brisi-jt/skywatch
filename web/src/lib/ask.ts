/** Ask-AI question box: request shaping and error-message mapping.
 *
 * Kept out of the component so the request/response handling can be tested
 * without rendering anything.
 */

import { ApiError } from "@/lib/api/hooks";

/** Mirrors the backend's `AskRequest.question` limit. */
export const MAX_QUESTION_LENGTH = 300;

/** Trims a raw question box value; `null` when there is nothing to ask. */
export function sanitizeQuestion(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return trimmed.slice(0, MAX_QUESTION_LENGTH);
}

/** Retry countdown (seconds) carried on a 429 problem, or null when absent. */
export function retryAfterSeconds(error: unknown): number | null {
  if (!(error instanceof ApiError)) return null;
  const value = (error.problem as { retry_after_s?: unknown } | null)?.retry_after_s;
  return typeof value === "number" && value > 0 ? value : null;
}

/** A short, honest message for whatever went wrong asking a question. */
export function askErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      const retry = retryAfterSeconds(error);
      return retry
        ? `Asked again too soon — try again in ${retry}s.`
        : "Asked again too soon — try again in a moment.";
    }
    if (error.status === 503) {
      return "The station can't answer right now — the model budget may be used up until it resets.";
    }
    if (error.status === 422) {
      return "That doesn't look like a question.";
    }
  }
  return "Something went wrong asking that. Try again in a moment.";
}
