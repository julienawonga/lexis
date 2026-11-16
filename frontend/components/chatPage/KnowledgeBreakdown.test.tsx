// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { KnowledgeTraceEntry } from '@/types/chat';
import { KnowledgeBreakdown } from './KnowledgeBreakdown';

// The icon component renders an imported SVG asset, which the Node test
// environment cannot turn into markup; a stub keeps these tests about content.
vi.mock('@/common/icons', () => ({
	Icon: () => null,
	IconName: new Proxy({}, { get: (_target, name) => String(name) }),
}));

describe('KnowledgeBreakdown', () => {
	it('renders nothing for an empty list', () => {
		const htmlEmpty = renderToStaticMarkup(<KnowledgeBreakdown entries={[]} />);
		expect(htmlEmpty).toBe('');

		const htmlUndefined = renderToStaticMarkup(<KnowledgeBreakdown entries={undefined} />);
		expect(htmlUndefined).toBe('');
	});

	it('renders used card first and considered grid second', () => {
		const entries: KnowledgeTraceEntry[] = [
			{
				kind: 'term',
				id: '1',
				name: 'ConsideredTerm',
				database: null,
				certified: null,
				reason: '',
				used: false,
				matched: [],
			},
			{
				kind: 'sql_attribute',
				id: '2',
				name: 'UsedAttribute',
				database: null,
				certified: true,
				reason: '',
				used: true,
				matched: ['col_x'],
			},
			{
				kind: 'column_attribute',
				id: '3',
				name: 'UndecidedColumn',
				database: null,
				certified: null,
				reason: '',
				used: null,
				matched: [],
			},
		];

		const html = renderToStaticMarkup(<KnowledgeBreakdown entries={entries} />);
		expect(html).toContain('Used in the SQL');
		expect(html).toContain('UsedAttribute');
		expect(html).toContain('sql attribute');
		expect(html).toContain('Also considered (2): 1 undecided, 1 not used');
		expect(html).toContain('ConsideredTerm');
		expect(html).toContain('UndecidedColumn');

		const usedPos = html.indexOf('UsedAttribute');
		const consideredPos = html.indexOf('ConsideredTerm');
		expect(usedPos).toBeLessThan(consideredPos);
	});

	it('shows check icon only when certified === true and never writes "not certified"', () => {
		const entries: KnowledgeTraceEntry[] = [
			{
				kind: 'term',
				id: '1',
				name: 'CertTrue',
				database: null,
				certified: true,
				reason: '',
				used: true,
				matched: [],
			},
			{
				kind: 'term',
				id: '2',
				name: 'CertFalse',
				database: null,
				certified: false,
				reason: '',
				used: false,
				matched: [],
			},
		];

		const html = renderToStaticMarkup(<KnowledgeBreakdown entries={entries} />);
		expect(html).not.toContain('not certified');

		const htmlCertTrue = renderToStaticMarkup(<KnowledgeBreakdown entries={[entries[0]]} />);
		expect(htmlCertTrue).toContain('CertTrue');

		const htmlCertFalse = renderToStaticMarkup(<KnowledgeBreakdown entries={[entries[1]]} />);
		expect(htmlCertFalse).not.toContain('not certified');
	});

	it('renders matched chips when matched is non-empty', () => {
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

		const html = renderToStaticMarkup(<KnowledgeBreakdown entries={entries} />);
		expect(html).toContain('found in SQL');
		expect(html).toContain('col_a');
		expect(html).toContain('col_b');
	});
});
