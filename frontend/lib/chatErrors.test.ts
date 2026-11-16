// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { SESSION_EXPIRED_MESSAGE, responseErrorMessage } from './chatErrors';

describe('responseErrorMessage', () => {
	it('reads the API detail', () => {
		expect(responseErrorMessage(503, '{"detail":"The chat is busy, retry shortly."}')).toBe(
			'The chat is busy, retry shortly.',
		);
	});

	it('reads the web app guard error instead of showing its JSON', () => {
		expect(responseErrorMessage(403, '{"error":"Forbidden"}')).toBe('Forbidden');
	});

	it('explains an expired session whatever the body says', () => {
		expect(responseErrorMessage(401, '{"error":"Unauthorized"}')).toBe(SESSION_EXPIRED_MESSAGE);
		expect(responseErrorMessage(401, '')).toBe(SESSION_EXPIRED_MESSAGE);
	});

	it('keeps a plain-text body as the message', () => {
		expect(responseErrorMessage(502, 'Upstream responded with 502')).toBe(
			'Upstream responded with 502',
		);
	});

	it('falls back to the status for an empty or unreadable JSON body', () => {
		expect(responseErrorMessage(500, '  ')).toBe('Server responded with 500');
		expect(responseErrorMessage(500, '{"detail":[{"msg":"x"}]}')).toBe(
			'Server responded with 500',
		);
	});
});
