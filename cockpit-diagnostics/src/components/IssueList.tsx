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
import { Table, Tbody, Td, Tr } from "@patternfly/react-table";

import cockpit from 'cockpit';

import { DiagnosticsEntry } from "../interfaces";
import { SeverityIcon } from "./SeverityIcon";
import { issueEntries } from "../utils/summary";

const _ = cockpit.gettext;

/*
 * Everything worth acting on, in one list.
 *
 * Replaces the pair of alert-wrapped tables (errors, warnings) that each cost a
 * full empty state even when there was nothing to show -- and that reported
 * "No Errors" while the bridge was down, which was not the same thing at all.
 */
export const IssueList = ({
    diagnostics,
    setSelectedRawName,
}: {
    diagnostics: DiagnosticsEntry[],
    setSelectedRawName: (rawName: string | null) => void,
}) => {
    const issues = issueEntries(diagnostics);

    if (issues.length === 0) {
        return <div className="issue-empty">{_("No issues")}</div>;
    }

    return (
        <Table aria-label={_("Issues")} borders={false} variant="compact" className="issue-list">
            <Tbody>
                {issues.map(issue => (
                    <Tr key={issue.rawName} isClickable onRowClick={() => setSelectedRawName(issue.rawName)}>
                        <Td className="issue-level" modifier="fitContent">
                            <SeverityIcon level={issue.severity_level} hideOk />
                        </Td>
                        <Td>
                            <span className="diagnostics-table-name">{issue.name || _("N/A")}</span>
                            <div className="issue-path">{issue.path || _("N/A")}</div>
                        </Td>
                        <Td>{issue.message || _("N/A")}</Td>
                    </Tr>
                ))}
            </Tbody>
        </Table>
    );
};
