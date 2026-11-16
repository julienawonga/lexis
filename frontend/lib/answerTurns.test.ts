// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import type { ChatMessage } from '@/types/chat';
import { groupAnswerTurns } from './answerTurns';

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
];

const answerMessage = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
	id: 'm1',
	role: 'assistant',
	content: 'Here are your top customers.',
	sql: 'SELECT name, total FROM payments ORDER BY total DESC LIMIT 10;',
	knowledgeTrace,
	timestamp: 1,
	...overrides,
});

const chartResult = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
	id: 'm2',
	role: 'assistant',
	content: '```chart\n{"type":"bar","title":"Top customers"}\n```',
	timestamp: 2,
	...overrides,
});

const rowsResult = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
	id: 'm2',
	role: 'assistant',
	content: '',
	sqlResponse: '[{"name":"Ada","total":"712"}]',
	timestamp: 2,
	...overrides,
});

describe('groupAnswerTurns', () => {
	it('merges an answer with the result message that follows it', () => {
		const m1 = answerMessage();
		const m2 = chartResult();
		const grouped = groupAnswerTurns([m1, m2]);

		expect(grouped).toHaveLength(1);
		expect(grouped[0].result).toEqual({
			content: m2.content,
			sqlResponse: undefined,
		});
		expect(grouped[0].timestamp).toBe(m2.timestamp);
	});

	it('keeps the answer message id, sql and knowledgeTrace', () => {
		const m1 = answerMessage();
		const grouped = groupAnswerTurns([m1, chartResult()]);

		expect(grouped[0].id).toBe('m1');
		expect(grouped[0].sql).toBe(m1.sql);
		expect(grouped[0].knowledgeTrace).toBe(knowledgeTrace);
	});

	it('merges a chart-fence result and a raw-rows result alike', () => {
		const rows = '[{"count":"712"}]';
		const byChart = groupAnswerTurns([answerMessage(), chartResult()]);
		const byRows = groupAnswerTurns([answerMessage(), rowsResult({ sqlResponse: rows })]);

		expect(byChart).toHaveLength(1);
		expect(byChart[0].result?.content).toContain('```chart');
		expect(byRows).toHaveLength(1);
		expect(byRows[0].result?.sqlResponse).toBe(rows);
	});

	it('does not merge across an intervening user message', () => {
		const m1 = answerMessage();
		const user: ChatMessage = { id: 'u1', role: 'user', content: 'thanks', timestamp: 3 };
		const m2 = chartResult();
		const grouped = groupAnswerTurns([m1, user, m2]);

		expect(grouped).toEqual([m1, user, m2]);
		expect(grouped[0].result).toBeUndefined();
	});

	it('leaves a lone answer (result still running) untouched', () => {
		const m1 = answerMessage();
		const grouped = groupAnswerTurns([m1]);

		expect(grouped).toEqual([m1]);
		expect(grouped[0]).toBe(m1);
	});

	it('leaves a lone result message untouched', () => {
		const m2 = chartResult();
		const grouped = groupAnswerTurns([m2]);

		expect(grouped).toEqual([m2]);
		expect(grouped[0]).toBe(m2);
	});

	it('does not treat a clarification as the answer half of a pair', () => {
		const m1 = answerMessage();
		const m2 = chartResult({
			clarification: { id: 'c-1', term: 'VIP', question: 'q', options: [], allowOther: true },
		});
		const grouped = groupAnswerTurns([m1, m2]);

		expect(grouped).toEqual([m1, m2]);
	});

	it('does not mutate the input array', () => {
		const messages = [answerMessage(), chartResult(), rowsResult()];
		const before = JSON.parse(JSON.stringify(messages));
		groupAnswerTurns(messages);

		expect(messages).toEqual(before);
		expect(messages).toHaveLength(3);
	});

	it('passes the same objects through when there is nothing to merge', () => {
		const user: ChatMessage = { id: 'u1', role: 'user', content: 'hi', timestamp: 1 };
		const plain: ChatMessage = {
			id: 'm3',
			role: 'assistant',
			content: 'All done.',
			timestamp: 4,
		};
		const loneResult = chartResult();
		const messages = [user, plain, loneResult];
		const grouped = groupAnswerTurns(messages);

		expect(grouped).toHaveLength(3);
		expect(grouped[0]).toBe(user);
		expect(grouped[1]).toBe(plain);
		expect(grouped[2]).toBe(loneResult);
	});
});
