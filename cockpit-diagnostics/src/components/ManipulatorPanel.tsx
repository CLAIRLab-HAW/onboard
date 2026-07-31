/*
 * This file is part of Cockpit ROS 2 Diagnostics.
 *
 * Copyright (C) 2025 Clearpath Robotics, Inc., a Rockwell Automation Company. All rights reserved.
 * Copyright (C) 2026 CLAIRLab, HAW Hamburg -- manipulator extension.
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
    Alert,
    Button,
    Card,
    CardBody,
    CardTitle,
    DescriptionList,
    DescriptionListDescription,
    DescriptionListGroup,
    DescriptionListTerm,
    Flex,
    FlexItem,
    Grid,
    GridItem,
    Label,
    Progress,
    ProgressMeasureLocation,
} from "@patternfly/react-core";
import { Table, Thead, Tr, Th, Tbody, Td } from "@patternfly/react-table";

import cockpit from 'cockpit';

import { DiagnosticsEntry } from "../interfaces";
import {
    boolOf,
    collectManipulator,
    controllerRows,
    gripperPercent,
    jointRows,
    numberOf,
    valueOf,
    worstLevel,
} from "../utils/manipulatorUtils";
import {
    LEVEL_ERROR,
    LEVEL_INACTIVE,
    LEVEL_OK,
    LEVEL_STALE,
    LEVEL_WARN,
} from "../utils/severity";
import { SeverityIcon, severityLabel } from "./SeverityIcon";

const _ = cockpit.gettext;

/*
 * Dedicated view for the arm and the end effector.
 *
 * The generic tree below already contains these statuses, but reading a joint
 * pose or a gripper opening out of a collapsed tree of key/value pairs is
 * tedious in exactly the moments where it matters (arm in a protective stop,
 * gripper stuck closed). This panel renders the same data in the shape an
 * operator actually looks for, and stays silent on robots without a
 * manipulator: no manipulator statuses in the tree -> nothing is rendered.
 */

// The stripe is the card's only state carrier; OK is deliberately grey, because
// "fine" is not something anybody scans for.
const cardVariant = (level: number): string => {
    if (level >= LEVEL_STALE) return "stale";
    if (level >= LEVEL_ERROR) return "error";
    if (level >= LEVEL_WARN) return "warn";
    return "quiet";
};

const boolText = (value: boolean | null, yes: string, no: string): string => {
    if (value === null) return _("unknown");
    return value ? yes : no;
};

const Term = ({ label, children }: { label: string, children: React.ReactNode }) => (
    <DescriptionListGroup>
        <DescriptionListTerm>{label}</DescriptionListTerm>
        <DescriptionListDescription>{children}</DescriptionListDescription>
    </DescriptionListGroup>
);

/*
 * One line per status that is not plain OK, carrying the publisher's own
 * message (which already says what to do -- "arm switched off", "tool voltage
 * off", ...). Clicking it selects the status in the tree table below, which
 * opens the detail drawer with the full key/value list.
 *
 * Out-of-service statuses get a muted line instead of an alert: they are the
 * *explanation* for the grey card, not something to act on.
 */
const StatusAlerts = ({
    entries,
    setSelectedRawName,
}: {
    entries: (DiagnosticsEntry | null)[],
    setSelectedRawName: (rawName: string | null) => void,
}) => (
    <>
        {entries
                .filter((entry): entry is DiagnosticsEntry =>
                    entry !== null &&
                    (entry.severity_level > LEVEL_OK || entry.severity_level === LEVEL_INACTIVE))
                .map(entry => (entry.severity_level === LEVEL_INACTIVE
                    ? (
                        <div key={entry.rawName} className="manipulator-note">
                            {entry.message || _("No message")}{" "}
                            <Button variant="link" isInline onClick={() => setSelectedRawName(entry.rawName)}>
                                {_("Show details")}
                            </Button>
                        </div>
                    )
                    : (
                        <Alert
                            key={entry.rawName}
                            isInline
                            isPlain
                            variant={entry.severity_level === LEVEL_WARN
                                ? "warning"
                                : entry.severity_level === LEVEL_STALE ? "info" : "danger"}
                            title={entry.message || _("No message")}
                            className="manipulator-alert"
                        >
                            <Button variant="link" isInline onClick={() => setSelectedRawName(entry.rawName)}>
                                {_("Show details")}
                            </Button>
                        </Alert>
                    )))}
    </>
);

const ArmCard = ({
    armMode,
    armControl,
    armJoints,
    armControllers,
    setSelectedRawName,
}: {
    armMode: DiagnosticsEntry | null,
    armControl: DiagnosticsEntry | null,
    armJoints: DiagnosticsEntry | null,
    armControllers: DiagnosticsEntry | null,
    setSelectedRawName: (rawName: string | null) => void,
}) => {
    const robotMode = valueOf(armMode, "robot_mode");
    const safetyMode = valueOf(armMode, "safety_mode");
    const externalControl = valueOf(armControl, "external_control");
    const motionLive = valueOf(armControl, "motion_interface") === "live";
    const rate = valueOf(armControl, "joint_state_rate_hz");
    const joints = jointRows(armJoints);
    const controllers = controllerRows(armControllers);
    const activeControllers = controllers.filter(c => c.state === "active").length;
    const level = worstLevel([armMode, armControl, armJoints, armControllers]);
    // Out of service: the readings are last-known values, not live state. Dim
    // them so nobody reads a joint angle off a powered-down arm as current.
    const isInactive = level === LEVEL_INACTIVE;

    return (
        <div className={`state-card state-card-${cardVariant(level)}`}>
            <h3 className="state-card-title">
                {_("Arm")}
                <span className="card-state">
                    <SeverityIcon level={level} /> {severityLabel(level)}
                </span>
            </h3>
            <div className="manipulator-subtitle">{valueOf(armMode, "robot_ip")
                ? cockpit.format(_("UR5 at $0"), valueOf(armMode, "robot_ip"))
                : _("UR5")}
            </div>
            <div {...(isInactive ? { className: "manipulator-out-of-service" } : {})}>
                <StatusAlerts
                    entries={[armMode, armControl, armJoints, armControllers]}
                    setSelectedRawName={setSelectedRawName}
                />
                <DescriptionList isHorizontal isCompact>
                    <Term label={_("Robot mode")}>{robotMode ?? _("unknown")}</Term>
                    <Term label={_("Safety mode")}>{safetyMode ?? _("unknown")}</Term>
                    <Term label={_("External control")}>{externalControl ?? _("unknown")}</Term>
                    {/*
                      * The joint_state stream is the honest liveness signal: it only
                      * flows while the ros2_control hardware interface is active.
                      * External control can read "running" over a dead motion link.
                      */}
                    <Term label={_("Motion link")}>
                        {motionLive ? _("live") : _("dead")}
                        {rate && motionLive ? <span className="manipulator-hint">{cockpit.format(_("$0 Hz"), rate)}</span> : null}
                    </Term>
                    <Term label={_("Controllers")}>
                        {controllers.length > 0
                            ? cockpit.format(_("$0 of $1 active"), activeControllers, controllers.length)
                            : _("unknown")}
                    </Term>
                </DescriptionList>

                {joints.length > 0 && (
                    <Table
                        aria-label={_("Arm Joints Table")}
                        borders={false}
                        variant="compact"
                        className="manipulator-joints"
                    >
                        <Thead>
                            <Tr>
                                <Th>{_("Joint")}</Th>
                                <Th modifier="fitContent">{_("Position")}</Th>
                                <Th modifier="fitContent">{_("Velocity")}</Th>
                                {joints.some(joint => joint.effort !== null) && <Th modifier="fitContent">{_("Effort")}</Th>}
                            </Tr>
                        </Thead>
                        <Tbody>
                            {joints.map(joint => (
                                <Tr key={joint.name}>
                                    <Td dataLabel={_("Joint")}>{joint.name}</Td>
                                    <Td dataLabel={_("Position")} modifier="nowrap">
                                        {joint.deg}&nbsp;° <span className="manipulator-hint">({joint.rad}&nbsp;rad)</span>
                                    </Td>
                                    <Td dataLabel={_("Velocity")} modifier="nowrap">{joint.velocity}&nbsp;rad/s</Td>
                                    {joints.some(j => j.effort !== null) && (
                                        <Td dataLabel={_("Effort")} modifier="nowrap">{joint.effort ?? "-"}</Td>
                                    )}
                                </Tr>
                            ))}
                        </Tbody>
                    </Table>
                )}

                {controllers.length > 0 && (
                    <Flex className="manipulator-controllers" spaceItems={{ default: 'spaceItemsXs' }} flexWrap={{ default: 'wrap' }}>
                        {controllers.map(controller => (
                            <FlexItem key={controller.name}>
                                <Label isCompact color={controller.state === "active" ? "green" : "grey"}>
                                    {controller.name}
                                </Label>
                            </FlexItem>
                        ))}
                    </Flex>
                )}
            </div>
        </div>
    );
};

const GripperCard = ({
    gripper,
    setSelectedRawName,
}: {
    gripper: DiagnosticsEntry | null,
    setSelectedRawName: (rawName: string | null) => void,
}) => {
    const percent = gripperPercent(gripper);
    const widthMm = valueOf(gripper, "width_mm");
    const strokeMm = valueOf(gripper, "stroke_mm");
    const gripDetected = boolOf(gripper, "grip_detected");
    const busy = boolOf(gripper, "busy");
    /*
     * Tool voltage is the *commanded* setpoint of the driver, never hardware
     * feedback -- it stays true after the arm is powered down. `signal_valid`
     * is what says whether the tool actually answers, so the two are shown
     * together: "commanded, no signal" is the honest reading when the analog
     * signal does not confirm it.
     * (`tool_power_on` is the pre-2026-07 key name, kept so an older publisher
     * still renders instead of reading "unknown".)
     */
    const toolPower = boolOf(gripper, "tool_power_commanded") ?? boolOf(gripper, "tool_power_on");
    const signalValid = boolOf(gripper, "signal_valid");
    const highForce = boolOf(gripper, "high_force_preset");
    const forceRaw = numberOf(gripper, "force_raw_v");
    const level = worstLevel([gripper]);
    const isInactive = level === LEVEL_INACTIVE;

    return (
        <div className={`state-card state-card-${cardVariant(level)}`}>
            <h3 className="state-card-title">
                {_("End effector")}
                <span className="card-state">
                    <SeverityIcon level={level} /> {severityLabel(level)}
                </span>
            </h3>
            <div className="manipulator-subtitle">{_("OnRobot RG6")}</div>
            <div {...(isInactive ? { className: "manipulator-out-of-service" } : {})}>
                <StatusAlerts entries={[gripper]} setSelectedRawName={setSelectedRawName} />
                {percent !== null && (
                    <Progress
                        value={percent}
                        title={_("Opening")}
                        label={widthMm && strokeMm
                            ? cockpit.format(_("$0 of $1 mm"), widthMm, strokeMm)
                            : `${percent.toFixed(0)} %`}
                        measureLocation={ProgressMeasureLocation.top}
                        aria-label={_("Gripper opening")}
                        className="manipulator-opening"
                    />
                )}
                <DescriptionList isHorizontal isCompact>
                    <Term label={_("Grip detected")}>
                        {boolText(gripDetected, _("object held"), _("no object"))}
                    </Term>
                    <Term label={_("Motion")}>
                        {boolText(busy, _("moving"), _("settled"))}
                    </Term>
                    {/*
                      * Without tool voltage the RG6 reports neither analog nor digital
                      * values. After an arm restart that is briefly normal -- rg6_control
                      * raises the voltage itself on the program-running edge.
                      */}
                    <Term label={_("Tool power")}>
                        {boolText(toolPower, _("on"), _("off"))}
                        {signalValid === false && toolPower === true && (
                            <span className="manipulator-hint">{_("commanded, no signal")}</span>
                        )}
                    </Term>
                    <Term label={_("Force preset")}>
                        {boolText(highForce, _("high"), _("normal"))}
                    </Term>
                    <Term label={_("Last command")}>
                        {valueOf(gripper, "last_command") ?? _("unknown")}
                    </Term>
                    <Term label={_("Force signal")}>
                        {forceRaw === null ? _("unknown") : `${forceRaw.toFixed(2)} V`}
                    </Term>
                </DescriptionList>
            </div>
        </div>
    );
};

export const ManipulatorPanel = ({
    diagnostics,
    setSelectedRawName,
}: {
    diagnostics: DiagnosticsEntry[],
    setSelectedRawName: (rawName: string | null) => void,
}) => {
    const manipulator = collectManipulator(diagnostics);

    // No manipulator diagnostics at all -> this robot has no arm (or the
    // publisher was never installed). Render nothing rather than an empty card.
    if (!manipulator) {
        return null;
    }

    return (
        <Card>
            <CardTitle component="h2" className="diagnostics-title">
                <Flex justifyContent={{ default: 'justifyContentSpaceBetween' }} alignItems={{ default: 'alignItemsCenter' }}>
                    <FlexItem>{_("Manipulator")}</FlexItem>
                    <FlexItem>
                        <span className="card-state">
                            <SeverityIcon level={manipulator.level} /> {severityLabel(manipulator.level)}
                        </span>
                    </FlexItem>
                </Flex>
            </CardTitle>
            <CardBody>
                <Grid hasGutter>
                    <GridItem md={7}>
                        <ArmCard
                            armMode={manipulator.armMode}
                            armControl={manipulator.armControl}
                            armJoints={manipulator.armJoints}
                            armControllers={manipulator.armControllers}
                            setSelectedRawName={setSelectedRawName}
                        />
                    </GridItem>
                    <GridItem md={5}>
                        <GripperCard
                            gripper={manipulator.gripper}
                            setSelectedRawName={setSelectedRawName}
                        />
                    </GridItem>
                </Grid>
            </CardBody>
        </Card>
    );
};
