// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { requests } from './requests';
import type { ResponseWithError } from './types';
import type { AuditEventsPage, AuditEventsQuery } from '@/types/audit';

export const auditApi = {
	/** One page of the audit log, newest first. Administrators only. */
	list: ({ action_prefix, cursor, limit }: AuditEventsQuery = {}): Promise<
		ResponseWithError<AuditEventsPage>
	> =>
		requests.get('audit-events', {
			...(action_prefix ? { action_prefix } : {}),
			...(cursor != null ? { cursor } : {}),
			...(limit != null ? { limit } : {}),
		}),
};
