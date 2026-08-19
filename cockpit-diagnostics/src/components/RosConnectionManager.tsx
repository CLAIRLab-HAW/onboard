/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2025 Clearpath Robotics, Inc., a Rockwell Automation Company. All rights reserved.
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

import React, { useEffect, useRef } from "react";

import { DiagnosticsEntry, DiagnosticsStatus } from "../interfaces";
import * as ROSLIB from "../roslib/index";
import {
    LEVEL_NONE,
    overrideFor,
    rollUpOverrides,
} from "../utils/severity";
import { headlineLevel, summarise } from "../utils/summary";

interface RosConnectionManagerProps {
    namespace: string;
    url: string | null;
    onDiagnosticsUpdate: (diagnosticsStatus: DiagnosticsStatus) => void;
    onConnectionStatusChange: (connected: boolean) => void;
    onClearHistory: () => void;
    /*
     * Hands the live connection out so the one control that actuates hardware
     * can call a service over it. Fires with the instance once connected and
     * with null when the link drops, so a button can never sit enabled over a
     * dead socket.
     */
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    onRosChange?: (ros: any | null) => void;
}

// Helper function to build a nested DiagnosticsEntry tree
// Exported so the severity-override behaviour can be tested against captured
// aggregator payloads without standing up a websocket.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const buildDiagnosticsTree = (diagnostics: any[]): DiagnosticsEntry[] => {
    const root: DiagnosticsEntry[] = [];

    diagnostics.forEach(({ name, message, level, hardware_id, values }) => {
        const parts = name.split("/");
        let currentLevel = root;

        parts.forEach((part: string, index: number) => {
            if (!part) return; // Skip empty parts

            let existingEntry = currentLevel.find(entry => entry.name === part);

            if (!existingEntry) {
                const [baseName, suffix] = part.split(":");
                const path = parts.slice(0, index + 1).join("/")
                        .split(":")[0];
                existingEntry = {
                    name: index === parts.length - 1 && suffix ? suffix : baseName,
                    path,
                    rawName: path,
                    message: "",
                    severity_level: LEVEL_NONE,
                    reported_level: LEVEL_NONE,
                    override_reason: null,
                    hardware_id: null,
                    values: null,
                    children: [],
                };
                currentLevel.push(existingEntry);
            }

            if (index === parts.length - 1) {
                existingEntry.message = message || "";
                existingEntry.hardware_id = hardware_id || null;
                existingEntry.rawName = name;

                existingEntry.values = Array.isArray(values)
                    ? values.reduce((acc, { key, value }) => {
                        acc[key] = value;
                        return acc;
                    }, {})
                    : values && typeof values === "object"
                        ? Object.fromEntries(
                            Object.entries(values).map(([key, value]) => [key, value])
                        )
                        : {};

                const reported = level ?? LEVEL_NONE;
                const override = overrideFor(name, existingEntry.message, existingEntry.values);
                existingEntry.reported_level = reported;
                existingEntry.severity_level = override ? override.level : reported;
                existingEntry.override_reason = override ? override.reason : null;
            }

            currentLevel = existingEntry.children;
        });
    });

    // Propagate overridden levels into the analyzer groups above them.
    rollUpOverrides(root);

    return root;
};

export const RosConnectionManager: React.FC<RosConnectionManagerProps> = ({
    namespace,
    url,
    onDiagnosticsUpdate,
    onConnectionStatusChange,
    onClearHistory,
    onRosChange
}) => {
    const staleTimeoutId = useRef(0);
    const retryTimeoutId = useRef(0);

    useEffect(() => {
        if (!url) {
            console.warn("WebSocket URL is not set correctly. Skipping WebSocket configuration.");
            return;
        }

        console.log(`Creating new connection to ${url} for namespace ${namespace}`);
        const ros = new ROSLIB.Ros({ url });

        const diagnosticsTopic = new ROSLIB.Topic({
            ros,
            name: `${namespace}/diagnostics_agg`,
            messageType: "diagnostic_msgs/DiagnosticArray",
        });

        const retryDelay = 3000; // 3 seconds
        const timeoutDuration = 5000; // 5 seconds
        let retryConnection = true;

        const connectToWebSocket = () => {
            clearTimeout(staleTimeoutId.current);
            clearTimeout(retryTimeoutId.current);
            ros.connect(url);

            ros.on("connection", () => {
                onClearHistory();
                console.log("Connected to Foxglove bridge at " + url);
                onConnectionStatusChange(true);
                onRosChange?.(ros);

                diagnosticsTopic.subscribe((message) => {
                    // Clear the timeout if a new message is received
                    clearTimeout(staleTimeoutId.current);

                    // Process incoming diagnostics messages
                    if (Array.isArray(message.status)) {
                        const diagnosticsTree = buildDiagnosticsTree(
                            message.status.map(({ name, message, level, hardware_id, values }) => ({
                                name,
                                message,
                                level: level !== undefined ? level : -1,
                                hardware_id,
                                values,
                            }))
                        );

                        // Calculate overall level from diagnostics tree. Priority, not
                        // magnitude -- see utils/summary.ts:headlineLevel. A plain
                        // Math.max() here would feed Timeline's colour coding a level
                        // that cannot tell "only stale" from "error and stale both
                        // present", because the reduction has already thrown the
                        // distinction away.
                        const overallLevel = headlineLevel(summarise(diagnosticsTree));

                        // Extract timestamp from ROS message header
                        let timestamp = Date.now(); // Default fallback
                        if (message.header && message.header.stamp) {
                            // Convert ROS time (sec + nanosec) to JavaScript timestamp (milliseconds)
                            const sec = message.header.stamp.sec || 0;
                            const nanosec = message.header.stamp.nanosec || 0;
                            timestamp = sec * 1000 + Math.round(nanosec / 1000000);
                            // console.log(`Extracted timestamp from ROS message: ${new Date(timestamp).toISOString()}`);
                        } else {
                            console.log("No header.stamp found in message, using current time");
                        }

                        // Create DiagStatus object
                        const diagStatus: DiagnosticsStatus = {
                            timestamp,
                            level: overallLevel,
                            diagnostics: diagnosticsTree
                        };

                        onDiagnosticsUpdate(diagStatus);
                    } else {
                        console.warn("Unexpected diagnostics data format:", message);
                    }

                    // Set a timeout to clear stale diagnostics if no new message is received
                    staleTimeoutId.current = setTimeout(() => {
                        console.warn("No diagnostics message received for 5 seconds. Clearing stale diagnostics.");
                        onClearHistory();
                    }, timeoutDuration);
                });
                console.log(`Subscribed to topic: ${diagnosticsTopic.name}`);
            });

            ros.on("error", (error) => {
                console.error("Error connecting to Foxglove bridge:", error);
                ros.close();
            });

            ros.on("close", () => {
                onConnectionStatusChange(false);
                onRosChange?.(null);
                console.log("Connection to Foxglove bridge closed");
                onClearHistory();
                clearTimeout(staleTimeoutId.current);
                clearTimeout(retryTimeoutId.current);
                if (retryConnection) {
                    console.log("Retrying WebSocket connection...");
                    retryTimeoutId.current = setTimeout(connectToWebSocket, retryDelay);
                }
            });
        };

        connectToWebSocket();

        // Cleanup function
        return () => {
            console.log(`Cleaning up connection for namespace ${namespace}`);
            diagnosticsTopic.unsubscribe();
            retryConnection = false;
            clearTimeout(staleTimeoutId.current);
            clearTimeout(retryTimeoutId.current);
            ros.close();
        };
    }, [namespace, url, onDiagnosticsUpdate, onConnectionStatusChange, onClearHistory, onRosChange]);

    return null; // This component does not render anything
};
