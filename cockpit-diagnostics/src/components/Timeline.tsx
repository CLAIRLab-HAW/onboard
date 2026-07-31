/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2025 Clearpath Robotics, Inc., a Rockwell Automation Company. All rights reserved.
 * Copyright (C) 2026 CLAIRLab, HAW Hamburg -- band redesign, replaces the old ProgressStepper timeline.
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

import React, { useEffect, useState } from 'react';

import cockpit from 'cockpit';

import { DiagnosticsStatus } from "../interfaces";
import { HISTORY_SIZE } from '../hooks/useDiagHistory';
import { LEVEL_ERROR, LEVEL_STALE, LEVEL_WARN } from '../utils/severity';

const _ = cockpit.gettext;

/*
 * The retained snapshots as one band.
 *
 * Equal-height segments on purpose: varying heights read as a chart and invite
 * comparison of a quantity that does not exist here. Colour marks the snapshots
 * worth clicking; everything healthy stays neutral grey.
 *
 * Unfilled slots are rendered on the left so the newest snapshot always ends at
 * the right edge and the band keeps its width while the history fills up.
 */
const variantFor = (level: number): string => {
    if (level >= LEVEL_STALE) return "stale";
    if (level >= LEVEL_ERROR) return "error";
    if (level >= LEVEL_WARN) return "warn";
    return "ok";
};

export const Timeline = ({
    diagHistory,
    setDiagStatusDisplay,
    isPaused,
    setIsPaused,
}: {
    diagHistory: DiagnosticsStatus[],
    setDiagStatusDisplay: React.Dispatch<React.SetStateAction<DiagnosticsStatus | null>>,
    isPaused: boolean,
    setIsPaused: React.Dispatch<React.SetStateAction<boolean>>,
}) => {
    // -1 is the latest, -2 the one before it, ... (kept from the previous component).
    const [negIndex, setNegIndex] = useState(-1);

    useEffect(() => {
        if (!isPaused) {
            setNegIndex(-1);
            setDiagStatusDisplay(diagHistory.length > 0 ? diagHistory[diagHistory.length - 1] : null);
        }
    }, [diagHistory, setDiagStatusDisplay, isPaused]);

    const blanks = Math.max(0, HISTORY_SIZE - diagHistory.length);
    const selected = diagHistory.length + negIndex;

    return (
        <div className="timeline">
            <div className="timeline-band" role="group" aria-label={_("Diagnostics history")}>
                {Array.from({ length: blanks }).map((_unused, index) => (
                    <span key={`blank-${index}`} className="timeline-slot timeline-slot-empty" />
                ))}
                {diagHistory.map((snapshot, index) => (
                    <button
                        type="button"
                        key={index}
                        className={`timeline-slot timeline-slot-${variantFor(snapshot.level)}` +
                                   (isPaused && index === selected ? " timeline-slot-selected" : "")}
                        title={new Date(snapshot.timestamp).toLocaleTimeString()}
                        aria-label={cockpit.format(_("diagnostics snapshot $0"), index + 1)}
                        onClick={() => {
                            setDiagStatusDisplay(snapshot);
                            setIsPaused(true);
                            setNegIndex(index - diagHistory.length);
                        }}
                    />
                ))}
            </div>
            <div className="timeline-legend">
                <span>{diagHistory.length > 0
                    ? new Date(diagHistory[0].timestamp).toLocaleTimeString()
                    : _("no history yet")}
                </span>
                <span>{cockpit.format(_("$0 snapshots · click to freeze"), HISTORY_SIZE)}</span>
                <span>{isPaused ? _("frozen") : _("now")}</span>
            </div>
        </div>
    );
};
