// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { auditActorLabel, auditDetailsLabel, auditTargetLabel } from '@/lib/auditLog';
import type { AuditEvent } from '@/types/audit';

const event = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
	id: 'e1',
	at: '2026-11-17T10:00:00Z',
	actor_id: 'u1',
	actor_email: 'a@example.com',
	actor_kind: 'user',
	action: 'term.update',
	target_kind: 'term',
	target_id: 't1',
	target_name: 'Revenue',
	request_id: null,
	details: {},
	...overrides,
});

describe('auditActorLabel', () => {
	it('prefers the email recorded at the time', () => {
		expect(auditActorLabel(event())).toBe('a@example.com');
	});
	it('falls back to the id, then to System', () => {
		expect(auditActorLabel(event({ actor_email: null }))).toBe('u1');
		expect(auditActorLabel(event({ actor_email: null, actor_id: null }))).toBe('System');
	});
});

describe('auditTargetLabel', () => {
	it('names the kind and the name', () => {
		expect(auditTargetLabel(event())).toBe('term Revenue');
	});
	it('uses the id when no name was recorded', () => {
		expect(auditTargetLabel(event({ target_name: null }))).toBe('term t1');
	});
	it('is empty when nothing was targeted', () => {
		const none = event({ target_kind: null, target_id: null, target_name: null });
		expect(auditTargetLabel(none)).toBe('');
	});
});

describe('auditDetailsLabel', () => {
	it('joins pairs and flattens lists', () => {
		expect(auditDetailsLabel({ fields: ['name', 'description'], table_count: 2 })).toBe(
			'fields: name, description · table_count: 2',
		);
	});
	it('is empty for no details', () => {
		expect(auditDetailsLabel({})).toBe('');
	});
});
