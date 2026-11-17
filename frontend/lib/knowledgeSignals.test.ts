// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import {
	declaredLabel,
	disagreementText,
	foundLabel,
	signalAgreement,
} from '@/lib/knowledgeSignals';

describe('knowledge signals', () => {
	it('labels the two signals separately', () => {
		expect(declaredLabel({ declared: true, found_in_sql: false })).toBe(
			'Applied (the model said so)',
		);
		expect(declaredLabel({ declared: false })).toBe('Not applied (the model said so)');
		expect(foundLabel({ found_in_sql: true })).toBe('Found in the SQL');
		expect(foundLabel({ found_in_sql: false })).toBe('Not found in the SQL');
	});

	it('gives no label when a signal is missing or undecided', () => {
		expect(declaredLabel({})).toBeNull();
		expect(declaredLabel({ declared: null })).toBeNull();
		expect(foundLabel({ found_in_sql: null })).toBeNull();
		expect(foundLabel({})).toBeNull();
	});

	it('classifies agreement and disagreement', () => {
		expect(signalAgreement({ declared: true, found_in_sql: true })).toBe('agree');
		expect(signalAgreement({ declared: false, found_in_sql: false })).toBe('agree');
		expect(signalAgreement({ declared: true, found_in_sql: false })).toBe('declared_only');
		expect(signalAgreement({ declared: false, found_in_sql: true })).toBe('found_only');
		expect(signalAgreement({ declared: true, found_in_sql: null })).toBeNull();
		expect(signalAgreement({ found_in_sql: true })).toBeNull();
	});

	it('states a disagreement in plain words and stays silent otherwise', () => {
		expect(disagreementText({ declared: true, found_in_sql: false })).toBe(
			'The model said it applied this but nothing in the SQL matches',
		);
		expect(disagreementText({ declared: false, found_in_sql: true })).toBe(
			'Found in the SQL but not declared',
		);
		expect(disagreementText({ declared: true, found_in_sql: true })).toBeNull();
		expect(disagreementText({ declared: null, found_in_sql: true })).toBeNull();
	});
});
