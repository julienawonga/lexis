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

const message = (thought?: string): ChatMessage => ({
	id: 'm1',
	role: 'assistant',
	content: 'A description.',
	sql: 'SELECT 1;',
	timestamp: 1,
	steps: [{ node: 'question_intent', label: 'Question intent', thought, status: 'completed' }],
});

describe('the understood step', () => {
	it('is a plain row, not a button, when the engine left no note', () => {
		const html = renderToStaticMarkup(<AnswerPath message={message()} defaultOpen />);
		expect(html).toContain('Understood the question');
		expect(html.match(/disabled=""/g)).toHaveLength(1);
	});

	it('is a working row when the engine recorded a note', () => {
		const html = renderToStaticMarkup(
			<AnswerPath
				message={message('Calculation question (aggregation). Database: chinook.')}
				defaultOpen
			/>,
		);
		expect(html).toContain('Understood the question');
		expect(html).not.toContain('disabled=""');
	});
});
