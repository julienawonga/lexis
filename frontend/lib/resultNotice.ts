// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

/**
 * Two things the result bubble (Message 2) must say in plain words.
 *
 * A result cut at the row limit carries a leading `> **Result note:** ...` line
 * in the stored message content (written by `build_result_message` in
 * auto_ontology/server/chat/helpers.py), so it survives a reload with no extra
 * column. A result with no rows is recognised from the stored rows themselves.
 */
const RESULT_NOTE = /^> \*\*Result note:\*\* ([^\n]+)(?:\n+|$)/;

export const NO_ROWS_MESSAGE = 'The query ran and returned no rows.';

/** Split the cut-result notice off the front of a result message's content. */
export const splitResultNotice = (
	content: string | null | undefined,
): { notice: string | null; body: string } => {
	const text = content ?? '';
	const match = RESULT_NOTE.exec(text);
	if (!match) return { notice: null, body: text };
	return { notice: match[1], body: text.slice(match[0].length) };
};

/** Whether the stored result is an executed query that returned zero rows. */
export const isEmptyResult = (sqlResponse: string | null | undefined): boolean => {
	if (!sqlResponse) return false;
	try {
		let value: unknown = JSON.parse(sqlResponse);
		if (Array.isArray(value) && value.length === 1 && typeof value[0] === 'string') {
			value = JSON.parse(value[0]);
		}
		return Array.isArray(value) && value.length === 0;
	} catch {
		return false;
	}
};
