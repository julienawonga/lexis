// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { buildSqlAnswerMessage } from '@/lib/answerMessages';
import {
	canDo,
	eventLabel,
	isVersionConflict,
	itemBody,
	itemDatabase,
	itemTitle,
	learnedTermLine,
	parseLearnedTerm,
	proposerLabel,
	provenanceLabel,
	provenanceTime,
	statusLabel,
	termFormError,
} from '@/lib/knowledge';

describe('isVersionConflict', () => {
	it('recognises the server message for a lost lock', () => {
		expect(
			isVersionConflict(
				"Knowledge item 'k' changed since it was loaded (you saw version 1, it is now version 2)",
			),
		).toBe(true);
	});
	it('does not mistake another conflict or no message for it', () => {
		expect(isVersionConflict('cannot approve an item that is draft')).toBe(false);
		expect(isVersionConflict(undefined)).toBe(false);
	});
});

describe('item text', () => {
	const term = {
		kind: 'term' as const,
		content: { name: ' VIP ', definition: ' spends a lot ', database: 'shop' },
	};
	const synonym = {
		kind: 'synonym' as const,
		content: { term: 'Revenue', synonyms: ['sales', ' turnover ', 3] },
	};
	it('reads a term', () => {
		expect(itemTitle(term)).toBe('VIP');
		expect(itemBody(term)).toBe('spends a lot');
		expect(itemDatabase(term)).toBe('shop');
	});
	it('reads a synonym', () => {
		expect(itemTitle(synonym)).toBe('Revenue');
		expect(itemBody(synonym)).toBe('sales, turnover');
		expect(itemDatabase(synonym)).toBeNull();
	});
	it('survives an empty content', () => {
		expect(itemTitle({ kind: 'term', content: {} })).toBe('Untitled');
		expect(itemBody({ kind: 'synonym', content: {} })).toBe('');
	});
});

describe('provenance', () => {
	it('says how a clarification answer was given', () => {
		expect(provenanceLabel({ source: 'clarification', option_id: 'a' })).toContain(
			'chose an option',
		);
		expect(provenanceLabel({ source: 'clarification', free_text: true })).toContain(
			'typed an answer',
		);
	});
	it('names a manual item and an unknown source', () => {
		expect(provenanceLabel({ source: 'manual' })).toBe('Written by hand');
		expect(provenanceLabel({})).toBe('Source not recorded');
	});
	it('returns a time only when it parses', () => {
		expect(provenanceTime({ asked_at: '2026-11-17T09:00:00+00:00' }, 'asked_at')).toBe(
			'2026-11-17T09:00:00+00:00',
		);
		expect(provenanceTime({ asked_at: 'not a date' }, 'asked_at')).toBeNull();
		expect(provenanceTime({}, 'answered_at')).toBeNull();
	});
});

describe('history and labels', () => {
	it('names the person, then Lexis for an agent', () => {
		expect(
			eventLabel({
				action: 'submit',
				actor_type: 'user',
				actor_email: 'a@b.c',
				actor_id: 'u1',
			}),
		).toBe('Submitted for review by a@b.c');
		expect(
			eventLabel({
				action: 'propose',
				actor_type: 'user',
				actor_email: null,
				actor_id: 'u1',
			}),
		).toBe('Created by u1');
		expect(
			eventLabel({
				action: 'propose',
				actor_type: 'agent',
				actor_email: null,
				actor_id: 'x',
			}),
		).toBe('Created by Lexis');
	});
	it('labels statuses plainly', () => {
		expect(statusLabel('certified')).toBe('Approved');
		expect(statusLabel('deprecated')).toBe('Withdrawn');
	});
	it('falls back to the id when a proposer has no email', () => {
		expect(proposerLabel({ owner_email: null, owner_id: 'u9' })).toBe('u9');
		expect(proposerLabel({ owner_email: 'a@b.c', owner_id: 'u9' })).toBe('a@b.c');
	});
	it('reads what the server allows', () => {
		expect(canDo({ allowed_actions: ['edit', 'submit'] }, 'submit')).toBe(true);
		expect(canDo({ allowed_actions: ['edit'] }, 'approve')).toBe(false);
	});
});

describe('termFormError', () => {
	it('accepts a complete form', () => {
		expect(termFormError({ name: 'VIP', definition: 'spends a lot' })).toBeNull();
	});
	it('asks for each missing part', () => {
		expect(termFormError({ name: ' ', definition: 'x' })).toMatch(/name/);
		expect(termFormError({ name: 'VIP', definition: ' ' })).toMatch(/means/);
	});
	it('refuses what the server would refuse', () => {
		expect(termFormError({ name: 'x'.repeat(201), definition: 'x' })).toMatch(/limited/);
		expect(termFormError({ name: 'VIP', definition: 'x'.repeat(2001) })).toMatch(/limited/);
	});
});

describe('learned term', () => {
	it('words the line under the answer', () => {
		expect(learnedTermLine({ id: 'k', name: 'VIP' })).toBe(
			'Saved as your draft definition: VIP',
		);
	});
	it('parses only a complete wire value', () => {
		expect(parseLearnedTerm({ id: 'k', name: 'VIP' })).toEqual({ id: 'k', name: 'VIP' });
		expect(parseLearnedTerm({ id: 'k' })).toBeUndefined();
		expect(parseLearnedTerm(null)).toBeUndefined();
		expect(parseLearnedTerm('x')).toBeUndefined();
	});
});

describe('the live answer', () => {
	it('carries the learned term to the message', () => {
		const message = buildSqlAnswerMessage({
			response: 'There are 12.',
			sql_code: 'SELECT 12',
			learned_term: { id: 'k', name: 'VIP' },
		});
		expect(message?.learnedTerm).toEqual({ id: 'k', name: 'VIP' });
	});
	it('has none when the server sent none or something malformed', () => {
		expect(buildSqlAnswerMessage({ response: 'x' })?.learnedTerm).toBeUndefined();
		expect(
			buildSqlAnswerMessage({ response: 'x', learned_term: { id: 3 } })?.learnedTerm,
		).toBeUndefined();
	});
});
