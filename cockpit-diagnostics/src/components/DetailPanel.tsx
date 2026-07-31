/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2025 Clearpath Robotics, Inc., a Rockwell Automation Company. All rights reserved.
 * Copyright (C) 2026 CLAIRLab, HAW Hamburg -- split out of DiagnosticsTreeTable, page-level panel.
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
    DescriptionList,
    DescriptionListDescription,
    DescriptionListGroup,
    DescriptionListTerm,
    DrawerActions,
    DrawerCloseButton,
    DrawerHead,
    DrawerPanelBody,
    Title,
} from "@patternfly/react-core";

import cockpit from 'cockpit';

import { DiagnosticsEntry } from "../interfaces";
import { SeverityIcon, severityLabel } from "./SeverityIcon";

const _ = cockpit.gettext;

// Moved here from DiagnosticsTreeTable: the selection now lives on the page, so
// whoever renders the panel has to be able to resolve a rawName.
export const findEntryByRawName = (
    entries: DiagnosticsEntry[],
    rawName: string,
): DiagnosticsEntry | null => {
    for (const entry of entries) {
        if (entry.rawName === rawName)
            return entry;
        const found = findEntryByRawName(entry.children, rawName);
        if (found)
            return found;
    }
    return null;
};

const Term = ({ label, children }: { label: string, children: React.ReactNode }) => (
    <DescriptionListGroup>
        <DescriptionListTerm>{label}</DescriptionListTerm>
        <DescriptionListDescription>{children}</DescriptionListDescription>
    </DescriptionListGroup>
);

export const DetailPanel = ({
    entry,
    onClose,
}: {
    entry: DiagnosticsEntry | null,
    onClose: () => void,
}) => {
    const panelRef = React.useRef<HTMLDivElement>(null);

    React.useEffect(() => {
        if (entry && panelRef.current)
            panelRef.current.focus();
    }, [entry]);

    if (!entry) {
        return null;
    }

    return (
        <>
            <DrawerHead>
                <Title headingLevel="h2" size="md">
                    <SeverityIcon level={entry.severity_level} /> {severityLabel(entry.severity_level)}
                </Title>
                <DrawerActions>
                    <DrawerCloseButton onClick={onClose} />
                </DrawerActions>
            </DrawerHead>
            <DrawerPanelBody>
                <div tabIndex={0} ref={panelRef} className="detail-body">
                    <Title headingLevel="h3" size="md">{entry.name}</Title>
                    <div className="detail-path">{entry.path}</div>
                    <p className="detail-message">{entry.message || _("No message")}</p>
                    <DescriptionList isHorizontal isCompact>
                        <Term label={_("Hardware ID")}>{entry.hardware_id || _("N/A")}</Term>
                        {/*
                          * A reclassified status must never look like the original:
                          * show what ROS actually reported and why it is displayed
                          * differently.
                          */}
                        {entry.override_reason && (
                            <Term label={_("Reported level")}>
                                {severityLabel(entry.reported_level)}
                                {" — "}
                                {_(entry.override_reason)}
                            </Term>
                        )}
                    </DescriptionList>
                    {entry.values && Object.keys(entry.values).length > 0 && (
                        <>
                            <Title headingLevel="h4" size="md" className="detail-values-title">
                                {_("Values")}
                            </Title>
                            <DescriptionList isHorizontal isCompact className="detail-values">
                                {Object.entries(entry.values).map(([key, value]) => (
                                    <Term key={key} label={key}>{String(value)}</Term>
                                ))}
                            </DescriptionList>
                        </>
                    )}
                </div>
            </DrawerPanelBody>
        </>
    );
};
