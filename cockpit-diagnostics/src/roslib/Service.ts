/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2026 CLAIRLab, HAW Hamburg.
 *
 * Cockpit ROS 2 Diagnostics is free software; you can redistribute it and/or modify it
 * under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation; either version 2.1 of the License, or
 * (at your option) any later version.
 *
 * Cockpit ROS 2 Diagnostics is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with Cockpit; If not, see <http://www.gnu.org/licenses/>.
 */

import type { Ros } from './Ros';

/*
 * A ROS service call over the Foxglove bridge.
 *
 * `Impl.sendServiceRequest` already speaks the protocol; this is the thin shell
 * around it, in the shape `Topic` has, plus the one thing the transport does
 * not provide: a deadline.
 *
 * The underlying promise resolves only when a `serviceCallResponse` with a
 * matching call id arrives. If the service never answers -- the node died
 * between the advertisement and the call, the bridge dropped it, the robot went
 * away -- it never settles, and a caller awaiting it waits forever. For a
 * button that actuates hardware that is the worst failure mode available: the
 * operator is left looking at a control that neither succeeded nor failed.
 */
const DEFAULT_TIMEOUT_MS = 5000;

export class ServiceCallTimeout extends Error {
    constructor(name: string, ms: number) {
        super(`Service ${name} did not answer within ${ms} ms`);
        this.name = "ServiceCallTimeout";
    }
}

export class Service<TRequest = object, TResponse = object> {
    readonly #ros: Ros;
    readonly #name: string;
    readonly #serviceType: string;
    readonly #timeoutMs: number;

    constructor(
        readonly options: {
            readonly ros: Ros;
            readonly name: string;
            readonly serviceType: string;
            readonly timeoutMs?: number;
        },
    ) {
        this.#ros = options.ros;
        this.#name = options.name;
        this.#serviceType = options.serviceType;
        this.#timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    }

    get name() {
        return this.#name;
    }

    get serviceType() {
        return this.#serviceType;
    }

    /*
     * Rejects rather than hanging: on timeout, on a closed connection, and on
     * anything the transport throws. Callers are expected to surface the
     * failure -- a service call whose outcome is unknown must never be
     * presented as success.
     */
    async call(request: TRequest): Promise<TResponse> {
        const impl = this.#ros.rosImpl;
        if (!impl) {
            throw new Error(`Not connected: cannot call ${this.#name}`);
        }

        let timer: ReturnType<typeof setTimeout> | undefined;
        const deadline = new Promise<never>((_resolve, reject) => {
            timer = setTimeout(
                () => reject(new ServiceCallTimeout(this.#name, this.#timeoutMs)),
                this.#timeoutMs,
            );
        });

        try {
            return await Promise.race([
                impl.sendServiceRequest<TRequest, TResponse>(this.#name, request),
                deadline,
            ]);
        } finally {
            if (timer !== undefined) {
                clearTimeout(timer);
            }
        }
    }
}
