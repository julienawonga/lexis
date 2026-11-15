// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { isResultMessage } from '@/lib/answerMessages';
import type { ChatMessage } from '@/types/chat';

/** The half of an answer that carries the SQL ("Message 1"). */
const isSqlHalf = (message: ChatMessage): boolean =>
	message.role === 'assistant' &&
	Boolean(message.sql) &&
	!message.clarification &&
	!isResultMessage(message);

/** The half that carries the table or charts ("Message 2"). */
const isResultHalf = (message: ChatMessage): boolean =>
	isResultMessage(message) && !message.sql && !message.clarification;

/**
 * An answer reaches the thread as two assistant messages: the SQL, then the
 * result. To show the result first, fold each such pair into one message that
 * carries the SQL and a `result`. Display only: nothing is stored this way, and
 * every message that is not half of a pair passes through as the same object.
 */
export const groupAnswerTurns = (messages: ChatMessage[]): ChatMessage[] => {
	const turns: ChatMessage[] = [];
	for (let index = 0; index < messages.length; index++) {
		const message = messages[index];
		const next = messages[index + 1];
		if (next && isSqlHalf(message) && isResultHalf(next)) {
			turns.push({
				...message,
				result: { content: next.content, sqlResponse: next.sqlResponse },
				timestamp: next.timestamp,
			});
			index++;
		} else {
			turns.push(message);
		}
	}
	return turns;
};
