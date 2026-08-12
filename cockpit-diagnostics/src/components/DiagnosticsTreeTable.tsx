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

import React, { useEffect, useState, useCallback } from 'react';
import {
    Bullseye,
    Button,
    Card,
    CardBody,
    CardTitle,
    EmptyState,
    EmptyStateVariant,
    EmptyStateBody,
    SearchInput,
    ToggleGroup,
    ToggleGroupItem,
} from "@patternfly/react-core";
import { Table, Thead, Tr, Th, Tbody, Td, TreeRowWrapper, TdProps } from "@patternfly/react-table";

import cockpit from 'cockpit';

import { DiagnosticsEntry } from "../interfaces";
import { FilterLevel, filterTree } from "../utils/treeFilter";
import { SeverityIcon } from "./SeverityIcon";

const _ = cockpit.gettext;

// Renders an expandable TreeTable of diagnostic messages
export const DiagnosticsTreeTable = ({
    diagnostics,
    selectedRawName,
    setSelectedRawName,
    query,
    filterLevel,
    onQueryChange,
    onFilterLevelChange,
}: {
    diagnostics: DiagnosticsEntry[],
    selectedRawName: string | null,
    setSelectedRawName: (rawName: string | null) => void,
    query: string,
    filterLevel: FilterLevel,
    onQueryChange: (query: string) => void,
    onFilterLevelChange: (level: FilterLevel) => void,
}) => {
    const [expandedRows, setExpandedRows] = useState<string[]>([]);
    const [lastExpandedRawName, setLastExpandedRawName] = useState<string | null>(null); // Track last expanded

    const { visible, expand, matches } = filterTree(diagnostics, query, filterLevel);

    // Helper to toggle expansion for a given diagnostic rawName
    const toggleRowExpansion = (diagRawName: string) => {
        setExpandedRows(prevExpanded =>
            prevExpanded.includes(diagRawName)
                ? prevExpanded.filter(name => name !== diagRawName)
                : [...prevExpanded, diagRawName]
        );
    };

    const renderRows = (
        [diag, ...remainingDiag]: DiagnosticsEntry[],
        indentLevel = 1,
        posinset = 1,
        rowIndex = 0,
        isHidden = false
    ): React.ReactNode[] => {
        if (!diag) return [];

        if (!visible.has(diag.rawName)) {
            return renderRows(remainingDiag, indentLevel, posinset, rowIndex, isHidden);
        }

        const isExpanded = expandedRows.includes(diag.rawName) || expand.has(diag.rawName);

        const treeRow: TdProps["treeRow"] = {
            onCollapse: (event) => {
                event.stopPropagation(); // Prevent triggering onClick when expanding/collapsing
                toggleRowExpansion(diag.rawName);
            },
            props: {
                isExpanded,
                isHidden,
                "aria-level": indentLevel,
                "aria-posinset": posinset,
                "aria-setsize": diag.children.length,
            },
        };

        const childRows = diag.children.length
            ? renderRows(diag.children, indentLevel + 1, 1, rowIndex + 1, !isExpanded || isHidden)
            : [];

        return [
            <TreeRowWrapper
                key={diag.rawName}
                row={{ props: treeRow.props }}
                isSelectable
                isRowSelected={selectedRawName === diag.rawName}
                isClickable
                onClick={() => {
                    setSelectedRawName(diag.rawName);
                    toggleRowExpansion(diag.rawName);
                }}
            >
                <Td dataLabel={_("Level")} className="tree-level" modifier="fitContent">
                    <SeverityIcon level={diag.severity_level} hideOk />
                </Td>
                <Td dataLabel={_("Name")} treeRow={treeRow}>
                    <span className="diagnostics-table-name">{diag.name}</span>
                    <br />
                    {diag.path}
                </Td>
                <Td dataLabel={_("Message")}>{diag.message}</Td>
            </TreeRowWrapper>,
            ...childRows,
            ...renderRows(remainingDiag, indentLevel, posinset + 1, rowIndex + 1 + childRows.length, isHidden),
        ];
    };

    // Helper to find the path (array of rawNames) from root to a given rawName
    const findPathToRawName = useCallback((entries: DiagnosticsEntry[], rawName: string, path: string[] = []): string[] | null => {
        for (const entry of entries) {
            const newPath = [...path, entry.rawName];
            if (entry.rawName === rawName) {
                return newPath;
            }
            const childPath = findPathToRawName(entry.children, rawName, newPath);
            if (childPath) {
                return childPath;
            }
        }
        return null;
    }, []);

    useEffect(() => {
        if (
            selectedRawName &&
            selectedRawName !== lastExpandedRawName // Only expand if changed
        ) {
            const path = findPathToRawName(diagnostics, selectedRawName);
            if (path && path.length > 1) {
                // Expand all ancestors (exclude the last, which is the selected node itself)
                setExpandedRows(prevExpanded => {
                    const ancestors = path.slice(0, -1);
                    // Only add ancestors not already expanded
                    return Array.from(new Set([...prevExpanded, ...ancestors]));
                });
            }
            setLastExpandedRawName(selectedRawName);
        }
    }, [selectedRawName, diagnostics, findPathToRawName, lastExpandedRawName]);

    return (
        <Card>
            <CardTitle component="h2" className="diagnostics-title">{_("All Diagnostics")}</CardTitle>
            <CardBody>
                <div className="tree-controls">
                    <SearchInput
                        value={query}
                        onChange={(_event, value) => onQueryChange(value)}
                        onClear={() => onQueryChange("")}
                        placeholder={_("Search name, path or message")}
                        aria-label={_("Search diagnostics")}
                    />
                    <ToggleGroup aria-label={_("Severity filter")}>
                        <ToggleGroupItem
                            text={_("All")}
                            isSelected={filterLevel === "all"}
                            onChange={() => onFilterLevelChange("all")}
                        />
                        <ToggleGroupItem
                            text={_("≥ Warning")}
                            isSelected={filterLevel === "warn"}
                            onChange={() => onFilterLevelChange("warn")}
                        />
                        <ToggleGroupItem
                            text={_("≥ Error")}
                            isSelected={filterLevel === "error"}
                            onChange={() => onFilterLevelChange("error")}
                        />
                    </ToggleGroup>
                </div>
                <Table isTreeTable variant="compact" aria-label={_("Diagnostics Tree Table")} borders={false}>
                    {diagnostics.length > 0 && (
                        <Thead>
                            <Tr>
                                <Th screenReaderText={_("Level")} className="tree-level" modifier="fitContent" />
                                <Th>{_("Name")}</Th>
                                <Th>{_("Message")}</Th>
                            </Tr>
                        </Thead>
                    )}
                    <Tbody>
                        {diagnostics.length > 0 && matches === 0 && (
                            <Tr>
                                <Td colSpan={3}>
                                    <Bullseye>
                                        <EmptyState headingLevel="h2" titleText={_("Nothing matches")} variant={EmptyStateVariant.xs}>
                                            <EmptyStateBody>
                                                <Button
                                                    variant="link"
                                                    isInline
                                                    onClick={() => {
                                                        onQueryChange("");
                                                        onFilterLevelChange("all");
                                                    }}
                                                >
                                                    {_("Reset filters")}
                                                </Button>
                                            </EmptyStateBody>
                                        </EmptyState>
                                    </Bullseye>
                                </Td>
                            </Tr>
                        )}
                        {(diagnostics.length === 0 || matches > 0) && renderRows(diagnostics)}
                    </Tbody>
                </Table>
            </CardBody>
        </Card>
    );
};
