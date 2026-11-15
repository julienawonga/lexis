// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { KnowledgeTraceEntry } from '@/types/chat';
import { KnowledgeTracePanel } from './KnowledgeTracePanel';

describe('KnowledgeTracePanel', () => {
	it('renders nothing for an empty list', () => {
		const html = renderToStaticMarkup(<KnowledgeTracePanel entries={[]} />);
		expect(html).toBe('');
	});

	it('shows the summary with the right counts', () => {
		const entries: KnowledgeTraceEntry[] = [
			{
				kind: 'term',
				id: '1',
				name: 'Term 1',
				database: null,
				certified: true,
				reason: '',
				used: true,
				matched: [],
			},
			{
				kind: 'sql_attribute',
				id: '2',
				name: 'Attr 2',
				database: null,
				certified: false,
				reason: '',
				used: false,
				matched: [],
			},
			{
				kind: 'column_attribute',
				id: '3',
				name: 'Attr 3',
				database: null,
				certified: null,
				reason: '',
				used: null,
				matched: [],
			},
		];
		const html = renderToStaticMarkup(<KnowledgeTracePanel entries={entries} />);
		expect(html).toContain('Knowledge offered to the SQL (3), 1 used');
	});

	it('orders used before undecided before not used', () => {
		const entries: KnowledgeTraceEntry[] = [
			{
				kind: 'term',
				id: 'not-used',
				name: 'NotUsedTerm',
				database: null,
				certified: null,
				reason: '',
				used: false,
				matched: [],
			},
			{
				kind: 'term',
				id: 'undecided',
				name: 'UndecidedTerm',
				database: null,
				certified: null,
				reason: '',
				used: null,
				matched: [],
			},
			{
				kind: 'term',
				id: 'used',
				name: 'UsedTerm',
				database: null,
				certified: null,
				reason: '',
				used: true,
				matched: [],
			},
		];
		const html = renderToStaticMarkup(<KnowledgeTracePanel entries={entries} />);
		const posUsed = html.indexOf('UsedTerm');
		const posUndecided = html.indexOf('UndecidedTerm');
		const posNotUsed = html.indexOf('NotUsedTerm');
		expect(posUsed).toBeGreaterThan(-1);
		expect(posUndecided).toBeGreaterThan(-1);
		expect(posNotUsed).toBeGreaterThan(-1);
		expect(posUsed).toBeLessThan(posUndecided);
		expect(posUndecided).toBeLessThan(posNotUsed);
	});

	it('shows the certified badge only for certified === true/false, not null', () => {
		const entries: KnowledgeTraceEntry[] = [
			{
				kind: 'term',
				id: '1',
				name: 'CertTrueTerm',
				database: null,
				certified: true,
				reason: '',
				used: null,
				matched: [],
			},
			{
				kind: 'term',
				id: '2',
				name: 'CertFalseTerm',
				database: null,
				certified: false,
				reason: '',
				used: null,
				matched: [],
			},
			{
				kind: 'term',
				id: '3',
				name: 'CertNullTerm',
				database: null,
				certified: null,
				reason: '',
				used: null,
				matched: [],
			},
		];
		const html = renderToStaticMarkup(<KnowledgeTracePanel entries={entries} />);
		expect(html).toContain('certified');
		expect(html).toContain('not certified');

		const nullHtml = renderToStaticMarkup(<KnowledgeTracePanel entries={[entries[2]]} />);
		expect(nullHtml).not.toContain('certified');
		expect(nullHtml).not.toContain('not certified');
	});

	it('shows matched identifiers', () => {
		const entries: KnowledgeTraceEntry[] = [
			{
				kind: 'term',
				id: '1',
				name: 'MatchedTerm',
				database: null,
				certified: null,
				reason: '',
				used: true,
				matched: ['col_a', 'col_b'],
			},
		];
		const html = renderToStaticMarkup(<KnowledgeTracePanel entries={entries} />);
		expect(html).toContain('col_a');
		expect(html).toContain('col_b');
	});
});
