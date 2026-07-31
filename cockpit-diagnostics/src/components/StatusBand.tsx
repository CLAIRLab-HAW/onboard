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

import React from 'react';
import {
    Button,
    Dropdown,
    DropdownList,
    Flex,
    FlexItem,
    MenuToggle,
    MenuToggleElement,
} from "@patternfly/react-core";
import { EllipsisVIcon, PauseIcon, PlayIcon } from "@patternfly/react-icons";

import cockpit from 'cockpit';

import { DiagnosticsEntry } from "../interfaces";
import { FilterLevel } from "../utils/treeFilter";
import { SeverityIcon } from "./SeverityIcon";
import { headline, headlineLevel, summarise } from "../utils/summary";

const _ = cockpit.gettext;

/*
 * The band answers "is the robot fine?" without scrolling.
 *
 * Everything in here is derived, never stored: the sentence, the counters and
 * the worst level all come out of the tree that is currently on display -- which
 * on a frozen timeline is a past snapshot, not the live one. That is also why
 * the timestamp shown is the snapshot's and not the wall clock.
 */

const Kpi = ({
    value,
    label,
    onClick,
}: {
    value: number,
    label: string,
    onClick?: () => void,
}) => {
    // A counter at zero is not a filter anybody wants: clicking "0 errors" would
    // still open a threshold that lists stale messages.
    const clickable = onClick !== undefined && value > 0;
    const body = (
        <>
            <b className={value > 0 ? "status-kpi-value status-kpi-hit" : "status-kpi-value"}>{value}</b>
            <span className="status-kpi-label">{label}</span>
        </>
    );

    if (!clickable) {
        return <div className="status-kpi">{body}</div>;
    }
    return (
        // `aria-label` overrides the element's content rather than adding to it,
        // so a bare `label` here would read "Warnings" and drop the count -- on
        // exactly the counters that are non-zero. The count has to be in the
        // label itself.
        <Button
            variant="plain"
            className="status-kpi"
            onClick={onClick}
            aria-label={cockpit.format(_("$0 $1"), value, label)}
        >
            {body}
        </Button>
    );
};

export const StatusBand = ({
    namespace,
    diagnostics,
    timestamp,
    bridgeConnected,
    rateHz,
    isPaused,
    onTogglePause,
    onFilterLevel,
    menuItems,
    children,
}: {
    namespace: string,
    diagnostics: DiagnosticsEntry[],
    timestamp: number | null,
    bridgeConnected: boolean,
    rateHz: number | null,
    isPaused: boolean,
    onTogglePause: () => void,
    onFilterLevel: (level: FilterLevel) => void,
    menuItems: React.ReactNode,
    children?: React.ReactNode,
}) => {
    const [menuOpen, setMenuOpen] = React.useState(false);
    const summary = summarise(diagnostics);
    // Empty until robot.yaml resolves a namespace. Rendering the em dash
    // anyway would leave a dangling "— operational" with nothing in front of
    // it, so the separator only appears once there is a name to attach it to.
    const displayNamespace = namespace.replace(/^\//, "");

    const facts = [
        namespace,
        bridgeConnected ? _("Bridge connected") : _("Bridge disconnected"),
        rateHz !== null ? cockpit.format(_("$0 Hz"), rateHz.toFixed(1)) : null,
        timestamp !== null
            ? cockpit.format(_("as of $0"), new Date(timestamp).toLocaleTimeString())
            : null,
    ].filter(Boolean);

    return (
        <div className="status-band">
            <Flex
                justifyContent={{ default: 'justifyContentSpaceBetween' }}
                alignItems={{ default: 'alignItemsFlexStart' }}
            >
                <FlexItem>
                    <h1 className="status-headline">
                        {/*
                          * Same branch order headline() uses -- errors, then warnings,
                          * then stale -- so the symbol never contradicts the sentence
                          * next to it. `summary.worst` alone cannot do this: see
                          * utils/summary.ts:headlineLevel.
                          */}
                        <SeverityIcon level={headlineLevel(summary)} />
                        {" "}
                        {displayNamespace && <>{displayNamespace}{" — "}</>}
                        <span className="status-headline-state">{headline(summary)}</span>
                    </h1>
                    <div className="status-facts">{facts.join(" · ")}</div>
                </FlexItem>
                <FlexItem>
                    <Flex
                        alignItems={{ default: 'alignItemsCenter' }}
                        spaceItems={{ default: 'spaceItemsLg' }}
                    >
                        <Kpi value={summary.errors} label={_("Errors")} onClick={() => onFilterLevel("error")} />
                        <Kpi value={summary.warnings} label={_("Warnings")} onClick={() => onFilterLevel("warn")} />
                        <Kpi value={summary.stale} label={_("Stale")} />
                        <Kpi value={summary.total} label={_("Statuses")} />
                        <FlexItem>
                            <Button
                                variant="secondary"
                                icon={isPaused ? <PlayIcon /> : <PauseIcon />}
                                onClick={onTogglePause}
                                aria-label={isPaused ? _("Resume diagnostics updates") : _("Pause diagnostics updates")}
                            >
                                {isPaused ? _("Resume") : _("Pause")}
                            </Button>
                        </FlexItem>
                        <FlexItem>
                            <Dropdown
                                isOpen={menuOpen}
                                onOpenChange={setMenuOpen}
                                popperProps={{ position: 'right' }}
                                toggle={(ref: React.Ref<MenuToggleElement>) => (
                                    <MenuToggle
                                        ref={ref}
                                        variant="plain"
                                        aria-label={_("More actions")}
                                        onClick={() => setMenuOpen(!menuOpen)}
                                        isExpanded={menuOpen}
                                    >
                                        <EllipsisVIcon />
                                    </MenuToggle>
                                )}
                            >
                                <DropdownList>{menuItems}</DropdownList>
                            </Dropdown>
                        </FlexItem>
                    </Flex>
                </FlexItem>
            </Flex>
            {children}
        </div>
    );
};
