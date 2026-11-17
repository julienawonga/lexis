<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

This is the [Next.js](https://nextjs.org) frontend of Lexis. The FastAPI backend
(port **3001**) must be running for the data and chat routes. See the
**[root README](../README.md)** for the full setup.

## Development

From `frontend/`:

```bash
pnpm dev      # Next.js dev server on http://localhost:3000
pnpm lint     # ESLint
pnpm format   # Prettier
pnpm build    # production build
```

The backend is started from the repo root, see the dev commands in
[`CLAUDE.md`](../CLAUDE.md).
