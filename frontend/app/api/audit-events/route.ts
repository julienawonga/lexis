// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// auditApi.list — read the audit log (admin only: `group:manage` is held by admins
// alone). The backend names the caller from the forwarded id and checks the role
// again, since the log lists people's emails.
export const GET = withPermission({ group: ['manage'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);
