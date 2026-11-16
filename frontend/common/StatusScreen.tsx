// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ReactNode } from 'react';

// The card the error and not-found screens share, in the app's glass style.
export const StatusScreen = ({
	title,
	message,
	digest,
	action,
}: {
	title: string;
	message: string;
	digest?: string;
	action: ReactNode;
}) => (
	<div className="flex h-full w-full items-center justify-center overflow-y-auto p-6">
		<div className="glass flex w-full max-w-[420px] flex-col gap-4 rounded-[28px] border border-white/80 p-9 dark:border-white/10">
			<h1 className="text-2xl leading-tight font-bold tracking-tight text-glass-text dark:text-zinc-50">
				{title}
			</h1>
			<p className="text-sm text-secondary dark:text-zinc-400">{message}</p>
			{digest ? (
				<p className="font-mono text-xs text-secondary dark:text-zinc-500">
					Reference: {digest}
				</p>
			) : null}
			<div>{action}</div>
		</div>
	</div>
);
