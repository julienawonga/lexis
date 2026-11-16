// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

// How the web app's route handlers talk to the Python API when it misbehaves:
// a refused connection and a hung backend each answer a JSON `{"detail": ...}`
// the client wrapper already knows how to read, instead of a bare Next 500.

export const UPSTREAM_UNREACHABLE = 'The API is unreachable.';
export const UPSTREAM_TIMEOUT = 'The API did not answer in time.';

/** Time allowed for a plain request/response call, body included. */
export const PROXY_TIMEOUT_MS = 60_000;
/** Time allowed for a streaming call to start answering (headers only). */
export const STREAM_HEADERS_TIMEOUT_MS = 30_000;

const isTimeout = (err: unknown): boolean =>
	err instanceof Error && (err.name === 'TimeoutError' || err.name === 'AbortError');

/** The JSON answer for a failed upstream call: 504 on a timeout, 502 otherwise. */
export const upstreamFailure = (err: unknown): Response => {
	const timedOut = isTimeout(err);
	return Response.json(
		{ detail: timedOut ? UPSTREAM_TIMEOUT : UPSTREAM_UNREACHABLE },
		{ status: timedOut ? 504 : 502 },
	);
};

/** `Retry-After` from an upstream answer, as headers to merge into ours. */
export const retryAfterHeader = (upstream: Response): Record<string, string> => {
	const value = upstream.headers.get('retry-after');
	return value ? { 'Retry-After': value } : {};
};

/**
 * `fetch` that gives up when the headers have not arrived in `timeoutMs`, and
 * then leaves the body alone. For streams (chat completions, watch) a timer
 * over the whole response would cut a long answer off mid-run; the body ends
 * when the run does. Rejects with a `TimeoutError` when the timer fires.
 */
export const fetchUntilHeaders = async (
	url: string,
	init: RequestInit,
	timeoutMs = STREAM_HEADERS_TIMEOUT_MS,
): Promise<Response> => {
	const controller = new AbortController();
	const timer = setTimeout(
		() => controller.abort(new DOMException('Timed out', 'TimeoutError')),
		timeoutMs,
	);
	try {
		return await fetch(url, { ...init, signal: controller.signal });
	} finally {
		clearTimeout(timer);
	}
};

/** Seconds from a `Retry-After` header value (delta-seconds form), or null. */
export const parseRetryAfterSeconds = (value: string | null | undefined): number | null => {
	if (!value || !/^\d+$/.test(value.trim())) return null;
	const seconds = Number(value.trim());
	return seconds > 0 ? seconds : null;
};

/** The sentence for a busy chat that says when to come back. */
export const busyMessage = (seconds: number): string =>
	`The chat is busy; try again in ${seconds} ${seconds === 1 ? 'second' : 'seconds'}.`;
