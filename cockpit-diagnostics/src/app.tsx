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

import React, { useState } from 'react';

import {
    Alert,
    Drawer,
    DrawerContent,
    DrawerContentBody,
    DrawerPanelContent,
    DropdownItem,
    Page,
    PageSection,
    Stack,
} from "@patternfly/react-core";

import cockpit from 'cockpit';

import { DiagnosticsStatus } from "./interfaces";
import { DetailPanel, findEntryByRawName } from "./components/DetailPanel";
import { DiagnosticsTreeTable } from "./components/DiagnosticsTreeTable";
import { CaptureAlerts, useCapture } from "./components/DiagnosticsCapture";
import { IssueList } from "./components/IssueList";
import { RosConnectionManager } from "./components/RosConnectionManager";
import { StatusBand } from "./components/StatusBand";
import { useNamespace } from "./hooks/useNamespace";
import { useWebSocketUrl } from "./hooks/useWebSocketUrl";
import { ManipulatorPanel } from "./components/ManipulatorPanel";
import { ManualNamespace } from "./components/ManualNamespace";
import { Timeline } from "./components/Timeline";
import { useDiagHistory } from './hooks/useDiagHistory';
import { FilterLevel } from "./utils/treeFilter";
import { updateRateHz } from "./utils/summary";

const _ = cockpit.gettext;

export const Application = () => {
    const {
        namespace,
        setManualNamespace,
        invalidNamespaceMessage,
        manualEntryRequired
    } = useNamespace();
    const url = useWebSocketUrl(); // Use custom hook for WebSocket URL
    const [diagStatusDisplay, setDiagStatusDisplay] = useState<DiagnosticsStatus | null>(null); // DiagStatus data for display
    const [bridgeConnected, setBridgeConnected] = useState(false);
    const [selectedRawName, setSelectedRawName] = useState<string | null>(null); // Used as identifier for diag entry so that values get updated
    const [isPaused, setIsPaused] = useState(false); // Pause state for diagnostics updates
    const [query, setQuery] = useState("");
    const [filterLevel, setFilterLevel] = useState<FilterLevel>("all");

    const {
        diagHistory,
        updateDiagHistory,
        clearDiagHistory
    } = useDiagHistory(isPaused);
    const capture = useCapture(namespace);

    // Extract diagnostics array from DiagnosticsStatus for components that need it
    const diagnostics = diagStatusDisplay?.diagnostics || [];
    // Resolved here, not inside the tree: the issue list and the manipulator
    // panel select a status too, and the panel now lives above all three.
    const selectedEntry = selectedRawName ? findEntryByRawName(diagnostics, selectedRawName) : null;

    return (
        <Page id="ros2-diag" className='no-masthead-sidebar'>
            <PageSection>
                <Stack hasGutter>
                    <StatusBand
                        namespace={namespace}
                        diagnostics={diagnostics}
                        timestamp={diagStatusDisplay?.timestamp ?? null}
                        bridgeConnected={bridgeConnected}
                        rateHz={updateRateHz(diagHistory)}
                        isPaused={isPaused}
                        onTogglePause={() => {
                            if (isPaused) clearDiagHistory();
                            setIsPaused(!isPaused);
                        }}
                        onFilterLevel={setFilterLevel}
                        menuItems={
                            <DropdownItem
                                key="capture"
                                isDisabled={!capture.adminAccess || capture.isCapturing}
                                {...(!capture.adminAccess
                                    ? { description: _("Enable admin access at the top of the page to enable diagnostics capture feature.") }
                                    : {})}
                                onClick={() => { capture.capture() }}
                            >
                                {capture.isCapturing ? _("Generating…") : _("Generate diagnostics capture")}
                            </DropdownItem>
                        }
                    >
                        <Timeline
                            diagHistory={diagHistory}
                            setDiagStatusDisplay={setDiagStatusDisplay}
                            isPaused={isPaused}
                            setIsPaused={setIsPaused}
                        />
                    </StatusBand>
                    <CaptureAlerts state={capture} />
                    {invalidNamespaceMessage && (
                        <Alert
                            variant="danger"
                            title={invalidNamespaceMessage} // Display error message if namespace is invalid
                        />
                    )}
                    { manualEntryRequired && (
                        <ManualNamespace
                            setManualNamespace={setManualNamespace}
                            namespace={namespace}
                        />
                    )}
                    { !invalidNamespaceMessage && (
                        <>
                            <RosConnectionManager
                                namespace={namespace}
                                url={url}
                                onDiagnosticsUpdate={updateDiagHistory}
                                onConnectionStatusChange={setBridgeConnected}
                                onClearHistory={clearDiagHistory}
                            />
                            {/*
                              * The detail panel lives at page level, not inside the tree card: the
                              * issue list, the manipulator panel and the tree all select through the
                              * same setSelectedRawName, and isInline is deliberately not set so the
                              * panel slides over the workspace instead of splitting its width.
                              */}
                            <Drawer isExpanded={!!selectedEntry}>
                                <DrawerContent
                                    panelContent={
                                        <DrawerPanelContent isResizable defaultSize="28rem" minSize="20rem">
                                            <DetailPanel entry={selectedEntry} onClose={() => setSelectedRawName(null)} />
                                        </DrawerPanelContent>
                                    }
                                >
                                    <DrawerContentBody>
                                        <Stack hasGutter>
                                            {diagnostics.length > 0 && (
                                                <>
                                                    <IssueList diagnostics={diagnostics} setSelectedRawName={setSelectedRawName} />
                                                    {/* Renders itself only on robots that publish manipulator diagnostics. */}
                                                    <ManipulatorPanel diagnostics={diagnostics} setSelectedRawName={setSelectedRawName} />
                                                </>
                                            )}
                                            <DiagnosticsTreeTable
                                                diagnostics={diagnostics}
                                                bridgeConnected={bridgeConnected}
                                                selectedRawName={selectedRawName}
                                                setSelectedRawName={setSelectedRawName}
                                                query={query}
                                                filterLevel={filterLevel}
                                                onQueryChange={setQuery}
                                                onFilterLevelChange={setFilterLevel}
                                            />
                                        </Stack>
                                    </DrawerContentBody>
                                </DrawerContent>
                            </Drawer>
                        </>
                    )}
                </Stack>
            </PageSection>
        </Page>
    );
};
