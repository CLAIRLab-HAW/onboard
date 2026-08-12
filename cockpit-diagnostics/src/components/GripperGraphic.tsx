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
const JAW_T = 11;
const JAW_TOP = 58;
const JAW_BOT = 138; // long fingers: the RG6's are long relative to its body
const PAD_T = 3.5; // gripping face, drawn on the inner side of each finger

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

    /*
     * One coupler per side and nothing else. An earlier version also drew the
     * inner knuckle of the four-bar; at the size this renders it was invisible
     * behind the body and the coupler, so it cost strokes and told nobody
     * anything.
     */
    const arm = (sign: number) => {
        const px = sign * PIVOT_X;
        const cx = sign * carrier;
        const inner = sign * half; // the face that touches the object
        return (
            <g key={sign}>
                <line x1={px} y1={PIVOT_Y} x2={cx} y2={JAW_TOP + 6} className="rg6-link" />
                <circle cx={px} cy={PIVOT_Y} r={2.6} className="rg6-pivot" />
                <rect
                    x={cx - JAW_T / 2}
                    y={JAW_TOP}
                    width={JAW_T}
                    height={JAW_BOT - JAW_TOP}
                    rx={2.5}
                    className="rg6-jaw"
                />
                {/* gripping face, so it reads as a finger rather than a post */}
                <rect
                    x={sign > 0 ? inner : inner - PAD_T}
                    y={JAW_TOP + 22}
                    width={PAD_T}
                    height={JAW_BOT - JAW_TOP - 32}
                    className="rg6-pad"
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
                {/*
                  * A slim dimension line between the fingertips, so it is
                  * visible which distance the caption underneath is quoting.
                  * Only the ticks and the rule -- the number lives in the
                  * caption, printing it twice would just be noise.
                  */}
                <line x1={-half} y1={JAW_BOT + 7} x2={half} y2={JAW_BOT + 7} className="rg6-dim" />
                <line x1={-half} y1={JAW_BOT + 3} x2={-half} y2={JAW_BOT + 11} className="rg6-dim" />
                <line x1={half} y1={JAW_BOT + 3} x2={half} y2={JAW_BOT + 11} className="rg6-dim" />
            </svg>
            <figcaption className="rg6-caption">{label}</figcaption>
        </figure>
    );
};
