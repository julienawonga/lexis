// SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { knowledgeApi } from '@/api/knowledge';
import type { ResponseWithError } from '@/api/types';
import { Button } from '@/common/Button';
import { ConfirmModal } from '@/common/modal';
import { ButtonTheme, Size } from '@/enums/button';
import {
	canDo,
	eventLabel,
	isVersionConflict,
	itemBody,
	itemDatabase,
	itemTitle,
	proposerLabel,
	provenanceLabel,
	provenanceTime,
	statusLabel,
	termFormError,
} from '@/lib/knowledge';
import type { KnowledgeItem, KnowledgeItemResponse } from '@/types/knowledge';

export type KnowledgeCardMode = 'mine' | 'review';

type KnowledgeItemCardProps = {
	item: KnowledgeItem;
	mode: KnowledgeCardMode;
};

type Pending = 'reject' | 'changes' | null;

const fieldClass =
	'w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm text-heading dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100';

const when = (value: string | null): string => (value ? new Date(value).toLocaleString() : '');

export const KnowledgeItemCard = ({ item, mode }: KnowledgeItemCardProps) => {
	const queryClient = useQueryClient();
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [conflict, setConflict] = useState(false);
	const [editing, setEditing] = useState(false);
	const [name, setName] = useState(itemTitle(item));
	const [definition, setDefinition] = useState(itemBody(item));
	const [pending, setPending] = useState<Pending>(null);
	const [comment, setComment] = useState('');
	const [confirmingApprove, setConfirmingApprove] = useState(false);
	const [historyOpen, setHistoryOpen] = useState(false);

	const history = useQuery({
		queryKey: ['knowledge-item', item.id, item.current_version, item.status],
		enabled: historyOpen,
		queryFn: async () => {
			const res = await knowledgeApi.get(item.id);
			if (res.error) throw new Error(res.message ?? 'Could not load the history');
			return res.events;
		},
	});

	const reload = () => {
		setConflict(false);
		setError(null);
		setEditing(false);
		void queryClient.invalidateQueries({ queryKey: ['knowledge-items'] });
	};

	// One path for every action: a lost optimistic lock never overwrites anything,
	// it asks the person to reload; any other refusal shows the server's words.
	const run = async (call: () => Promise<ResponseWithError<KnowledgeItemResponse>>) => {
		setBusy(true);
		setError(null);
		const res = await call();
		setBusy(false);
		if (res.error) {
			if (isVersionConflict(res.message)) setConflict(true);
			else setError(res.message ?? 'Something went wrong. Please try again.');
			setConfirmingApprove(false);
			return false;
		}
		setPending(null);
		setComment('');
		setEditing(false);
		setConfirmingApprove(false);
		void queryClient.invalidateQueries({ queryKey: ['knowledge-items'] });
		return true;
	};

	const formError = editing ? termFormError({ name, definition }) : null;
	const database = itemDatabase(item);
	const asked = provenanceTime(item.provenance, 'asked_at');
	const answered = provenanceTime(item.provenance, 'answered_at');
	const version = item.current_version;

	return (
		<li className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white/70 p-4 dark:border-zinc-700 dark:bg-white/[0.04]">
			<div className="flex flex-wrap items-start justify-between gap-2">
				<div className="min-w-0">
					<h3 className="wrap-anywhere text-base font-semibold text-heading dark:text-zinc-100">
						{itemTitle(item)}
					</h3>
					<p className="text-xs text-secondary dark:text-zinc-400">
						{item.kind === 'synonym' ? 'Synonyms' : 'Term'}
						{database ? ` · ${database}` : ' · all databases'}
						{item.scope === 'personal' ? ' · only visible to its owner' : ''}
					</p>
				</div>
				<span className="rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs font-medium text-body dark:bg-zinc-800 dark:text-zinc-300">
					{statusLabel(item.status)}
				</span>
			</div>

			{editing ? (
				<div className="flex flex-col gap-2">
					<label className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
						Term
						<input
							className={fieldClass}
							value={name}
							onChange={(event) => setName(event.target.value)}
						/>
					</label>
					<label className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
						What it means
						<textarea
							className={fieldClass}
							rows={4}
							value={definition}
							onChange={(event) => setDefinition(event.target.value)}
						/>
					</label>
					{formError && (
						<p className="text-sm text-red-700 dark:text-red-300">{formError}</p>
					)}
					<div className="flex gap-2">
						<Button
							theme={ButtonTheme.Primary}
							size={Size.REGULAR}
							type="button"
							disabled={busy || formError !== null}
							onClick={() => {
								void run(() =>
									knowledgeApi.edit(item.id, { name, definition }, version),
								);
							}}
						>
							Save
						</Button>
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => {
								setEditing(false);
								setName(itemTitle(item));
								setDefinition(itemBody(item));
							}}
						>
							Cancel
						</Button>
					</div>
				</div>
			) : (
				<p className="wrap-anywhere whitespace-pre-wrap text-sm text-body dark:text-zinc-300">
					{itemBody(item)}
				</p>
			)}

			<div className="flex flex-col gap-0.5 text-xs text-secondary dark:text-zinc-400">
				<span>
					Proposed by <span className="font-medium">{proposerLabel(item)}</span>
					{answered ? ` on ${when(answered)}` : ` on ${when(item.created)}`}
				</span>
				<span>
					{provenanceLabel(item.provenance)}
					{asked ? ` (asked ${when(asked)})` : ''}
				</span>
			</div>

			{conflict && (
				<div
					role="alert"
					className="flex flex-wrap items-center gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-200"
				>
					<span>
						This item changed since you opened it. Nothing was overwritten. Reload to
						see the latest version, then try again.
					</span>
					<Button
						theme={ButtonTheme.Secondary}
						size={Size.SMALL}
						type="button"
						onClick={reload}
					>
						Reload
					</Button>
				</div>
			)}
			{error && (
				<p
					role="alert"
					className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300"
				>
					{error}
				</p>
			)}

			{pending && (
				<div className="flex flex-col gap-2">
					<label className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
						{pending === 'reject' ? 'Why is it rejected?' : 'What should change?'}{' '}
						(required)
						<textarea
							className={fieldClass}
							rows={3}
							value={comment}
							onChange={(event) => setComment(event.target.value)}
						/>
					</label>
					<div className="flex gap-2">
						<Button
							theme={pending === 'reject' ? ButtonTheme.Danger : ButtonTheme.Primary}
							size={Size.REGULAR}
							type="button"
							disabled={busy || !comment.trim()}
							onClick={() => {
								const text = comment.trim();
								void run(() =>
									pending === 'reject'
										? knowledgeApi.reject(item.id, text, version)
										: knowledgeApi.requestChanges(item.id, text, version),
								);
							}}
						>
							{pending === 'reject' ? 'Reject' : 'Send back'}
						</Button>
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => {
								setPending(null);
								setComment('');
							}}
						>
							Cancel
						</Button>
					</div>
				</div>
			)}

			{!editing && !pending && (
				<div className="flex flex-wrap gap-2">
					{mode === 'mine' && item.kind === 'term' && canDo(item, 'edit') && (
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => setEditing(true)}
						>
							Edit
						</Button>
					)}
					{mode === 'mine' && canDo(item, 'submit') && (
						<Button
							theme={ButtonTheme.Primary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => {
								void run(() => knowledgeApi.submit(item.id, version));
							}}
						>
							Submit for review
						</Button>
					)}
					{mode === 'mine' && canDo(item, 'deprecate') && (
						<Button
							theme={ButtonTheme.DangerSubtle}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => {
								void run(() => knowledgeApi.withdraw(item.id, version));
							}}
						>
							Withdraw
						</Button>
					)}
					{mode === 'review' && canDo(item, 'approve') && (
						<Button
							theme={ButtonTheme.Primary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => setConfirmingApprove(true)}
						>
							Approve
						</Button>
					)}
					{mode === 'review' && canDo(item, 'request_changes') && (
						<Button
							theme={ButtonTheme.Secondary}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => setPending('changes')}
						>
							Request changes
						</Button>
					)}
					{mode === 'review' && canDo(item, 'reject') && (
						<Button
							theme={ButtonTheme.DangerSubtle}
							size={Size.REGULAR}
							type="button"
							disabled={busy}
							onClick={() => setPending('reject')}
						>
							Reject
						</Button>
					)}
				</div>
			)}

			<details
				onToggle={(event) =>
					setHistoryOpen((event.currentTarget as HTMLDetailsElement).open)
				}
			>
				<summary className="cursor-pointer text-xs font-medium text-primary dark:text-primary-soft">
					History
				</summary>
				{history.isPending && historyOpen ? (
					<p className="mt-2 text-xs text-secondary dark:text-zinc-400">Loading…</p>
				) : history.error ? (
					<p className="mt-2 text-xs text-red-700 dark:text-red-300">
						{history.error.message}
					</p>
				) : (
					<ol className="mt-2 flex flex-col gap-1 text-xs text-body dark:text-zinc-300">
						{(history.data ?? []).map((event) => (
							<li key={`${event.at}-${event.action}-${event.version}`}>
								<span className="text-secondary dark:text-zinc-400">
									{when(event.at)}
								</span>{' '}
								{eventLabel(event)}
								{event.comment ? `: “${event.comment}”` : ''}
							</li>
						))}
					</ol>
				)}
			</details>

			<ConfirmModal
				open={confirmingApprove}
				title="Approve this definition?"
				message={
					<>
						Approving shares <span className="font-semibold">{itemTitle(item)}</span>{' '}
						with everyone who uses Lexis. It is recorded under your name.
					</>
				}
				confirmLabel="Approve"
				tone="default"
				confirming={busy}
				onCancel={() => setConfirmingApprove(false)}
				onConfirm={() => {
					void run(() => knowledgeApi.approve(item.id, version));
				}}
			/>
		</li>
	);
};
