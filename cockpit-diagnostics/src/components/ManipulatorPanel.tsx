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
    LabelProps,
    Progress,
    ProgressMeasureLocation,
    ProgressVariant,
} from "@patternfly/react-core";
import {
    CheckCircleIcon,
    ExclamationCircleIcon,
    ExclamationTriangleIcon,
    QuestionCircleIcon,
} from "@patternfly/react-icons";
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

// `LabelProps["color"]` is optional, and the project builds with
// exactOptionalPropertyTypes -- so an explicit `undefined` would not be a valid
// value for the prop. Strip it: every helper here always names a colour.
type LabelColor = NonNullable<LabelProps["color"]>;

interface SeverityStyle {
    color: LabelColor;
    text: string;
    icon: React.ReactElement;
}

const severityStyle = (level: number): SeverityStyle => {
    switch (level) {
    case 0:
        return { color: "green", text: _("OK"), icon: <CheckCircleIcon /> };
    case 1:
        return { color: "orange", text: _("Warning"), icon: <ExclamationTriangleIcon /> };
    case 2:
        return { color: "red", text: _("Error"), icon: <ExclamationCircleIcon /> };
    case 3:
        return { color: "blue", text: _("Stale"), icon: <QuestionCircleIcon /> };
    default:
        return { color: "grey", text: _("No data"), icon: <QuestionCircleIcon /> };
    }
};

const SeverityLabel = ({ level }: { level: number }) => {
    const style = severityStyle(level);
    return <Label isCompact color={style.color} icon={style.icon}>{style.text}</Label>;
};

// UR robot mode: only RUNNING means "ready to move".
const modeColor = (mode: string | null): LabelColor => {
    if (mode === null || mode === "UNKNOWN") return "grey";
    return mode === "RUNNING" ? "green" : "orange";
};

// UR safety mode: anything past REDUCED/RECOVERY needs an intervention.
const safetyColor = (safety: string | null): LabelColor => {
    if (safety === null || safety === "UNKNOWN") return "grey";
    if (safety === "NORMAL") return "green";
    if (safety === "REDUCED" || safety === "RECOVERY") return "orange";
    return "red";
};

const boolColor = (value: boolean | null, goodValue: boolean): LabelColor => {
    if (value === null) return "grey";
    return value === goodValue ? "green" : "orange";
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
 * One inline alert per status that is not OK, carrying the publisher's own
 * message (which already says what to do -- "arm powered late", "tool voltage
 * off", ...). Clicking it selects the status in the tree table below, which
 * opens the detail drawer with the full key/value list.
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
                .filter((entry): entry is DiagnosticsEntry => entry !== null && entry.severity_level > 0)
                .map(entry => (
                    <Alert
                        key={entry.rawName}
                        isInline
                        isPlain
                        variant={entry.severity_level === 1 ? "warning" : entry.severity_level === 3 ? "info" : "danger"}
                        title={entry.message || _("No message")}
                        className="manipulator-alert"
                    >
                        <Button variant="link" isInline onClick={() => setSelectedRawName(entry.rawName)}>
                            {_("Show details")}
                        </Button>
                    </Alert>
                ))}
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

    return (
        <Card isPlain isCompact>
            <CardTitle component="h3">
                <Flex justifyContent={{ default: 'justifyContentSpaceBetween' }} alignItems={{ default: 'alignItemsCenter' }}>
                    <FlexItem>{_("Arm")}</FlexItem>
                    <FlexItem>
                        <SeverityLabel level={worstLevel([armMode, armControl, armJoints, armControllers])} />
                    </FlexItem>
                </Flex>
                <div className="manipulator-subtitle">{valueOf(armMode, "robot_ip")
                    ? cockpit.format(_("UR5 at $0"), valueOf(armMode, "robot_ip"))
                    : _("UR5")}
                </div>
            </CardTitle>
            <CardBody>
                <StatusAlerts
                    entries={[armMode, armControl, armJoints, armControllers]}
                    setSelectedRawName={setSelectedRawName}
                />
                <DescriptionList isHorizontal isCompact>
                    <Term label={_("Robot mode")}>
                        <Label isCompact color={modeColor(robotMode)}>{robotMode ?? _("unknown")}</Label>
                    </Term>
                    <Term label={_("Safety mode")}>
                        <Label isCompact color={safetyColor(safetyMode)}>{safetyMode ?? _("unknown")}</Label>
                    </Term>
                    <Term label={_("External control")}>
                        <Label isCompact color={externalControl === "running" ? "green" : externalControl ? "orange" : "grey"}>
                            {externalControl ?? _("unknown")}
                        </Label>
                    </Term>
                    {/*
                      * The joint_state stream is the honest liveness signal: it only
                      * flows while the ros2_control hardware interface is active.
                      * External control can read "running" over a dead motion link.
                      */}
                    <Term label={_("Motion link")}>
                        <Label isCompact color={motionLive ? "green" : "red"}>
                            {motionLive ? _("live") : _("dead")}
                        </Label>
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
            </CardBody>
        </Card>
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
    const toolPower = boolOf(gripper, "tool_power_on");
    const highForce = boolOf(gripper, "high_force_preset");
    const forceRaw = numberOf(gripper, "force_raw_v");

    return (
        <Card isPlain isCompact>
            <CardTitle component="h3">
                <Flex justifyContent={{ default: 'justifyContentSpaceBetween' }} alignItems={{ default: 'alignItemsCenter' }}>
                    <FlexItem>{_("End effector")}</FlexItem>
                    <FlexItem><SeverityLabel level={worstLevel([gripper])} /></FlexItem>
                </Flex>
                <div className="manipulator-subtitle">{_("OnRobot RG6")}</div>
            </CardTitle>
            <CardBody>
                <StatusAlerts entries={[gripper]} setSelectedRawName={setSelectedRawName} />
                {percent !== null && (
                    <Progress
                        value={percent}
                        title={_("Opening")}
                        label={widthMm && strokeMm
                            ? cockpit.format(_("$0 of $1 mm"), widthMm, strokeMm)
                            : `${percent.toFixed(0)} %`}
                        measureLocation={ProgressMeasureLocation.top}
                        // No variant = the neutral blue bar; green only once an object is actually held.
                        {...(gripDetected ? { variant: ProgressVariant.success } : {})}
                        aria-label={_("Gripper opening")}
                        className="manipulator-opening"
                    />
                )}
                <DescriptionList isHorizontal isCompact>
                    <Term label={_("Grip detected")}>
                        <Label isCompact color={gripDetected === null ? "grey" : gripDetected ? "green" : "grey"}>
                            {boolText(gripDetected, _("object held"), _("no object"))}
                        </Label>
                    </Term>
                    <Term label={_("Motion")}>
                        <Label isCompact color={busy === null ? "grey" : busy ? "blue" : "green"}>
                            {boolText(busy, _("moving"), _("settled"))}
                        </Label>
                    </Term>
                    {/*
                      * Without tool voltage the RG6 reports neither analog nor digital
                      * values. After an arm restart that is briefly normal -- rg6_control
                      * raises the voltage itself on the program-running edge.
                      */}
                    <Term label={_("Tool power")}>
                        <Label isCompact color={boolColor(toolPower, true)}>
                            {boolText(toolPower, _("on"), _("off"))}
                        </Label>
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
            </CardBody>
        </Card>
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
                    <FlexItem><SeverityLabel level={manipulator.level} /></FlexItem>
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
