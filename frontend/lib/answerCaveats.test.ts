// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { buildSqlAnswerMessage } from './answerMessages';
import { extraCaveats } from './answerCaveats';

const skipped = { code: 'validation_skipped', message: 'A check could not run.' };
const unresolved = { code: 'validation_unresolved', message: 'Not fully validated.' };

describe('answer caveats', () => {
	it('carries the caveats of the answer onto the message', () => {
		const msg = buildSqlAnswerMessage({ response: 'ok', caveats: [skipped] });
		expect(msg?.caveats).toEqual([skipped]);
	});

	it('leaves caveats unset when the answer has none', () => {
		expect(buildSqlAnswerMessage({ response: 'ok', caveats: [] })?.caveats).toBeUndefined();
		expect(buildSqlAnswerMessage({ response: 'ok' })?.caveats).toBeUndefined();
	});

	it('does not list the unresolved caveat twice', () => {
		expect(extraCaveats({ caveats: [skipped, unresolved] })).toEqual([skipped]);
		expect(extraCaveats({})).toEqual([]);
	});
});
