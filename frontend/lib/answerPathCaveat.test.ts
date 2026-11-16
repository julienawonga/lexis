// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '@/types/chat';
import { pathSteps } from './answerPath';

const base: ChatMessage = {
	id: 'm1',
	role: 'assistant',
	content: 'Revenue per store is not in the schema.',
	sql: 'SELECT 1;',
	timestamp: 1,
	steps: [{ node: 'construct_sql_from_candidates', label: 'SQL', status: 'completed' }],
};

const caveat =
	'\n\n> **Note:** Automatic validation kept rejecting alternative versions of this query for ' +
	'conflicting reasons, so this answer was not fully validated. Check the SQL before relying on it.';

const sqlStep = (message: ChatMessage) => pathSteps(message).find((step) => step.id === 'sql')!;

describe('pathSteps and the validation caveat', () => {
	it('says the SQL was not fully validated when the engine appended its note', () => {
		expect(sqlStep({ ...base, content: base.content + caveat }).summary).toBe(
			'not fully validated',
		);
	});

	it('puts the caveat before a correction or an attempt count', () => {
		const message: ChatMessage = {
			...base,
			content: base.content + caveat,
			steps: [{ node: 'reconstruct_sql', label: 'Fix', status: 'completed' }],
		};
		expect(sqlStep(message).summary).toBe('not fully validated');
	});

	it('leaves an ordinary answer as it was', () => {
		expect(sqlStep(base).summary).toBe('1 attempt');
	});
});
