// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/** How often the compilation status is re-read while a run is in progress. */
export const COMPILATION_POLL_MS = 5000;

/** Poll only while a run is in progress; a finished run is read once. */
export const nextPollDelay = (running: boolean): number | null =>
	running ? COMPILATION_POLL_MS : null;
