// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import type { ChatMessage, GraphStep } from '@/types/chat';
import { pathSteps } from './answerPath';

const liveSteps: GraphStep[] = [
	{ node: 'question_intent', label: 'Validating intent', status: 'completed' },
	{ node: 'retrieve_candidates', label: 'Searching knowledge', status: 'completed' },
	{ node: 'construct_sql_from_candidates', label: 'Writing SQL', status: 'completed' },
	{ node: 'execute_sql_query', label: 'Running the query', status: 'completed' },
];

const knowledgeTrace = [
	{
		kind: 'term' as const,
		id: 't-1',
		name: 'VIP customers',
		database: null,
		certified: true,
		reason: 'glossary match',
		used: true,
		matched: [],
	},
	{
		kind: 'column_attribute' as const,
		id: 'c-1',
		name: 'total',
		database: 'music',
		certified: null,
		reason: 'column match',
		used: false,
		matched: [],
	},
];

const answerMessage = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
	id: 'm1',
	role: 'assistant',
	content: 'Here is the answer.',
	sql: 'SELECT count(*) FROM payments;',
	knowledgeTrace,
	steps: liveSteps,
	sqlResponse: '[{"count":"712"},{"count":"300"}]',
	timestamp: 1,
	...overrides,
});

const ROWS_RESULT = '[{"region":"EMEA","revenue":"1200"},{"region":"AMER","revenue":"900"}]';

describe('pathSteps', () => {
	it('always returns the four steps in order with their fixed titles', () => {
		const steps = pathSteps(answerMessage());

		expect(steps.map((s) => s.id)).toEqual(['understood', 'knowledge', 'sql', 'run']);
		expect(steps.map((s) => s.title)).toEqual([
			'Understood the question',
			'Found knowledge',
			'Wrote the SQL',
			'Checked and ran it',
		]);
	});

	it('marks understood as known when an intent or extraction node ran', () => {
		expect(pathSteps(answerMessage()).find((s) => s.id === 'understood')?.known).toBe(true);
		expect(
			pathSteps(
				answerMessage({
					steps: [
						{ node: 'question_extraction', label: 'Extracting', status: 'completed' },
					],
				}),
			).find((s) => s.id === 'understood')?.known,
		).toBe(true);
		expect(
			pathSteps(
				answerMessage({
					steps: [{ node: 'execute_sql_query', label: 'Running', status: 'completed' }],
				}),
			).find((s) => s.id === 'understood')?.known,
		).toBe(false);
	});

	it('summarises knowledge as offered vs used', () => {
		const step = pathSteps(answerMessage()).find((s) => s.id === 'knowledge');
		expect(step?.known).toBe(true);
		expect(step?.summary).toBe('2 offered · 1 used');
	});

	it('counts only entries used === true, not null or false', () => {
		const step = pathSteps(
			answerMessage({
				knowledgeTrace: [
					{ ...knowledgeTrace[0], used: null },
					{ ...knowledgeTrace[1], used: false },
				],
			}),
		).find((s) => s.id === 'knowledge');
		expect(step?.summary).toBe('2 offered · 0 used');
	});

	it('marks knowledge unknown without a trace', () => {
		const step = pathSteps(answerMessage({ knowledgeTrace: undefined })).find(
			(s) => s.id === 'knowledge',
		);
		expect(step?.known).toBe(false);
		expect(step?.summary).toBe('');
	});

	it('marks knowledge unknown for an empty trace', () => {
		const step = pathSteps(answerMessage({ knowledgeTrace: [] })).find(
			(s) => s.id === 'knowledge',
		);
		expect(step?.known).toBe(false);
	});

	it('marks sql as known when the message carries SQL', () => {
		expect(pathSteps(answerMessage()).find((s) => s.id === 'sql')?.known).toBe(true);
		expect(
			pathSteps(answerMessage({ sql: undefined })).find((s) => s.id === 'sql')?.known,
		).toBe(false);
	});

	it('summarises sql as corrected when the query was reconstructed', () => {
		const steps: GraphStep[] = [
			...liveSteps,
			{ node: 'reconstruct_sql', label: 'Rewrote SQL', status: 'completed' },
		];
		const step = pathSteps(answerMessage({ steps })).find((s) => s.id === 'sql');
		expect(step?.summary).toBe('corrected');
	});

	it('summarises sql as one attempt when steps ran without a rewrite', () => {
		expect(pathSteps(answerMessage()).find((s) => s.id === 'sql')?.summary).toBe('1 attempt');
	});

	it('leaves the sql summary empty for history messages without steps', () => {
		const step = pathSteps(answerMessage({ steps: undefined })).find((s) => s.id === 'sql');
		expect(step?.summary).toBe('');
		expect(step?.known).toBe(true);
	});

	it('marks run as known from the folded result rows', () => {
		const step = pathSteps(
			answerMessage({ result: { content: 'chart', sqlResponse: ROWS_RESULT } }),
		).find((s) => s.id === 'run');
		expect(step?.known).toBe(true);
		expect(step?.summary).toBe('2 rows');
	});

	it('falls back to the message sqlResponse when there is no result', () => {
		const step = pathSteps(answerMessage({ sqlResponse: ROWS_RESULT })).find(
			(s) => s.id === 'run',
		);
		expect(step?.known).toBe(true);
		expect(step?.summary).toBe('2 rows');
	});

	it('prefers the folded result over the raw sqlResponse', () => {
		const step = pathSteps(
			answerMessage({
				sqlResponse: '[{"count":"712"}]',
				result: {
					content: 'chart',
					sqlResponse: '[{"one":"1"},{"two":"2"},{"three":"3"}]',
				},
			}),
		).find((s) => s.id === 'run');
		expect(step?.summary).toBe('3 rows');
	});

	it('formats thousands separators and the singular row', () => {
		const manyRows = JSON.stringify(Array.from({ length: 1234 }, (_, i) => ({ i: String(i) })));
		const many = pathSteps(answerMessage({ sqlResponse: manyRows })).find(
			(s) => s.id === 'run',
		);
		expect(many?.summary).toBe('1,234 rows');

		const one = pathSteps(answerMessage({ sqlResponse: '[{"count":"712"}]' })).find(
			(s) => s.id === 'run',
		);
		expect(one?.summary).toBe('1 row');
	});

	it('marks run unknown with no result yet, or a non-tabular response', () => {
		const none = pathSteps(answerMessage({ sqlResponse: undefined })).find(
			(s) => s.id === 'run',
		);
		expect(none?.known).toBe(false);
		expect(none?.summary).toBe('');

		const prose = pathSteps(answerMessage({ sqlResponse: 'no rows came back' })).find(
			(s) => s.id === 'run',
		);
		expect(prose?.known).toBe(false);
		expect(prose?.summary).toBe('');
	});

	it('shows a history message (no steps) with only what it stored', () => {
		const history = answerMessage({ steps: undefined, result: undefined });
		const [understood, knowledge, sql, run] = pathSteps(history);

		expect(understood.known).toBe(false);
		expect(understood.summary).toBe('');
		expect(knowledge.known).toBe(true);
		expect(knowledge.summary).toBe('2 offered · 1 used');
		expect(sql.known).toBe(true);
		expect(sql.summary).toBe('');
		expect(run.known).toBe(true);
		expect(run.summary).toBe('2 rows');
	});
});
