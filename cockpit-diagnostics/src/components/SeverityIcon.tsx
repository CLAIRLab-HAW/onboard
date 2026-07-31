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
import { Icon } from "@patternfly/react-core";
import {
    CheckCircleIcon,
    ClockIcon,
    ExclamationCircleIcon,
    ExclamationTriangleIcon,
    PowerOffIcon,
} from "@patternfly/react-icons";

import cockpit from 'cockpit';

import {
    LEVEL_ERROR,
    LEVEL_INACTIVE,
    LEVEL_OK,
    LEVEL_STALE,
    LEVEL_WARN,
} from "../utils/severity";

const _ = cockpit.gettext;

/*
 * One place that decides how a severity looks.
 *
 * Five states get five distinguishable *shapes*, not just five colours, so the
 * page stays readable in greyscale and with red-green colour blindness. The
 * clock and the power symbol replace upstream's question mark and empty circle:
 * those named the uncertainty, not the state -- a stale status means "no fresh
 * message", and an inactive one means "deliberately switched off".
 *
 * Colours come from PatternFly's `<Icon status>`, never from our own SCSS, so
 * Cockpit's dark mode needs no extra work.
 */
export const severityLabel = (level: number): string => {
    switch (level) {
    case LEVEL_ERROR:
        return _("Error");
    case LEVEL_STALE:
        return _("Stale");
    case LEVEL_WARN:
        return _("Warning");
    case LEVEL_OK:
        return _("OK");
    case LEVEL_INACTIVE:
        return _("Out of service");
    default:
        return _("No data");
    }
};

const glyphFor = (level: number): React.ReactElement | null => {
    switch (level) {
    case LEVEL_ERROR:
        return <Icon status="danger"><ExclamationCircleIcon /></Icon>;
    case LEVEL_STALE:
        return <Icon status="info"><ClockIcon /></Icon>;
    case LEVEL_WARN:
        return <Icon status="warning"><ExclamationTriangleIcon /></Icon>;
    case LEVEL_OK:
        return <Icon status="success"><CheckCircleIcon /></Icon>;
    case LEVEL_INACTIVE:
        return <Icon className="severity-icon-inactive"><PowerOffIcon /></Icon>;
    default:
        return null;
    }
};

/*
 * `hideOk` is what keeps repeating lists calm: in the tree and in the issue
 * list a healthy status writes nothing at all, because "everything is fine" is
 * not something anybody scans for. The tick is only drawn where exactly one
 * line stands, such as a manipulator card header.
 *
 * A native `title` rather than a PatternFly Tooltip: this renders in up to 34
 * table rows at once, and the word has to reach screen readers through
 * `aria-label` in any case.
 */
export const SeverityIcon = ({
    level,
    hideOk = false,
}: {
    level: number,
    hideOk?: boolean,
}) => {
    if (hideOk && level === LEVEL_OK) {
        return null;
    }

    const glyph = glyphFor(level);
    if (!glyph) {
        return null;
    }

    const label = severityLabel(level);
    return (
        <span className="severity-icon" role="img" aria-label={label} title={label}>
            {glyph}
        </span>
    );
};
