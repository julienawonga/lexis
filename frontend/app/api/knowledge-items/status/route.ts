// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// knowledgeApi.status — whether the feature is on. Never 404s, so the nav can hide the page.
export const GET = withPermission({ chat: ['use'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);
