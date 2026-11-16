// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { ChatMessage } from '@/types/chat';
import { AnswerPath } from './AnswerPath';

// The icon component renders an imported SVG asset, which the Node test
// environment cannot turn into markup; a stub keeps these tests about content.
vi.mock('@/common/icons', () => ({
	Icon: () => null,
	IconName: new Proxy({}, { get: (_target, name) => String(name) }),
}));

/** The visible text of rendered markup: tags removed, entities of quotes decoded. */
const textOf = (html: string): string =>
	html
		.replace(/<[^>]+>/g, '')
		.replace(/&#x27;|&apos;/g, "'")
		.replace(/&gt;/g, '>');

describe('AnswerPath', () => {
	const fullMessage: ChatMessage = {
		id: 'msg-1',
		role: 'assistant',
		content: 'Here is the sales analysis you requested.',
		sql: 'SELECT * FROM sales;',
		sqlResponse: JSON.stringify([{ id: 1 }, { id: 2 }]),
		timestamp: 1000000,
		steps: [
			{
				node: 'question_intent',
				label: 'Question intent',
				thought: 'User wants sales data',
				status: 'completed',
			},
		],
		knowledgeTrace: [
			{
				kind: 'term',
				id: 't1',
				name: 'Sales Term',
				database: null,
				certified: true,
				reason: '',
				used: true,
				matched: ['sales'],
			},
		],
	};

	it('renders closed line text for a full message and omits prose from the closed state', () => {
		const html = renderToStaticMarkup(<AnswerPath message={fullMessage} defaultOpen={false} />);
		expect(textOf(html)).toContain(
			'How: Understood › Knowledge 1 offered · 1 used › SQL (1 attempt) › 2 rows',
		);
		expect(html).not.toContain('Here is the sales analysis you requested.');
		expect(html).not.toContain('Wrote the SQL');
	});

	it('hides unknown steps from the closed summary line', () => {
		const partialMessage: ChatMessage = {
			id: 'msg-2',
			role: 'assistant',
			content: 'Partial message with SQL only.',
			sql: 'SELECT 1;',
			timestamp: 1000000,
		};
		const html = renderToStaticMarkup(
			<AnswerPath message={partialMessage} defaultOpen={false} />,
		);
		expect(html).toContain('How: SQL');
		expect(html).not.toContain('Understood');
		expect(html).not.toContain('Knowledge');
	});

	it('renders nothing when no step is known', () => {
		const emptyMessage: ChatMessage = {
			id: 'msg-3',
			role: 'assistant',
			content: 'Plain response without SQL or trace',
			timestamp: 1000000,
		};
		const html = renderToStaticMarkup(
			<AnswerPath message={emptyMessage} defaultOpen={false} />,
		);
		expect(html).toBe('');
	});

	it('shows timeline when defaultOpen is true', () => {
		const html = renderToStaticMarkup(<AnswerPath message={fullMessage} defaultOpen={true} />);
		expect(html).toContain('Understood the question');
		expect(html).toContain('Found knowledge');
		expect(html).toContain('Wrote the SQL');
		expect(html).toContain('Checked and ran it');
	});

	it('renders SQL and collapsed model description when SQL step is open', () => {
		const html = renderToStaticMarkup(<AnswerPath message={fullMessage} defaultOpen={true} />);
		expect(textOf(html)).toContain('SELECT * FROM sales;');
		expect(textOf(html)).toContain("Model's description of the query");
		expect(html).toContain('Here is the sales analysis you requested.');
	});

	it('names the database that answered, only when it is known', () => {
		const withDb = renderToStaticMarkup(
			<AnswerPath message={{ ...fullMessage, database: 'sales_db' }} />,
		);
		expect(textOf(withDb)).toContain('Answered from database: sales_db');
		const without = renderToStaticMarkup(<AnswerPath message={fullMessage} />);
		expect(textOf(without)).not.toContain('Answered from database');
	});

	it('shows the database even when no path step is known', () => {
		const html = renderToStaticMarkup(
			<AnswerPath
				message={{
					id: 'm',
					role: 'assistant',
					content: 'x',
					timestamp: 1,
					database: 'db1',
				}}
			/>,
		);
		expect(textOf(html)).toContain('Answered from database: db1');
	});
});
