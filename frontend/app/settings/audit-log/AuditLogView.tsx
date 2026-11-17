// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { auditApi } from '@/api/audit';
import { Button } from '@/common/Button';
import { EmptyState } from '@/common/EmptyState';
import { SkeletonRows } from '@/common/Skeleton';
import { ButtonTheme, Size } from '@/enums/button';
import { EmptyStateVariant } from '@/enums/emptyState';
import {
	AUDIT_ACTION_FILTERS,
	auditActorLabel,
	auditDetailsLabel,
	auditTargetLabel,
} from '@/lib/auditLog';

const PAGE_SIZE = 50;

export const AuditLogView = () => {
	const [prefix, setPrefix] = useState('');
	const { data, isPending, error, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
		useInfiniteQuery({
			queryKey: ['audit-events', prefix],
			initialPageParam: undefined as number | undefined,
			queryFn: async ({ pageParam }) => {
				const res = await auditApi.list({
					action_prefix: prefix || undefined,
					cursor: pageParam,
					limit: PAGE_SIZE,
				});
				if (res.error || !res.data)
					throw new Error(res.message ?? 'Could not load the audit log');
				return res;
			},
			getNextPageParam: (last) => last.next_cursor ?? undefined,
		});
	const events = data?.pages.flatMap((page) => page.data) ?? [];

	return (
		<div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-6">
			<div className="flex flex-wrap items-end justify-between gap-3">
				<div>
					<h1 className="text-xl font-semibold text-heading">Audit log</h1>
					<p className="text-sm text-zinc-600 dark:text-zinc-400">
						Administrative and governance actions, newest first. Secrets and question
						text are never recorded.
					</p>
				</div>
				<label className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
					Action
					<select
						className="rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
						value={prefix}
						onChange={(event) => setPrefix(event.target.value)}
					>
						{AUDIT_ACTION_FILTERS.map((filter) => (
							<option key={filter.prefix} value={filter.prefix}>
								{filter.label}
							</option>
						))}
					</select>
				</label>
			</div>

			{isPending ? (
				<SkeletonRows rows={8} />
			) : error ? (
				<div
					role="alert"
					className="flex flex-col items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
				>
					<span>{error.message}</span>
					<Button
						theme={ButtonTheme.Secondary}
						size={Size.REGULAR}
						type="button"
						onClick={() => {
							void refetch();
						}}
					>
						Retry
					</Button>
				</div>
			) : events.length === 0 ? (
				<EmptyState
					variant={EmptyStateVariant.Dashed}
					title="No events yet"
					description="Actions such as creating a Term or editing a connection appear here once they happen."
				/>
			) : (
				<>
					<div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-700">
						<table className="w-full text-left text-sm">
							<thead className="bg-zinc-50 text-xs uppercase text-zinc-500 dark:bg-zinc-800/60 dark:text-zinc-400">
								<tr>
									<th className="px-3 py-2 font-medium">When</th>
									<th className="px-3 py-2 font-medium">Who</th>
									<th className="px-3 py-2 font-medium">Action</th>
									<th className="px-3 py-2 font-medium">Target</th>
									<th className="px-3 py-2 font-medium">Details</th>
								</tr>
							</thead>
							<tbody className="divide-y divide-zinc-200 dark:divide-zinc-700">
								{events.map((event) => (
									<tr key={event.id} className="align-top">
										<td className="whitespace-nowrap px-3 py-2 text-zinc-600 dark:text-zinc-400">
											{new Date(event.at).toLocaleString()}
										</td>
										<td className="px-3 py-2 text-heading">
											{auditActorLabel(event)}
										</td>
										<td className="px-3 py-2 font-mono text-xs text-heading">
											{event.action}
										</td>
										<td className="px-3 py-2 text-heading">
											{auditTargetLabel(event)}
										</td>
										<td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">
											{auditDetailsLabel(event.details)}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
					{hasNextPage && (
						<div>
							<Button
								theme={ButtonTheme.Secondary}
								size={Size.REGULAR}
								type="button"
								disabled={isFetchingNextPage}
								onClick={() => {
									void fetchNextPage();
								}}
							>
								{isFetchingNextPage ? 'Loading…' : 'Load more'}
							</Button>
						</div>
					)}
				</>
			)}
		</div>
	);
};
