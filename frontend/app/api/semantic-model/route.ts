// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

import { withPermission } from '@/auth/with-auth';
import { proxyToBackend } from '@/auth/proxy-backend';

// Read-only, agent-neutral semantic model document.
export const GET = withPermission({ catalog: ['read'] })((req) => proxyToBackend(req));
