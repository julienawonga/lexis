// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { DEFAULT_NEXT, safeNext } from './safeNext';

describe('safeNext', () => {
	it.each([
		'/chat',
		'/data/sources?tab=2',
		'/discovery#top',
		'/api/auth/oauth2/authorize?client_id=x&redirect_uri=http%3A%2F%2Flocalhost%3A8787%2Fcb',
	])('keeps the same-origin path %s', (path) => {
		expect(safeNext(path)).toBe(path);
	});

	it.each([
		'https://evil.example',
		'http://evil.example/chat',
		'//evil.example',
		'///evil.example',
		'/\\evil.example',
		'/chat\\..\\evil',
		'javascript:alert(1)',
		'JaVaScRiPt:alert(1)',
		'data:text/html,x',
		'evil.example',
		'chat',
		' /chat',
		'/\tevil.example',
		'/\nevil.example',
		'',
	])('falls back for %j', (value) => {
		expect(safeNext(value)).toBe(DEFAULT_NEXT);
	});

	it('falls back for a missing value and honours a custom fallback', () => {
		expect(safeNext(null)).toBe('/chat');
		expect(safeNext(undefined)).toBe('/chat');
		expect(safeNext('//x', '/home')).toBe('/home');
	});
});
