// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { isEmptyResult, splitResultNotice } from './resultNotice';

describe('splitResultNotice', () => {
	it('takes the cut-result notice off the front of a chart message', () => {
		const content =
			'> **Result note:** Showing the first 500 rows; the result was cut.\n\n```chart\n{}\n```';
		expect(splitResultNotice(content)).toEqual({
			notice: 'Showing the first 500 rows; the result was cut.',
			body: '```chart\n{}\n```',
		});
	});

	it('finds the notice on a table-only message', () => {
		const { notice, body } = splitResultNotice('> **Result note:** Cut at 10 rows.');
		expect(notice).toBe('Cut at 10 rows.');
		expect(body).toBe('');
	});

	it('leaves other content alone', () => {
		expect(splitResultNotice('```chart\n{}\n```').notice).toBeNull();
		expect(splitResultNotice('> **Note:** something else').notice).toBeNull();
		expect(splitResultNotice(undefined)).toEqual({ notice: null, body: '' });
	});
});

describe('isEmptyResult', () => {
	it('recognises the stored shapes of an empty result', () => {
		expect(isEmptyResult('["[]"]')).toBe(true);
		expect(isEmptyResult('[]')).toBe(true);
	});

	it('is false for rows, nothing, or text', () => {
		expect(isEmptyResult('[{"a":1}]')).toBe(false);
		expect(isEmptyResult('["[{\\"a\\":1}]"]')).toBe(false);
		expect(isEmptyResult(undefined)).toBe(false);
		expect(isEmptyResult('a,b\n1,2')).toBe(false);
	});
});
