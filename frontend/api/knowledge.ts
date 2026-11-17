// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import type { ResponseWithError } from './types';
import type {
	KnowledgeItemResponse,
	KnowledgeItemsPage,
	KnowledgeItemsQuery,
	KnowledgeStatusResponse,
} from '@/types/knowledge';

const BASE = 'knowledge-items';

/** The transitions that take an optional comment and the optimistic-lock token. */
type TransitionBody = { comment?: string; expected_version?: number };

const transition = (id: string, action: string, body: TransitionBody) =>
	requests.post<KnowledgeItemResponse>(`${BASE}/${encodeURIComponent(id)}/${action}`, body);

export const knowledgeApi = {
	/** Whether the feature is switched on. Never an error: the page and the nav ask it. */
	status: (): Promise<ResponseWithError<KnowledgeStatusResponse>> =>
		requests.get(`${BASE}/status`),

	/** One page of the items the caller may see, newest first. */
	list: (query: KnowledgeItemsQuery = {}): Promise<ResponseWithError<KnowledgeItemsPage>> =>
		requests.get(BASE, {
			...(query.status ? { status: query.status } : {}),
			...(query.kind ? { kind: query.kind } : {}),
			...(query.database ? { database: query.database } : {}),
			...(query.mine ? { mine: true } : {}),
			...(query.reviewable ? { reviewable: true } : {}),
			...(query.cursor ? { cursor: query.cursor } : {}),
			...(query.limit != null ? { limit: query.limit } : {}),
		}),

	get: (id: string): Promise<ResponseWithError<KnowledgeItemResponse>> =>
		requests.get(`${BASE}/${encodeURIComponent(id)}`),

	create: (body: {
		kind: 'term' | 'synonym';
		content: Record<string, unknown>;
		database?: string;
	}): Promise<ResponseWithError<KnowledgeItemResponse>> => requests.post(BASE, body),

	/** Replace a draft's content; refused with a conflict when it changed since `expectedVersion`. */
	edit: (
		id: string,
		content: Record<string, unknown>,
		expectedVersion: number,
	): Promise<ResponseWithError<KnowledgeItemResponse>> =>
		requests.patch(`${BASE}/${encodeURIComponent(id)}`, {
			content,
			expected_version: expectedVersion,
		}),

	submit: (id: string, expectedVersion?: number) =>
		transition(id, 'submit', { expected_version: expectedVersion }),
	approve: (id: string, expectedVersion?: number, comment?: string) =>
		transition(id, 'approve', { expected_version: expectedVersion, comment }),
	reject: (id: string, comment: string, expectedVersion?: number) =>
		transition(id, 'reject', { expected_version: expectedVersion, comment }),
	requestChanges: (id: string, comment: string, expectedVersion?: number) =>
		transition(id, 'request-changes', { expected_version: expectedVersion, comment }),
	withdraw: (id: string, expectedVersion?: number) =>
		transition(id, 'withdraw', { expected_version: expectedVersion }),
};
