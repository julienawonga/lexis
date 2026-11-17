// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import type { AuditEvent } from '@/types/audit';

/** The action-prefix filter offered on the audit log page. */
export const AUDIT_ACTION_FILTERS: ReadonlyArray<{ label: string; prefix: string }> = [
	{ label: 'All actions', prefix: '' },
	{ label: 'Terms', prefix: 'term.' },
	{ label: 'Connections', prefix: 'connection.' },
	{ label: 'Groups', prefix: 'group.' },
	{ label: 'Zones', prefix: 'zone.' },
	{ label: 'SQL attributes', prefix: 'sql_attribute.' },
	{ label: 'Custom analyses', prefix: 'custom_analysis.' },
	{ label: 'Semantic compilation', prefix: 'semantic_compilation.' },
	{ label: 'Business domains', prefix: 'semantic_domain.' },
];

/** Who did it: the email recorded at the time, else the id, else "System". */
export const auditActorLabel = (event: AuditEvent): string => {
	if (event.actor_email) return event.actor_email;
	if (event.actor_id) return event.actor_id;
	return 'System';
};

/** What it was done to: "kind name" when a name was recorded, else the id. */
export const auditTargetLabel = (event: AuditEvent): string => {
	const label = event.target_name ?? event.target_id;
	if (!label) return event.target_kind ?? '';
	return event.target_kind ? `${event.target_kind} ${label}` : label;
};

const formatDetailValue = (value: unknown): string =>
	Array.isArray(value) ? value.map(String).join(', ') : String(value);

/** The allowlisted details as `key: value` pairs, or an empty string. */
export const auditDetailsLabel = (details: Record<string, unknown>): string =>
	Object.entries(details)
		.map(([key, value]) => `${key}: ${formatDetailValue(value)}`)
		.join(' · ');
