// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

export type KnowledgeKind =
	| 'term'
	| 'synonym'
	| 'column_attribute'
	| 'sql_attribute'
	| 'verified_query'
	| 'relation';

export type KnowledgeStatus =
	| 'draft'
	| 'in_review'
	| 'certified'
	| 'needs_revalidation'
	| 'conflicted'
	| 'deprecated'
	| 'rejected';

export type KnowledgeScope = 'personal' | 'shared';

/** What a person may do with an item right now, as the server computed it. */
export type KnowledgeAction =
	| 'edit'
	| 'submit'
	| 'approve'
	| 'reject'
	| 'request_changes'
	| 'deprecate'
	| 'promote_scope';

export type KnowledgeItem = {
	id: string;
	kind: KnowledgeKind;
	status: KnowledgeStatus;
	scope: KnowledgeScope;
	owner_id: string;
	owner_email: string | null;
	database_id: string | null;
	content: Record<string, unknown>;
	provenance: Record<string, unknown>;
	/** The optimistic-lock token: send it back as `expected_version`. */
	current_version: number;
	created_by: string;
	created: string;
	modified: string;
	allowed_actions: KnowledgeAction[];
};

export type KnowledgeEvent = {
	at: string;
	action: string;
	actor_type: string;
	actor_id: string;
	actor_email: string | null;
	from_status: KnowledgeStatus | null;
	to_status: KnowledgeStatus;
	from_scope: KnowledgeScope | null;
	to_scope: KnowledgeScope;
	version: number;
	comment: string | null;
};

export type KnowledgeItemResponse = {
	data: KnowledgeItem;
	events: KnowledgeEvent[];
};

export type KnowledgeItemsPage = {
	data: KnowledgeItem[];
	next_cursor: string | null;
};

export type KnowledgeItemsQuery = {
	status?: KnowledgeStatus;
	kind?: KnowledgeKind;
	database?: string;
	mine?: boolean;
	reviewable?: boolean;
	cursor?: string;
	limit?: number;
};

export type KnowledgeStatusResponse = { enabled: boolean };

/** The item a clarification answer was saved as, sent on the live answer. */
export type LearnedTerm = { id: string; name: string };
