// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

export type AuditEvent = {
	id: string;
	at: string;
	actor_id: string | null;
	actor_email: string | null;
	actor_kind: 'user' | 'api_token' | 'system';
	action: string;
	target_kind: string | null;
	target_id: string | null;
	target_name: string | null;
	request_id: string | null;
	details: Record<string, unknown>;
};

export type AuditEventsPage = {
	data: AuditEvent[];
	next_cursor: number | null;
};

export type AuditEventsQuery = {
	action_prefix?: string;
	cursor?: number;
	limit?: number;
};
