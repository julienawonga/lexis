// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState, type ReactNode } from 'react';
import { glassFocus } from './glass';

type ResultSwitchProps = {
	chart: ReactNode;
	table: ReactNode;
	className?: string;
};

export const ResultSwitch = ({ chart, table, className }: ResultSwitchProps) => {
	const [activeTab, setActiveTab] = useState<'chart' | 'table'>('chart');

	return (
		<div className={className}>
			<div className="mb-2 flex justify-end">
				<div className="inline-flex rounded-lg bg-black/5 p-0.5 text-xs dark:bg-white/5">
					<button
						type="button"
						aria-pressed={activeTab === 'chart'}
						onClick={() => setActiveTab('chart')}
						className={`cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${glassFocus} ${
							activeTab === 'chart'
								? 'bg-primary text-white shadow-xs dark:bg-primary dark:text-white'
								: 'text-secondary hover:text-heading dark:text-zinc-400 dark:hover:text-zinc-200'
						}`}
					>
						Chart
					</button>
					<button
						type="button"
						aria-pressed={activeTab === 'table'}
						onClick={() => setActiveTab('table')}
						className={`cursor-pointer rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${glassFocus} ${
							activeTab === 'table'
								? 'bg-primary text-white shadow-xs dark:bg-primary dark:text-white'
								: 'text-secondary hover:text-heading dark:text-zinc-400 dark:hover:text-zinc-200'
						}`}
					>
						Table
					</button>
				</div>
			</div>
			{activeTab === 'chart' ? chart : table}
		</div>
	);
};
