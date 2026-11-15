// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useMemo } from 'react';
import type { KnowledgeTraceEntry } from '@/types/chat';

type KnowledgeTracePanelProps = {
	entries?: KnowledgeTraceEntry[];
	className?: string;
};

const kindLabels: Record<KnowledgeTraceEntry['kind'], string> = {
	term: 'term',
	sql_attribute: 'sql attribute',
	column_attribute: 'column attribute',
	custom_analysis: 'custom analysis',
};

export const KnowledgeTracePanel = ({ entries, className }: KnowledgeTracePanelProps) => {
	const sortedEntries = useMemo(() => {
		if (!entries || entries.length === 0) return [];
		const used = entries.filter((e) => e.used === true);
		const undecided = entries.filter((e) => e.used === null);
		const notUsed = entries.filter((e) => e.used === false);
		return [...used, ...undecided, ...notUsed];
	}, [entries]);

	if (!entries || entries.length === 0) {
		return null;
	}

	const usedCount = entries.filter((e) => e.used === true).length;

	return (
		<details className={`group text-xs text-secondary dark:text-zinc-400 ${className ?? ''}`}>
			<summary className="cursor-pointer font-medium hover:text-primary dark:hover:text-primary-soft transition-colors select-none">
				Knowledge offered to the SQL ({entries.length}), {usedCount} used
			</summary>
			<div className="mt-2 flex flex-col gap-2 rounded-xl border border-black/5 bg-black/[0.02] p-3 dark:border-white/10 dark:bg-white/[0.02]">
				<ul className="flex flex-col gap-2.5">
					{sortedEntries.map((entry) => {
						const statusWord =
							entry.used === true
								? 'used'
								: entry.used === false
									? 'not used'
									: 'undecided';

						return (
							<li key={`${entry.kind}:${entry.id}`} className="flex flex-col gap-0.5">
								<div className="flex flex-wrap items-center gap-1.5">
									<span className="font-medium text-heading dark:text-zinc-200">
										{entry.name}
									</span>
									<span className="rounded bg-black/5 px-1.5 py-0.5 text-[10px] font-semibold text-secondary uppercase dark:bg-white/10 dark:text-zinc-400">
										{kindLabels[entry.kind] ?? entry.kind}
									</span>
									{entry.certified === true && (
										<span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
											certified
										</span>
									)}
									{entry.certified === false && (
										<span className="rounded bg-zinc-500/10 px-1.5 py-0.5 text-[10px] font-medium text-zinc-500 dark:text-zinc-400">
											not certified
										</span>
									)}
									<span className="ml-auto text-[11px] font-medium text-secondary dark:text-zinc-400">
										{statusWord}
									</span>
								</div>
								{entry.matched && entry.matched.length > 0 && (
									<p className="text-[11px] text-secondary/80 dark:text-zinc-500 break-all">
										Matched: {entry.matched.join(', ')}
									</p>
								)}
							</li>
						);
					})}
				</ul>
				<p className="mt-1 text-[11px] italic text-secondary/70 dark:text-zinc-500 border-t border-black/5 dark:border-white/5 pt-1.5">
					&apos;Used&apos; is a text heuristic on the final SQL, not a proof.
				</p>
			</div>
		</details>
	);
};
