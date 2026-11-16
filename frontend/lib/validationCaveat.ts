// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

/**
 * When automatic validation keeps rejecting every version of a query, the
 * engine stops and returns its best candidate with a note appended to the
 * answer text ("... so this answer was not fully validated. Check the SQL
 * before relying on it."). That note must never be hidden behind a fold: the
 * result next to it is shown as if it were an answer.
 */
const VALIDATION_CAVEAT = /this answer was not fully\s+validated/i;

export const hasValidationCaveat = (content: string | null | undefined): boolean =>
	Boolean(content) && VALIDATION_CAVEAT.test(content as string);
