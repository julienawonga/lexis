// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { KnowledgeTracePanel } from './KnowledgeTracePanel';

describe('KnowledgeTracePanel', () => {
	it('is a re-exported function', () => {
		expect(typeof KnowledgeTracePanel).toBe('function');
	});
});
