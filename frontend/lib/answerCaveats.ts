// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import type { AnswerCaveat, ChatMessage } from '@/types/chat';

/**
 * The structured caveats of an answer, minus `validation_unresolved`: that one
 * is already shown by the note appended to the answer text, so listing it again
 * would say the same thing twice.
 */
export const extraCaveats = (message: Pick<ChatMessage, 'caveats'>): AnswerCaveat[] =>
	(message.caveats ?? []).filter((caveat) => caveat.code !== 'validation_unresolved');
