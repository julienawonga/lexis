// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * "Latest request wins": hand out a ticket per request and apply a result only
 * if its ticket is still current. `invalidate` cancels every request in flight,
 * for example when the input the request was made from has since changed.
 */
export const createLatestGuard = () => {
	let current = 0;
	return {
		start: (): number => ++current,
		invalidate: (): void => {
			current += 1;
		},
		isCurrent: (ticket: number): boolean => ticket === current,
	};
};
