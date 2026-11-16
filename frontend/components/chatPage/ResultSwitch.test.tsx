// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ResultSwitch } from './ResultSwitch';

describe('ResultSwitch', () => {
	it('renders default state showing chart node and button attributes', () => {
		const html = renderToStaticMarkup(
			<ResultSwitch
				chart={<div data-testid="chart-node">Chart View</div>}
				table={<div data-testid="table-node">Table View</div>}
			/>,
		);
		expect(html).toContain('Chart View');
		expect(html).not.toContain('Table View');
		expect(html).toContain('Chart');
		expect(html).toContain('Table');
		expect(html).toContain('aria-pressed="true"');
		expect(html).toContain('aria-pressed="false"');
	});
});
