// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import Link from 'next/link';
import { StatusScreen } from '@/common/StatusScreen';

const NotFound = () => (
	<StatusScreen
		title="Page not found"
		message="This page does not exist or has moved."
		action={
			<Link
				href="/chat"
				className="rounded-xl bg-primary px-4 py-2 text-sm font-medium text-white"
			>
				Back to chat
			</Link>
		}
	/>
);

export default NotFound;
