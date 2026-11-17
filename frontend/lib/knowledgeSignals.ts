// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import type { KnowledgeTraceEntry } from '@/types/chat';

/**
 * Two independent signals about one piece of knowledge, never merged:
 * `declared` is the model's own account of what it applied (not proof), and
 * `found_in_sql` is a text match on the final SQL (not a cause).
 */
type Signals = Pick<KnowledgeTraceEntry, 'declared' | 'found_in_sql'>;

export type SignalAgreement = 'agree' | 'declared_only' | 'found_only' | null;

/** How the two signals relate; null when either is missing or undecided. */
export function signalAgreement(entry: Signals): SignalAgreement {
	const { declared, found_in_sql: found } = entry;
	if (declared === undefined || declared === null) return null;
	if (found === undefined || found === null) return null;
	if (declared === found) return 'agree';
	return declared ? 'declared_only' : 'found_only';
}

/** The label for the model's own account, or null when it gave none. */
export function declaredLabel(entry: Signals): string | null {
	if (entry.declared === undefined || entry.declared === null) return null;
	return entry.declared ? 'Applied (the model said so)' : 'Not applied (the model said so)';
}

/** The label for the text match on the SQL, or null when it is undecided. */
export function foundLabel(entry: Signals): string | null {
	if (entry.found_in_sql === undefined || entry.found_in_sql === null) return null;
	return entry.found_in_sql ? 'Found in the SQL' : 'Not found in the SQL';
}

/** A plain sentence when the signals disagree, else null. Never hides a disagreement. */
export function disagreementText(entry: Signals): string | null {
	switch (signalAgreement(entry)) {
		case 'declared_only':
			return 'The model said it applied this but nothing in the SQL matches';
		case 'found_only':
			return 'Found in the SQL but not declared';
		default:
			return null;
	}
}
