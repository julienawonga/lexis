// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

/** Where to go after sign-in when `next` is missing or not a safe path. */
export const DEFAULT_NEXT = '/chat';

/**
 * `next` from the URL, kept only if it is a path on this site.
 *
 * `/login?next=https://evil.example` would otherwise send a freshly signed-in
 * user to another origin. Accepted: a string starting with exactly one `/`.
 * Rejected: `//host` and `/\host` (browsers read both as a host), absolute and
 * `javascript:` URLs, and anything with a control character or backslash.
 */
export const safeNext = (value: string | null | undefined, fallback = DEFAULT_NEXT): string => {
	if (!value || !value.startsWith('/')) return fallback;
	if (value.startsWith('//') || value.startsWith('/' + String.fromCharCode(92))) return fallback;
	for (const ch of value) {
		const code = ch.charCodeAt(0);
		if (code <= 0x1f || code === 0x7f || code === 0x5c) return fallback;
	}
	return value;
};
