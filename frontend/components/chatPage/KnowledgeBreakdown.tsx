// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useMemo } from 'react';
import type { KnowledgeTraceEntry } from '@/types/chat';
import { Icon, IconName } from '@/common/icons';

type KnowledgeBreakdownProps = {
	entries?: KnowledgeTraceEntry[];
};

const kindLabels: Record<KnowledgeTraceEntry['kind'], string> = {
	term: 'term',
	sql_attribute: 'sql attribute',
	column_attribute: 'column attribute',
	custom_analysis: 'custom analysis',
};

export const KnowledgeBreakdown = ({ entries }: KnowledgeBreakdownProps) => {
	const { usedEntries, otherEntries, undecidedCount, notUsedCount } = useMemo(() => {
		if (!entries || entries.length === 0) {
			return { usedEntries: [], otherEntries: [], undecidedCount: 0, notUsedCount: 0 };
		}
		const used = entries.filter((e) => e.used === true);
		const undecided = entries.filter((e) => e.used === null);
		const notUsed = entries.filter((e) => e.used === false);
		return {
			usedEntries: used,
			otherEntries: [...undecided, ...notUsed],
			undecidedCount: undecided.length,
			notUsedCount: notUsed.length,
		};
	}, [entries]);

	if (!entries || entries.length === 0) {
		return null;
	}

	return (
		<div className="flex flex-col gap-3 text-xs">
			{usedEntries.length > 0 && (
				<div className="flex flex-col gap-2">
					<div className="text-[11px] font-medium text-secondary dark:text-zinc-400">
						Used in the SQL
					</div>
					<div className="flex flex-col gap-2">
						{usedEntries.map((entry) => (
							<div
								key={`${entry.kind}:${entry.id}`}
								className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-primary/5 p-2.5 dark:bg-primary-soft/10 border border-primary/10 dark:border-primary-soft/20"
							>
								<div className="flex items-center gap-1.5 min-w-0">
									{entry.certified === true && (
										<Icon
											name={IconName.Check}
											className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400"
										/>
									)}
									<span className="font-semibold text-heading dark:text-zinc-100 truncate">
										{entry.name}
									</span>
									<span className="text-[11px] text-secondary dark:text-zinc-400">
										({kindLabels[entry.kind] ?? entry.kind})
									</span>
								</div>
								<div className="flex items-center gap-1.5 text-[11px] text-secondary dark:text-zinc-400">
									<span>found in SQL</span>
									{entry.matched && entry.matched.length > 0 && (
										<div className="flex flex-wrap gap-1">
											{entry.matched.map((m, idx) => (
												<code
													key={idx}
													className="rounded bg-black/5 px-1 py-0.5 font-mono text-[10px] text-heading dark:bg-white/10 dark:text-zinc-200"
												>
													{m}
												</code>
											))}
										</div>
									)}
								</div>
							</div>
						))}
					</div>
				</div>
			)}

			{otherEntries.length > 0 && (
				<div className="flex flex-col gap-2">
					<div className="text-[11px] font-medium text-secondary dark:text-zinc-400">
						Also considered ({otherEntries.length}): {undecidedCount} undecided,{' '}
						{notUsedCount} not used
					</div>
					<div className="grid grid-cols-2 gap-2">
						{otherEntries.map((entry) => (
							<div
								key={`${entry.kind}:${entry.id}`}
								className="flex items-center gap-1.5 min-w-0 text-secondary dark:text-zinc-400"
							>
								{entry.used === null ? (
									<span className="h-2 w-2 shrink-0 rounded-full border border-secondary/60 dark:border-zinc-500" />
								) : (
									<span className="h-2 w-2 shrink-0 rounded-full bg-secondary/40 dark:bg-zinc-600" />
								)}
								{entry.certified === true && (
									<Icon
										name={IconName.Check}
										className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400"
									/>
								)}
								<span className="truncate text-xs">{entry.name}</span>
							</div>
						))}
					</div>
				</div>
			)}

			<p className="text-[11px] italic text-secondary/80 dark:text-zinc-500">
				&apos;Used&apos; is a text heuristic on the final SQL, not a proof.
			</p>
		</div>
	);
};
