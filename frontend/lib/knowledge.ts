// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import type {
	KnowledgeAction,
	KnowledgeEvent,
	KnowledgeItem,
	KnowledgeStatus,
	LearnedTerm,
} from '@/types/knowledge';

/** Where a person reviews what they and their colleagues taught Lexis. */
export const KNOWLEDGE_PATH = '/knowledge';

/** The server's own words for a lost optimistic lock (`VersionConflict`). */
const CONFLICT_MARKER = 'changed since it was loaded';

/** Whether an error message says the item changed under the person: never overwrite, reload. */
export const isVersionConflict = (message: string | undefined): boolean =>
	Boolean(message && message.includes(CONFLICT_MARKER));

export const MAX_NAME = 200;
export const MAX_DEFINITION = 2000;

const STATUS_LABELS: Record<KnowledgeStatus, string> = {
	draft: 'Draft',
	in_review: 'In review',
	certified: 'Approved',
	needs_revalidation: 'Needs a second look',
	conflicted: 'Conflicts with another definition',
	deprecated: 'Withdrawn',
	rejected: 'Rejected',
};

export const statusLabel = (status: KnowledgeStatus): string => STATUS_LABELS[status] ?? status;

export const canDo = (item: Pick<KnowledgeItem, 'allowed_actions'>, action: KnowledgeAction) =>
	item.allowed_actions.includes(action);

const text = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');

/** The name the item is about: the term itself, or the term a synonym belongs to. */
export const itemTitle = (item: Pick<KnowledgeItem, 'kind' | 'content'>): string =>
	text(item.kind === 'synonym' ? item.content.term : item.content.name) || 'Untitled';

/** The words under the title: the definition, or the synonyms offered. */
export const itemBody = (item: Pick<KnowledgeItem, 'kind' | 'content'>): string => {
	if (item.kind === 'synonym') {
		const synonyms = item.content.synonyms;
		return Array.isArray(synonyms) ? synonyms.map(text).filter(Boolean).join(', ') : '';
	}
	return text(item.content.definition);
};

/** The database the item is about, or `null` for a glossary entry. */
export const itemDatabase = (item: Pick<KnowledgeItem, 'content'>): string | null =>
	text(item.content.database) || null;

/** How the item came to be, in one plain line. */
export const provenanceLabel = (provenance: Record<string, unknown>): string => {
	if (provenance.source === 'clarification') {
		const choice = provenance.free_text === true ? 'typed an answer' : 'chose an option';
		return `Learned from a clarification question: they ${choice}`;
	}
	if (provenance.source === 'manual') return 'Written by hand';
	return 'Source not recorded';
};

/** `answered_at` or `asked_at` of a clarification, or `null`. */
export const provenanceTime = (
	provenance: Record<string, unknown>,
	key: 'asked_at' | 'answered_at',
): string | null => {
	const value = provenance[key];
	return typeof value === 'string' && !Number.isNaN(Date.parse(value)) ? value : null;
};

const EVENT_LABELS: Record<string, string> = {
	propose: 'Created',
	edit: 'Edited',
	submit: 'Submitted for review',
	approve: 'Approved',
	reject: 'Rejected',
	request_changes: 'Sent back for changes',
	deprecate: 'Withdrawn',
	promote_scope: 'Shared with everyone',
	mark_conflict: 'Marked as conflicting',
	mark_revalidation: 'Marked for a second look',
	revalidate_ok: 'Confirmed again',
};

/** "Submitted for review by a@b.c": one line of the history. */
export const eventLabel = (
	event: Pick<KnowledgeEvent, 'action' | 'actor_email' | 'actor_id' | 'actor_type'>,
) => {
	const what = EVENT_LABELS[event.action] ?? event.action;
	const who =
		event.actor_type === 'user'
			? event.actor_email || event.actor_id
			: event.actor_type === 'agent'
				? 'Lexis'
				: 'the system';
	return `${what} by ${who}`;
};

/** The person an item came from, for a reviewer. */
export const proposerLabel = (item: Pick<KnowledgeItem, 'owner_email' | 'owner_id'>): string =>
	item.owner_email || item.owner_id;

export type TermForm = { name: string; definition: string };

/** The problem with a term form, or `null` when it can be sent. */
export const termFormError = ({ name, definition }: TermForm): string | null => {
	if (!name.trim()) return 'Give the term a name.';
	if (name.trim().length > MAX_NAME) return `The name is limited to ${MAX_NAME} characters.`;
	if (!definition.trim()) return 'Write what the term means.';
	if (definition.trim().length > MAX_DEFINITION)
		return `The definition is limited to ${MAX_DEFINITION} characters.`;
	return null;
};

/** The line shown under an answer that taught Lexis a term. */
export const learnedTermLine = (learned: LearnedTerm): string =>
	`Saved as your draft definition: ${learned.name}`;

/** A learned term from an answer's wire shape, or `undefined` when it is absent or malformed. */
export const parseLearnedTerm = (value: unknown): LearnedTerm | undefined => {
	if (value == null || typeof value !== 'object') return undefined;
	const { id, name } = value as { id?: unknown; name?: unknown };
	return typeof id === 'string' && id && typeof name === 'string' && name
		? { id, name }
		: undefined;
};
