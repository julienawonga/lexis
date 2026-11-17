// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { knowledgeApi } from '@/api/knowledge';
import { Button } from '@/common/Button';
import { EmptyState } from '@/common/EmptyState';
import { SkeletonRows } from '@/common/Skeleton';
import { ButtonTheme, Size } from '@/enums/button';
import { EmptyStateVariant } from '@/enums/emptyState';
import { KnowledgeItemCard, type KnowledgeCardMode } from './KnowledgeItemCard';

const PAGE_SIZE = 20;

const TABS: { id: KnowledgeCardMode; label: string }[] = [
	{ id: 'mine', label: 'My drafts' },
	{ id: 'review', label: 'To review' },
];

const EMPTY: Record<KnowledgeCardMode, { title: string; description: string }> = {
	mine: {
		title: 'No drafts yet',
		description:
			'When you answer one of Lexis’s clarification questions, your answer is saved here as a draft definition that only you can see.',
	},
	review: {
		title: 'Nothing to review',
		description:
			'Definitions that people submit for review, and that you may approve, appear here.',
	},
};

const ErrorBox = ({ message, onRetry }: { message: string; onRetry: () => void }) => (
	<div
		role="alert"
		className="flex flex-col items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
	>
		<span>{message}</span>
		<Button theme={ButtonTheme.Secondary} size={Size.REGULAR} type="button" onClick={onRetry}>
			Retry
		</Button>
	</div>
);

const KnowledgeList = ({ mode }: { mode: KnowledgeCardMode }) => {
	const { data, isPending, error, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } =
		useInfiniteQuery({
			queryKey: ['knowledge-items', mode],
			initialPageParam: undefined as string | undefined,
			queryFn: async ({ pageParam }) => {
				const res = await knowledgeApi.list({
					...(mode === 'mine'
						? { mine: true }
						: { reviewable: true, status: 'in_review' as const }),
					cursor: pageParam,
					limit: PAGE_SIZE,
				});
				if (res.error || !res.data)
					throw new Error(res.message ?? 'Could not load the definitions');
				return res;
			},
			getNextPageParam: (last) => last.next_cursor ?? undefined,
		});
	const items = data?.pages.flatMap((page) => page.data) ?? [];

	if (isPending) return <SkeletonRows rows={4} />;
	if (error)
		return (
			<ErrorBox
				message={error.message}
				onRetry={() => {
					void refetch();
				}}
			/>
		);
	if (items.length === 0)
		return (
			<EmptyState
				variant={EmptyStateVariant.Dashed}
				title={EMPTY[mode].title}
				description={EMPTY[mode].description}
			/>
		);
	return (
		<>
			<ul className="flex flex-col gap-3">
				{items.map((item) => (
					// The version is in the key so a reload replaces the card (and its form)
					// with the latest content instead of keeping a stale draft of it.
					<KnowledgeItemCard
						key={`${item.id}-${item.current_version}-${item.status}`}
						item={item}
						mode={mode}
					/>
				))}
			</ul>
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
	);
};

export const KnowledgeView = () => {
	const [tab, setTab] = useState<KnowledgeCardMode>('mine');
	const status = useQuery({
		queryKey: ['knowledge-status'],
		queryFn: async () => {
			const res = await knowledgeApi.status();
			if (res.error) throw new Error(res.message ?? 'Could not check this feature');
			return res.enabled;
		},
	});

	return (
		<div className="mx-auto flex w-full max-w-4xl flex-col gap-4 p-6">
			<div>
				<h1 className="text-xl font-semibold text-heading">What Lexis learned</h1>
				<p className="text-sm text-zinc-600 dark:text-zinc-400">
					Definitions taken from your answers. They stay in your own space until you
					submit them and an owner approves them for everyone.
				</p>
			</div>

			{status.isPending ? (
				<SkeletonRows rows={4} />
			) : status.error ? (
				<ErrorBox
					message={status.error.message}
					onRetry={() => {
						void status.refetch();
					}}
				/>
			) : !status.data ? (
				<EmptyState
					variant={EmptyStateVariant.Dashed}
					title="Not turned on"
					description="Learning from answers is not enabled on this server."
				/>
			) : (
				<>
					<div
						role="tablist"
						aria-label="Definitions"
						className="flex gap-1 border-b border-zinc-200 dark:border-zinc-700"
					>
						{TABS.map(({ id, label }) => (
							<button
								key={id}
								type="button"
								role="tab"
								aria-selected={tab === id}
								onClick={() => setTab(id)}
								className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
									tab === id
										? 'border-primary text-primary dark:text-primary-soft'
										: 'border-transparent text-secondary hover:text-heading dark:text-zinc-400 dark:hover:text-zinc-100'
								}`}
							>
								{label}
							</button>
						))}
					</div>
					<KnowledgeList key={tab} mode={tab} />
				</>
			)}
		</div>
	);
};
