// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import { proxyToBackend } from '@/auth/proxy-backend';
import {
	UPSTREAM_TIMEOUT,
	UPSTREAM_UNREACHABLE,
	busyMessage,
	fetchUntilHeaders,
	parseRetryAfterSeconds,
	retryAfterHeader,
	upstreamFailure,
} from './upstream';

afterEach(() => {
	vi.unstubAllGlobals();
	vi.useRealTimers();
});

describe('upstreamFailure', () => {
	it('answers 502 JSON for a refused connection', async () => {
		const res = upstreamFailure(new TypeError('fetch failed'));
		expect(res.status).toBe(502);
		expect(await res.json()).toEqual({ detail: UPSTREAM_UNREACHABLE });
	});

	it('answers 504 JSON for a timeout', async () => {
		const res = upstreamFailure(new DOMException('x', 'TimeoutError'));
		expect(res.status).toBe(504);
		expect(await res.json()).toEqual({ detail: UPSTREAM_TIMEOUT });
	});
});

describe('Retry-After', () => {
	it('parses delta-seconds only', () => {
		expect(parseRetryAfterSeconds('5')).toBe(5);
		expect(parseRetryAfterSeconds('0')).toBeNull();
		expect(parseRetryAfterSeconds('Wed, 21 Oct 2026 07:28:00 GMT')).toBeNull();
		expect(parseRetryAfterSeconds(null)).toBeNull();
	});

	it('forwards the header when present', () => {
		expect(retryAfterHeader(new Response('', { headers: { 'Retry-After': '7' } }))).toEqual({
			'Retry-After': '7',
		});
		expect(retryAfterHeader(new Response(''))).toEqual({});
	});

	it('words the busy message', () => {
		expect(busyMessage(5)).toBe('The chat is busy; try again in 5 seconds.');
		expect(busyMessage(1)).toBe('The chat is busy; try again in 1 second.');
	});
});

describe('fetchUntilHeaders', () => {
	it('rejects with a TimeoutError when the headers never come', async () => {
		vi.useFakeTimers();
		vi.stubGlobal(
			'fetch',
			vi.fn(
				(_url: string, init: RequestInit) =>
					new Promise((_resolve, reject) => {
						init.signal?.addEventListener('abort', () => reject(init.signal?.reason));
					}),
			),
		);
		const pending = fetchUntilHeaders('http://x/', {}, 1000);
		const assertion = expect(pending).rejects.toMatchObject({ name: 'TimeoutError' });
		await vi.advanceTimersByTimeAsync(1001);
		await assertion;
	});

	it('does not abort a body that outlives the timeout', async () => {
		vi.useFakeTimers();
		let signal: AbortSignal | undefined;
		vi.stubGlobal(
			'fetch',
			vi.fn(async (_url: string, init: RequestInit) => {
				signal = init.signal ?? undefined;
				return new Response('ok');
			}),
		);
		await fetchUntilHeaders('http://x/', {}, 1000);
		await vi.advanceTimersByTimeAsync(5000);
		expect(signal?.aborted).toBe(false);
	});
});

describe('proxyToBackend', () => {
	it('answers 502 JSON when the backend is down', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('fetch failed')));
		const res = await proxyToBackend(new Request('http://web/api/tags'));
		expect(res.status).toBe(502);
		expect(await res.json()).toEqual({ detail: UPSTREAM_UNREACHABLE });
	});

	it('answers 504 JSON on a timeout', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockRejectedValue(new DOMException('timed out', 'TimeoutError')),
		);
		const res = await proxyToBackend(new Request('http://web/api/tags'));
		expect(res.status).toBe(504);
		expect(await res.json()).toEqual({ detail: UPSTREAM_TIMEOUT });
	});

	it('forwards Retry-After from a 503', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(
				new Response('{"detail":"busy"}', {
					status: 503,
					headers: { 'Content-Type': 'application/json', 'Retry-After': '4' },
				}),
			),
		);
		const res = await proxyToBackend(new Request('http://web/api/tags'));
		expect(res.status).toBe(503);
		expect(res.headers.get('retry-after')).toBe('4');
	});
});
