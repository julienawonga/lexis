// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// Reading and proposing need the same permission as using the chat. What a person
// may approve, reject or edit is decided by the backend (the knowledge DAL's rules),
// not here: the web app only forwards the signed-in user's id.

// knowledgeApi.reject
export const POST = withPermission<{ params: Promise<{ item_id: string }> }>({ chat: ['use'] })(
	(req, { user }) => proxyToBackend(req, { userId: user.id }),
);
