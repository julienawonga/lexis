// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { parseSqlResponse } from '@/lib/parseSqlResponse';
import { hasValidationCaveat } from '@/lib/validationCaveat';
import type { ChatMessage, PathStep, PathStepId } from '@/types/chat';

/** Which engine nodes make up each step shown to the user. */
export const PATH_STEP_NODES: Record<PathStepId, readonly string[]> = {
	understood: ['question_intent', 'question_extraction'],
	knowledge: ['retrieve_candidates', 'prepare_candidates', 'refine_evidence'],
	sql: [
		'construct_sql_from_candidates',
		'reconstruct_sql',
		'check_value_repair',
		'precheck_combined',
		'validate_sql_values',
	],
	run: ['validate_sql_query', 'execute_sql_query', 'check_empty_like_result'],
};

const hasRun = (message: ChatMessage, id: PathStepId): boolean =>
	(message.steps ?? []).some((step) => PATH_STEP_NODES[id].includes(step.node));

const rowsLabel = (count: number): string =>
	`${count.toLocaleString('en-US')} ${count === 1 ? 'row' : 'rows'}`;

/**
 * The four steps shown under an answer, in order, with what the thread can say
 * about each. A step the thread knows nothing about is `known: false`, so a
 * conversation reloaded from history (no steps, no trace) shows only the SQL
 * and the rows it stored.
 */
export const pathSteps = (message: ChatMessage): PathStep[] => {
	const trace = message.knowledgeTrace ?? [];
	const used = trace.filter((entry) => entry.used === true).length;
	const table = parseSqlResponse(message.result?.sqlResponse ?? message.sqlResponse);

	let sqlSummary = '';
	if (hasValidationCaveat(message.content)) {
		sqlSummary = 'not fully validated';
	} else if (
		hasRun(message, 'sql') &&
		(message.steps ?? []).some((s) => s.node === 'reconstruct_sql')
	) {
		sqlSummary = 'corrected';
	} else if ((message.steps ?? []).length > 0) {
		sqlSummary = '1 attempt';
	}

	return [
		{
			id: 'understood',
			title: 'Understood the question',
			summary: '',
			known: hasRun(message, 'understood'),
		},
		{
			id: 'knowledge',
			title: 'Found knowledge',
			summary: trace.length > 0 ? `${trace.length} offered · ${used} used` : '',
			known: trace.length > 0,
		},
		{
			id: 'sql',
			title: 'Wrote the SQL',
			summary: sqlSummary,
			known: Boolean(message.sql),
		},
		{
			id: 'run',
			title: 'Checked and ran it',
			summary: table ? rowsLabel(table.rows.length) : '',
			known: table !== null,
		},
	];
};
