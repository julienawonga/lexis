// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect } from 'react';
import { StatusScreen } from '@/common/StatusScreen';
import { THEME_INIT_SCRIPT } from '@/lib/theme';
import './globals.css';

// Replaces the root layout, so it brings its own document. This is what shows
// when the layout itself throws, for example when the auth database is down.
// No exception text is shown; the digest is the id to look up in the server log.
const GlobalError = ({
	error,
	retry,
}: {
	error: Error & { digest?: string };
	retry: () => void;
}) => {
	useEffect(() => {
		console.error(error);
	}, [error]);

	return (
		<html lang="en" className="h-full antialiased" suppressHydrationWarning>
			<head>
				<script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
			</head>
			<body className="flex h-full flex-col bg-glass-canvas font-sans text-heading dark:bg-glass-canvas-dark dark:text-zinc-100">
				<StatusScreen
					title="Lexis is unavailable"
					message="The app could not start, usually because a service it depends on is down. Try again in a moment."
					digest={error.digest}
					action={
						<button
							type="button"
							onClick={() => retry()}
							className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white"
						>
							Try again
						</button>
					}
				/>
			</body>
		</html>
	);
};

export default GlobalError;
