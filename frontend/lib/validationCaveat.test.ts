// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { hasValidationCaveat } from './validationCaveat';

const NOTE =
	'> **Note:** Automatic validation kept rejecting alternative versions of this query for ' +
	'conflicting reasons, so this answer was not fully validated. Check the SQL before relying on it.';

describe('hasValidationCaveat', () => {
	it('finds the engine note appended to an answer', () => {
		expect(hasValidationCaveat(`Some explanation.\n\n${NOTE}`)).toBe(true);
	});

	it('finds it when the sentence is wrapped over two lines', () => {
		expect(hasValidationCaveat('so this answer was not fully\nvalidated.')).toBe(true);
	});

	it('ignores ordinary answers, empty text and missing text', () => {
		expect(hasValidationCaveat('The query sums revenue per store.')).toBe(false);
		expect(hasValidationCaveat('')).toBe(false);
		expect(hasValidationCaveat(undefined)).toBe(false);
		expect(hasValidationCaveat(null)).toBe(false);
	});
});
