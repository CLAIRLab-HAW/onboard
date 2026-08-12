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

import cockpit from 'cockpit';

const _ = cockpit.gettext;

/*
 * The end effector, drawn at the opening it actually reports.
 *
 * What is exact and what is not, because the difference matters when someone
 * later reads a distance off this picture:
 *
 *  - The jaw gap IS the measurement. The inner faces sit at +/- width/2 on a
 *    scale where `stroke_mm` spans HALF_SPAN*2 drawing units, so the picture is
 *    open exactly as far as the driver says. Read the number, not the pixels,
 *    but the pixels will not lie to you.
 *  - The linkage is a SCHEMATIC, not kinematics. Pivot spacing (+/-24.1 mm) and
 *    the four-bar layout come from `rg6_description`'s URDF so the mechanism
 *    leans the way the real one leans, but the coupler is drawn from the pivot
 *    to wherever the jaw carrier ended up, so its length varies by a few
 *    percent across the range. A faithful planar solution would need the real
 *    finger geometry, and this is a status panel, not a viewer.
 *
 * The 3D meshes in `rg6_description` are deliberately not used: rendering STL
 * in the browser means a 3D library, and this project takes no new
 * dependencies.
 */

// Drawing units. The viewBox is centred on the jaw centreline.
const HALF_SPAN = 80; // half of a fully open gripper
const BODY_W = 68;
const BODY_H = 30;
const PIVOT_X = 24.1; // URDF: outer knuckle origin, +/-0.024112 m
const PIVOT_Y = BODY_H;
const INNER_PIVOT_X = 12.7; // URDF: inner knuckle origin, +/-0.012720 m
const INNER_PIVOT_Y = BODY_H + 6;
const JAW_T = 11;
const JAW_TOP = 64;
const JAW_BOT = 120;

export const GripperGraphic = ({
    percent,
    widthMm,
    strokeMm,
    gripDetected,
}: {
    percent: number | null,
    widthMm: string | null,
    strokeMm: string | null,
    gripDetected: boolean | null,
}) => {
    /*
     * No measurement, no picture. Without tool voltage the RG6 reports neither
     * a width nor an analog value, and a gripper drawn at a guessed pose would
     * be the one thing on this page that states something nobody measured.
     */
    if (percent === null) {
        return null;
    }

    const open = Math.max(0, Math.min(100, percent)) / 100;
    const half = open * HALF_SPAN; // inner face of each jaw
    const carrier = half + JAW_T / 2; // centre of each jaw

    const reading = widthMm && strokeMm
        ? cockpit.format(_("$0 of $1 mm"), widthMm, strokeMm)
        : `${percent.toFixed(0)} %`;
    // The bar this replaces was a labelled PatternFly Progress; a picture that
    // does not say the same thing out loud would lose the value for anyone on
    // a screen reader.
    const label = `${_("Opening")}: ${reading}`;

    const arm = (sign: number) => {
        const px = sign * PIVOT_X;
        const ix = sign * INNER_PIVOT_X;
        const cx = sign * carrier;
        return (
            <g key={sign}>
                {/* coupler: pivot -> jaw carrier */}
                <line x1={px} y1={PIVOT_Y} x2={cx} y2={JAW_TOP + 4} className="rg6-link" />
                {/* inner knuckle: the second bar that keeps the jaw parallel */}
                <line
                    x1={ix}
                    y1={INNER_PIVOT_Y}
                    x2={px + (cx - px) * 0.55}
                    y2={PIVOT_Y + (JAW_TOP + 4 - PIVOT_Y) * 0.55}
                    className="rg6-link rg6-link-thin"
                />
                <circle cx={px} cy={PIVOT_Y} r={2.6} className="rg6-pivot" />
                {/* jaw */}
                <rect
                    x={cx - JAW_T / 2}
                    y={JAW_TOP}
                    width={JAW_T}
                    height={JAW_BOT - JAW_TOP}
                    rx={2}
                    className="rg6-jaw"
                />
            </g>
        );
    };

    return (
        <figure className="rg6-figure">
            <svg
                viewBox={`${-(HALF_SPAN + JAW_T + 8)} -4 ${(HALF_SPAN + JAW_T + 8) * 2} ${JAW_BOT + 12}`}
                className="rg6-graphic"
                role="img"
                aria-label={label}
            >
                <rect
                    x={-BODY_W / 2}
                    y={0}
                    width={BODY_W}
                    height={BODY_H}
                    rx={4}
                    className="rg6-body"
                />
                {arm(-1)}
                {arm(1)}
                {/*
                  * A held object is drawn as a shape, not a colour: it fills the
                  * gap the jaws are holding. Colour on this page means severity,
                  * and "something is gripped" is not a severity.
                  */}
                {gripDetected && half > 1 && (
                    <rect
                        x={-half}
                        y={JAW_TOP + 12}
                        width={half * 2}
                        height={JAW_BOT - JAW_TOP - 24}
                        rx={2}
                        className="rg6-object"
                    />
                )}
                {/* dimension line across the gap, so the drawing states what it measures */}
                <line x1={-half} y1={JAW_BOT + 8} x2={half} y2={JAW_BOT + 8} className="rg6-dim" />
                <line x1={-half} y1={JAW_BOT + 4} x2={-half} y2={JAW_BOT + 12} className="rg6-dim" />
                <line x1={half} y1={JAW_BOT + 4} x2={half} y2={JAW_BOT + 12} className="rg6-dim" />
            </svg>
            <figcaption className="rg6-caption">{label}</figcaption>
        </figure>
    );
};
