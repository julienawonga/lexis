// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

/** Shown when the web app answers 401: the session cookie is gone or expired. */
export const SESSION_EXPIRED_MESSAGE =
	'Your session has expired. Reload the page and sign in again; your question is still in the input.';

/**
 * The sentence to show for a chat request the server refused before streaming.
 *
 * The API answers `{"detail": "..."}`; the web app's own guards answer
 * `{"error": "Unauthorized"}`. Reading only `detail` put that second body on
 * screen as raw JSON.
 */
export const responseErrorMessage = (status: number, body: string): string => {
	if (status === 401) return SESSION_EXPIRED_MESSAGE;

	const fallback = `Server responded with ${status}`;
	const text = body.trim();
	if (!text) return fallback;

	try {
		const parsed: unknown = JSON.parse(text);
		if (parsed && typeof parsed === 'object') {
			const { detail, error } = parsed as { detail?: unknown; error?: unknown };
			if (typeof detail === 'string' && detail.trim()) return detail.trim();
			if (typeof error === 'string' && error.trim()) return error.trim();
			// A JSON body with no message we know how to read is not a sentence.
			return fallback;
		}
	} catch {
		// Not JSON: a plain-text body is already the message.
	}
	return text;
};
