import { describe, expect, it } from 'vitest';
import { COMPILATION_POLL_MS, nextPollDelay } from './compilationPolling';

describe('nextPollDelay', () => {
	it('polls while a run is in progress', () => {
		expect(nextPollDelay(true)).toBe(COMPILATION_POLL_MS);
	});

	it('stops once the run is over', () => {
		expect(nextPollDelay(false)).toBeNull();
	});
});
