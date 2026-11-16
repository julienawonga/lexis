// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';
import type { ChatMessage, PathStep, PathStepId } from '@/types/chat';
import { Icon, IconName } from '@/common/icons';
import { pathSteps } from '@/lib/answerPath';
import { SqlBlock } from '@/common/SqlBlock';
import { KnowledgeBreakdown } from './KnowledgeBreakdown';
import { glassFocus } from './glass';

type AnswerPathProps = {
	message: ChatMessage;
	defaultOpen?: boolean;
};

const formatStepClosedSummary = (step: PathStep): string => {
	switch (step.id) {
		case 'understood':
			return 'Understood';
		case 'knowledge':
			return 'Knowledge' + (step.summary ? ` ${step.summary}` : '');
		case 'sql':
			return 'SQL' + (step.summary ? ` (${step.summary})` : '');
		case 'run':
			return step.summary || 'Run';
	}
};

export const AnswerPath = ({ message, defaultOpen = false }: AnswerPathProps) => {
	const steps = pathSteps(message);
	const knownSteps = steps.filter((s) => s.known);

	const [isOpen, setIsOpen] = useState(defaultOpen);
	const [expandedStep, setExpandedStep] = useState<PathStepId | null>('sql');

	if (knownSteps.length === 0 && !message.database) {
		return null;
	}

	const databaseLine = message.database ? (
		<p className="text-[11px] text-secondary dark:text-zinc-400">
			Answered from database: <span className="font-medium">{message.database}</span>
		</p>
	) : null;

	if (knownSteps.length === 0) {
		return <div className="w-full text-xs">{databaseLine}</div>;
	}

	const closedSummaryText = 'How: ' + knownSteps.map(formatStepClosedSummary).join(' › ');

	const understoodThought = message.steps?.find(
		(s) => s.node === 'question_intent' || s.node === 'question_extraction',
	)?.thought;

	return (
		<div className="flex flex-col gap-2 w-full text-xs">
			{databaseLine}
			<button
				type="button"
				aria-expanded={isOpen}
				onClick={() => setIsOpen(!isOpen)}
				className={`group flex w-full cursor-pointer items-center justify-between rounded-xl bg-black/5 px-3 py-2 text-xs font-medium text-secondary transition-colors hover:bg-black/10 hover:text-heading dark:bg-white/5 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-zinc-200 ${glassFocus}`}
			>
				<span>{closedSummaryText}</span>
				<Icon
					name={IconName.ChevronRight}
					className={`h-3.5 w-3.5 shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`}
				/>
			</button>

			{isOpen && (
				<div className="relative ml-2 border-l border-black/10 pl-4 dark:border-white/10 flex flex-col gap-3 pt-1">
					{knownSteps.map((step) => {
						// A row opens only when it has something to show: the understood step
						// shows the engine's note on the question.
						const expandable = step.id !== 'understood' || Boolean(understoodThought);
						const isStepExpanded = expandable && expandedStep === step.id;

						return (
							<div key={step.id} className="relative flex flex-col gap-2">
								<span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-primary dark:bg-primary-soft" />

								<button
									type="button"
									disabled={!expandable}
									aria-expanded={expandable ? isStepExpanded : undefined}
									onClick={() => setExpandedStep(isStepExpanded ? null : step.id)}
									className={`flex w-full items-center justify-between text-left text-xs font-medium text-heading dark:text-zinc-100 transition-colors ${
										expandable
											? 'cursor-pointer hover:text-primary dark:hover:text-primary-soft'
											: 'cursor-default'
									} ${glassFocus}`}
								>
									<span>{step.title}</span>
									<div className="flex items-center gap-1.5 text-secondary dark:text-zinc-400">
										{step.summary && (
											<span className="text-[11px] font-normal">
												{step.summary}
											</span>
										)}
										{expandable && (
											<Icon
												name={IconName.ChevronRight}
												className={`h-3 w-3 shrink-0 transition-transform ${isStepExpanded ? 'rotate-90' : ''}`}
											/>
										)}
									</div>
								</button>

								{isStepExpanded && (
									<div className="mt-1 pl-1">
										{step.id === 'understood' &&
											(understoodThought ? (
												<p className="text-xs text-secondary dark:text-zinc-400 leading-relaxed">
													{understoodThought}
												</p>
											) : null)}

										{step.id === 'knowledge' && (
											<KnowledgeBreakdown entries={message.knowledgeTrace} />
										)}

										{step.id === 'sql' && message.sql && (
											<div className="flex flex-col gap-2">
												<SqlBlock
													sql={message.sql}
													label={
														message.sql
															.trim()
															.toUpperCase()
															.startsWith('PREDICT')
															? 'PQL'
															: 'SQL'
													}
												/>
												{message.content.trim() !== '' && (
													<details className="mt-1 text-xs text-secondary dark:text-zinc-400">
														<summary className="cursor-pointer font-medium hover:text-primary dark:hover:text-primary-soft transition-colors select-none">
															Model&apos;s description of the query
														</summary>
														<p className="mt-1 text-xs italic text-secondary dark:text-zinc-400 leading-relaxed">
															{message.content}
														</p>
													</details>
												)}
											</div>
										)}

										{step.id === 'run' && (
											<p className="text-xs text-secondary dark:text-zinc-400">
												{(step.summary || 'Run') + ' returned.'}
											</p>
										)}
									</div>
								)}
							</div>
						);
					})}
				</div>
			)}
		</div>
	);
};
