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

import React, { useCallback, useState } from 'react';

import {
    Alert,
    Bullseye,
    Card,
    CardBody,
    CardTitle,
    Drawer,
    DrawerContent,
    DrawerContentBody,
    DrawerPanelContent,
    DropdownItem,
    EmptyState,
    EmptyStateBody,
    EmptyStateVariant,
    Page,
    PageSection,
    Spinner,
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

/*
 * With no diagnostics at all there is nothing to show in either workspace
 * column, so this now guards the whole workspace rather than just the tree
 * (which used to own it, back when it was the only thing on the page).
 */
const ConnectingState = ({ bridgeConnected }: { bridgeConnected: boolean }) => (
    <Bullseye>
        <EmptyState headingLevel="h2" titleText={_("Connecting")} icon={Spinner} variant={EmptyStateVariant.sm}>
            <EmptyStateBody>
                {bridgeConnected
                    ? _("Waiting for diagnostics messages...")
                    : _("Attempting to connect to the Foxglove bridge...")}
            </EmptyStateBody>
        </EmptyState>
    </Bullseye>
);

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
    // Held so the end effector's control can call a service over the same
    // connection the diagnostics arrive on. null whenever the link is down.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const [ros, setRos] = useState<any | null>(null);
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
    // Stable identity: an inline closure here would re-create itself on every
    // render of Application (roughly 1 Hz, driven by diagnostics updates),
    // which re-hangs DetailPanel's document-level Escape listener just as
    // often for no reason.
    const closeDetailPanel = useCallback(() => setSelectedRawName(null), []);

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
                    {invalidNamespaceMessage && (
                        <Alert
                            variant="danger"
                            isInline
                            title={invalidNamespaceMessage} // Display error message if namespace is invalid
                        />
                    )}
                    { manualEntryRequired && (
                        <ManualNamespace
                            setManualNamespace={setManualNamespace}
                            namespace={namespace}
                        />
                    )}
                    <CaptureAlerts state={capture} />
                    { !invalidNamespaceMessage && (
                        <>
                            <RosConnectionManager
                                onRosChange={setRos}
                                namespace={namespace}
                                url={url}
                                onDiagnosticsUpdate={updateDiagHistory}
                                onConnectionStatusChange={setBridgeConnected}
                                onClearHistory={clearDiagHistory}
                            />
                            {/*
                              * The detail panel lives at page level, not inside the tree card: the
                              * issue list, the manipulator panel and the tree all select through the
                              * same setSelectedRawName.
                              *
                              * `isInline` is required, not cosmetic. Without it PatternFly gives the
                              * drawer content `flex: 0 0 100%` -- it cannot shrink -- while the panel
                              * still takes its 336px in the same flex row. The row overflows, and
                              * since the row clips, the content is pushed that far off the left edge:
                              * measured at -300px, with the leftmost readings simply unreachable.
                              * `isInline` makes it `0 1 100%`, so the panel takes its space from the
                              * content instead of shoving it out of view.
                              */}
                            <Drawer isExpanded={!!selectedEntry} isInline>
                                <DrawerContent
                                    panelContent={
                                        <DrawerPanelContent isResizable defaultSize="28rem" minSize="20rem">
                                            <DetailPanel entry={selectedEntry} onClose={closeDetailPanel} />
                                        </DrawerPanelContent>
                                    }
                                >
                                    <DrawerContentBody>
                                        {diagnostics.length === 0
                                            ? <ConnectingState bridgeConnected={bridgeConnected} />
                                            : (
                                                <div className="workspace">
                                                    <div className="workspace-primary">
                                                        {/* Renders itself only on robots that publish manipulator diagnostics. */}
                                                        <ManipulatorPanel
                                                            diagnostics={diagnostics}
                                                            setSelectedRawName={setSelectedRawName}
                                                            ros={ros}
                                                            namespace={namespace}
                                                        />
                                                    </div>
                                                    <div className="workspace-secondary">
                                                        {/*
                                                          * Issues sit above the tree in the same column: they are
                                                          * the shortlist of what the tree below holds, and reading
                                                          * one straight into the other beats crossing the page.
                                                          */}
                                                        <Card>
                                                            <CardTitle component="h2" className="diagnostics-title">
                                                                {_("Issues")}
                                                            </CardTitle>
                                                            <CardBody>
                                                                <IssueList diagnostics={diagnostics} setSelectedRawName={setSelectedRawName} />
                                                            </CardBody>
                                                        </Card>
                                                        <DiagnosticsTreeTable
                                                            diagnostics={diagnostics}
                                                            selectedRawName={selectedRawName}
                                                            setSelectedRawName={setSelectedRawName}
                                                            query={query}
                                                            filterLevel={filterLevel}
                                                            onQueryChange={setQuery}
                                                            onFilterLevelChange={setFilterLevel}
                                                        />
                                                    </div>
                                                </div>
                                            )}
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
