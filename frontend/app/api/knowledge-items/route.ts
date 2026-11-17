// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// Reading and proposing need the same permission as using the chat. What a person
// may approve, reject or edit is decided by the backend (the knowledge DAL's rules),
// not here: the web app only forwards the signed-in user's id.

// knowledgeApi.list
export const GET = withPermission({ chat: ['use'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);

// knowledgeApi.create — a personal draft owned by the caller.
export const POST = withPermission({ chat: ['use'] })((req, { user }) =>
	proxyToBackend(req, { userId: user.id }),
);
