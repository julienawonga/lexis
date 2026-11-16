// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect } from 'react';
import { StatusScreen } from '@/common/StatusScreen';

// Shown when a page fails while rendering. The exception text is never put on
// screen: it can carry server details. The digest is the id to look up in the
// server log.
const ErrorPage = ({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) => {
	useEffect(() => {
		console.error(error);
	}, [error]);

	return (
		<StatusScreen
			title="Something went wrong"
			message="This page could not be shown. Trying again often works; if it keeps failing, tell your administrator."
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
	);
};

export default ErrorPage;
