// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { createLatestGuard } from './latestRequest';

describe('createLatestGuard', () => {
	it('accepts the only request', () => {
		const guard = createLatestGuard();
		expect(guard.isCurrent(guard.start())).toBe(true);
	});

	it('rejects an older request once a newer one started', () => {
		const guard = createLatestGuard();
		const first = guard.start();
		const second = guard.start();
		expect(guard.isCurrent(first)).toBe(false);
		expect(guard.isCurrent(second)).toBe(true);
	});

	it('rejects a request in flight after invalidate, as when a field is edited', () => {
		const guard = createLatestGuard();
		const ticket = guard.start();
		guard.invalidate();
		expect(guard.isCurrent(ticket)).toBe(false);
	});
});
