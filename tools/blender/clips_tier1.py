"""Monkey's Tier-1 animation kit (docs/ANIMATION-UI-DIRECTION.md §4, plan Step 5).

    cd tools/blender && python clips_tier1.py -- ../../ui/public/models/monkey.glb [--only name,name]

Adds the clips below to the GLB (existing clips untouched). 30 fps. Names ending in _loop loop at runtime;
everything else plays once and returns to the state clip. Faces (yawn mouth, sleepy lids, tongue) are driven by
code (EXPRESSIONS in ui/src/avatar3d.ts), and sound/VFX beats live in ui/src/avatar/events.ts.

Principles baked in (DK idle study): heavy anticipation before big moves, fast action, slow settle with overshoot,
the head arriving last (overlap), held "attitude" poses, and asymmetry (no twinning).
"""
from __future__ import annotations

from pathlib import Path

import bpy

from anim import Clip, Rig, merge, override, pose, scaled, squash, sym
from common import args, export_glb, import_glb
from reach import body_front, solve

def P(rot=None, loc=None, scale=None):
    return pose(rot, loc, scale)


# ---------------------------------------------------------------- reusable poses
CHEST_PUFF = P({"spine": [("x", -4)], "chest": [("x", -8)], "head": [("x", 5)]},
               scale={"chest": (1.06, 1.0, 1.06)})
ARMS_HANG_WIDE = sym(P({"upper_arm.R": [("y", 12)], "forearm.R": [("x", -15)]}))
CROUCH = merge(sym(P({"thigh.R": [("x", -28)], "shin.R": [("x", 45)], "foot.R": [("x", -17)]})),
               P({"spine": [("x", 10)]}, loc={"hips": (0, 0, -0.035)}))
HAND_AT_HEAD_R = P({"shoulder.R": [("y", 10)], "upper_arm.R": [("y", 95), ("x", -35)],
                    "forearm.R": [("x", -115)], "hand.R": [("y", 20)], "head": [("y", -8)]})
HAND_ON_BELLY_L = sym(P({"upper_arm.R": [("x", -25), ("y", -8)], "forearm.R": [("x", -85), ("z", -30)]}))
HAND_ON_BELLY_L = P({b: v for b, v in HAND_ON_BELLY_L["rot"].items() if b.endswith(".L")})
FIST = {f"{f}.0{i}.R": [("x", -70)] for f in ("f1", "f2", "f3") for i in (1, 2)}
FIST_L = sym(P(FIST))["rot"]


def head_top(x: float, band: float = 0.03) -> float:
    head = bpy.data.objects["Head"]
    zs = [(head.matrix_world @ v.co).z for v in head.data.vertices if abs((head.matrix_world @ v.co).x - x) < band]
    return max(zs) if zs else 0.9


def touches(rig) -> dict:
    """Solved arm poses that put a hand exactly on a spot of his body (see reach.py)."""
    a = rig.arm
    bf = lambda x, z: body_front(a, x, z)   # noqa: E731 - skin surface (min Y) at x, z
    seed_head = {"upper_arm.R": [("y", 95), ("x", -35)], "forearm.R": [("x", -115)]}
    seed_front = {"upper_arm.R": [("x", -30)], "forearm.R": [("x", -60), ("z", 50)]}
    seed_front_l = {"upper_arm.L": [("x", -30)], "forearm.L": [("x", -60), ("z", -50)]}
    t = {
        "head_R": solve(rig, "R", (-0.07, -0.02, head_top(-0.07) + 0.015), "finger", seed_head),
        "belly_L": solve(rig, "L", (0.05, bf(0.05, 0.33) - 0.03, 0.33), "finger", seed_front_l),
        "pec_R": solve(rig, "R", (-0.07, bf(-0.07, 0.47) - 0.035, 0.47), "hand", seed_front),
        "pec_L": solve(rig, "L", (0.07, bf(0.07, 0.47) - 0.035, 0.47), "hand", seed_front_l),
        "meet_R": solve(rig, "R", (-0.025, bf(0.0, 0.43) - 0.15, 0.43), "hand", seed_front),
        "meet_L": solve(rig, "L", (0.025, bf(0.0, 0.43) - 0.15, 0.43), "hand", seed_front_l),
        "cross_R": solve(rig, "R", (0.15, bf(0.15, 0.45) - 0.06, 0.45), "hand", seed_front),
        "cross_L": solve(rig, "L", (-0.15, bf(-0.15, 0.41) - 0.03, 0.41), "hand", seed_front_l),
        "eye_R": solve(rig, "R", (-0.07, -0.25, 0.745), "finger", seed_head),
        "cock_R": solve(rig, "R", (-0.21, bf(-0.2, 0.5) - 0.09, 0.57), "hand", seed_front),
        "cock_L": solve(rig, "L", (0.21, bf(0.2, 0.5) - 0.09, 0.57), "hand", seed_front_l),
        "fist_R": solve(rig, "R", (-0.01, bf(0.0, 0.40) - 0.2, 0.41), "hand", seed_front),
        "palm_L": solve(rig, "L", (0.02, bf(0.0, 0.40) - 0.2, 0.37), "hand", seed_front_l),
    }
    return {k: P(v) for k, v in t.items()}


def clips(rig) -> list[Clip]:
    global HAND_AT_HEAD_R, HAND_ON_BELLY_L
    out: list[Clip] = []
    T = touches(rig)
    HAND_AT_HEAD_R = merge(T["head_R"], P({"head": [("y", -8)], "hand.R": [("y", 10)]}))
    HAND_ON_BELLY_L = T["belly_L"]

    # ---- idle fidgets ----------------------------------------------------------------------------------
    c = Clip("idle_lookaround", 90)
    look_l = P({"chest": [("z", 10)], "neck": [("z", 8)], "head": [("z", 18), ("y", 4)],
                "eye.R": [("z", 10)], "eye.L": [("z", 10)]})
    look_r = P({"chest": [("z", -8)], "neck": [("z", -7)], "head": [("z", -15), ("x", 4)],
                "eye.R": [("z", -10)], "eye.L": [("z", -10)]})
    c.at(0).at(12, look_l, "out").at(40, scaled(look_l, 1.05)).at(52, look_r, "out").at(74, look_r).at(90)
    out.append(c)

    c = Clip("idle_scratch_head", 78)
    scratch_a = merge(HAND_AT_HEAD_R, P({"hand.R": [("x", 12)], "f1.01.R": [("x", -30)], "f2.01.R": [("x", -30)]}))
    scratch_b = merge(HAND_AT_HEAD_R, P({"hand.R": [("x", -14)], "f1.01.R": [("x", -55)], "f2.01.R": [("x", -55)]}))
    c.at(0).at(5, scaled(HAND_AT_HEAD_R, -0.08), "in").at(16, HAND_AT_HEAD_R, "back")
    for i, f in enumerate(range(22, 60, 6)):
        c.at(f, scratch_a if i % 2 == 0 else scratch_b, "linear")
    c.at(64, HAND_AT_HEAD_R).at(78)
    out.append(c)

    c = Clip("idle_scratch_belly", 72)
    rub_a = merge(HAND_ON_BELLY_L, P({"forearm.L": [("z", 10)], "spine": [("x", -3)]}))
    rub_b = merge(HAND_ON_BELLY_L, P({"forearm.L": [("z", -10)], "upper_arm.L": [("x", -6)]}))
    c.at(0).at(14, HAND_ON_BELLY_L, "out")
    for i, f in enumerate(range(20, 56, 6)):
        c.at(f, rub_a if i % 2 == 0 else rub_b)
    c.at(60, merge(HAND_ON_BELLY_L, P({"head": [("x", -6)]}))).at(72)   # content little head-back at the end
    out.append(c)

    c = Clip("idle_knuckle_crack", 60)
    hands_meet = merge(T["meet_R"], T["meet_L"], P(FIST), P(FIST_L), P({"head": [("x", 8)]}))
    crack = merge(hands_meet, sym(P({"hand.R": [("x", -25)], "shoulder.R": [("y", 6)]})), P({"head": [("y", 6)]}))
    c.at(0).at(14, hands_meet, "out").at(26, hands_meet).at(28, crack, "snap").at(34, hands_meet, "out")
    c.at(38, hands_meet).at(40, merge(crack, P({"head": [("y", -12)]})), "snap").at(48, hands_meet, "out").at(60)
    out.append(c)

    c = Clip("idle_stretch_shoulders", 90)
    reach = merge(sym(P({"upper_arm.R": [("y", 75), ("x", 10)], "forearm.R": [("x", -10)]})), CHEST_PUFF)
    roll_a = merge(sym(P({"shoulder.R": [("y", 10), ("x", 10)], "upper_arm.R": [("y", 70), ("x", -15)]})), CHEST_PUFF)
    roll_b = merge(sym(P({"shoulder.R": [("y", -6), ("x", -10)], "upper_arm.R": [("y", 72), ("x", 25)]})), CHEST_PUFF)
    c.at(0).at(18, reach, "out").at(32, roll_a).at(44, roll_b).at(56, roll_a).at(66, reach)
    c.at(78, scaled(ARMS_HANG_WIDE, 0.6), "out").at(90)
    out.append(c)

    c = Clip("idle_mini_chestbeat", 54)
    # wind-up: fists cocked back by the shoulders, chest puffed; then alternating hits on each pec
    wind = merge(T["cock_R"], T["cock_L"], P(FIST), P(FIST_L), scaled(CHEST_PUFF, 1.3))
    hit_r, hit_l = T["pec_R"], T["pec_L"]
    c.at(0).at(10, wind, "out")
    for i, f in enumerate((12, 18, 24, 30)):
        c.at(f, override(wind, hit_r if i % 2 == 0 else hit_l), "snap" if f == 12 else "out")
    c.at(38, merge(scaled(CHEST_PUFF, 1.2), P({"head": [("y", 8), ("x", -5)]})), "back")  # cocky head tilt
    c.at(54)
    out.append(c)

    c = Clip("idle_shake_off", 45)
    c.at(0).at(4, scaled(CROUCH, 0.5), "in")
    for i, f in enumerate(range(8, 36, 4)):
        amp = 12 * (1 - i / 8)
        s = 1 if i % 2 == 0 else -1
        c.at(f, P({"spine": [("z", s * amp * 0.5)], "chest": [("z", s * amp)], "head": [("z", -s * amp * 0.6)],
                   "upper_arm.R": [("y", 10 + s * 5)], "upper_arm.L": [("y", -10 + s * 5)]}), "linear")
    c.at(45)
    out.append(c)

    c = Clip("idle_cross_eyes", 45)
    cross = P({"eye.R": [("z", 18)], "eye.L": [("z", -18)], "head": [("x", 5), ("y", 4)]})
    c.at(0).at(6, cross, "snap").at(32, cross).at(34, P({"head": [("x", -3)]}), "snap").at(45)
    out.append(c)

    c = Clip("idle_flex_check", 78)
    flex = merge(P({"upper_arm.R": [("y", 80)], "forearm.R": [("x", -120), ("y", 30)], **FIST,
                    "neck": [("z", -10)], "head": [("z", -22), ("x", 10)], "chest": [("z", -6)]}), scaled(CHEST_PUFF, 0.6))
    c.at(0).at(6, scaled(flex, -0.1), "in").at(18, flex, "back").at(40, flex)
    c.at(46, merge(flex, P({"head": [("x", 18)]}))).at(52, flex).at(58, merge(flex, P({"head": [("x", 14)]}))).at(78)
    out.append(c)

    c = Clip("idle_impatient_tap", 120)
    arms_crossed = merge(T["cross_R"], T["cross_L"], P({"head": [("y", 5), ("x", -3)]}))
    tap_up = merge(arms_crossed, P({"foot.R": [("x", 22)], "toe.R": [("x", -10)]}))
    c.at(0).at(14, arms_crossed, "out")
    for i, f in enumerate(range(20, 84, 10)):
        c.at(f, tap_up, "out").at(f + 5, arms_crossed, "in")
    c.at(92, merge(arms_crossed, CHEST_PUFF)).at(102, merge(arms_crossed, P({"head": [("x", 10)]}))).at(120)
    out.append(c)

    # ---- sleep chain -------------------------------------------------------------------------------------
    c = Clip("yawn", 78)
    yawn_up = merge(sym(P({"upper_arm.R": [("y", 115), ("x", 15)], "forearm.R": [("x", -30)]})),
                    P({"spine": [("x", -6)], "chest": [("x", -10)], "head": [("x", -18)]}, scale={"chest": (1.08, 1.0, 1.08)}))
    c.at(0).at(8, scaled(CROUCH, 0.25), "in").at(26, yawn_up, "out").at(46, merge(yawn_up, P({"head": [("y", 6)]})))
    c.at(60, merge(scaled(yawn_up, 0.3), P({"head": [("x", 8)]})), "in").at(78)
    out.append(c)

    SIT = merge(sym(P({"thigh.R": [("x", -85), ("y", 12)], "shin.R": [("x", 25)], "foot.R": [("x", 40)],
                       "upper_arm.R": [("y", 8), ("x", -12)], "forearm.R": [("x", -35)]})),
                P({"spine": [("x", 8)], "chest": [("x", 4)], "head": [("x", -4)], "tail.01": [("x", 30)]},
                  loc={"hips": (0, 0.02, -0.13)}))
    c = Clip("sit_down", 45)
    c.at(0).at(10, CROUCH, "in").at(20, merge(SIT, P(loc={"hips": (0, 0, 0.04)})), "in")
    c.at(24, merge(SIT, P(loc={"hips": (0, 0, -0.012)}), squash("spine", 0.08)), "out")   # plop + belly jiggle
    c.at(32, merge(SIT, squash("spine", -0.03)), "out").at(45, SIT, "elastic")
    out.append(c)

    DOZE = merge(SIT, P({"neck": [("x", 18)], "head": [("x", 22), ("y", 5)], "chest": [("x", 8)]}))
    c = Clip("sit_doze_loop", 150, loop=True)
    c.lag = False
    c.at(0, SIT).at(60, scaled_into(SIT, DOZE, 0.6), "in").at(84, DOZE, "in")
    c.at(88, merge(SIT, P({"head": [("x", -6)]})), "back").at(120, scaled_into(SIT, DOZE, 0.3)).at(150, SIT)
    out.append(c)

    # On his left side facing you (reads clearly from the front camera), knees tucked a little,
    # lower arm folded up under his head as a pillow, top arm draped over his belly.
    LIE = merge(P({"root": [("y", 86)]}, loc={"root": (-0.33, 0, 0.16)}),
                sym(P({"thigh.R": [("x", -40)], "shin.R": [("x", 55)]})),
                P({"upper_arm.L": [("y", -155), ("x", -15)], "forearm.L": [("x", -120)],    # pillow arm
                   "upper_arm.R": [("y", -35), ("x", -30)], "forearm.R": [("x", -45), ("z", 35)],   # over belly
                   "head": [("y", 10), ("x", 8)], "neck": [("y", 4)], "tail.01": [("x", 20)]}))
    c = Clip("lie_down", 60)
    c.at(0, SIT).at(14, merge(SIT, P({"chest": [("y", 12)], "head": [("y", 10)]})), "in")
    c.at(38, merge(scaled(LIE, 1.06)), "out").at(46, merge(LIE, squash("spine", 0.05)), "out").at(60, LIE, "elastic")
    out.append(c)

    c = Clip("sleep_loop", 180, loop=True)
    c.lag = False
    breathe_in = merge(LIE, P({"spine": [("x", -4)], "chest": [("x", -5)], "head": [("y", 3)]},
                              scale={"chest": (1.07, 1.0, 1.07), "spine": (1.05, 1.0, 1.05)}))
    c.at(0, LIE).at(100, breathe_in, "smooth").at(180, LIE, "smooth")
    out.append(c)

    c = Clip("wake_startle", 40)
    c.lag = False
    air = merge(sym(P({"upper_arm.R": [("y", 100)], "forearm.R": [("x", -20)], "thigh.R": [("x", -20)]})),
                P({"head": [("x", -12)]}, loc={"hips": (0, 0, 0.12)}), squash("spine", -0.1))
    land = merge(CROUCH, squash("spine", 0.1), P(loc={"hips": (0, 0, -0.02)}))
    c.at(0, LIE).at(3, merge(LIE, P({"head": [("y", 12)]})), "snap").at(10, air, "out").at(16, land, "in")
    c.at(22, scaled(CROUCH, 0.3), "back").at(26, HAND_AT_HEAD_R).at(34, merge(HAND_AT_HEAD_R, P({"hand.R": [("x", -12)]})))
    c.at(40)
    out.append(c)

    c = Clip("wake_groggy", 96)
    rub = merge(SIT, T["eye_R"], P({"head": [("x", 12)], "neck": [("x", 6)]}))
    c.at(0, LIE).at(24, merge(SIT, P({"head": [("x", 14)]})), "smooth").at(36, rub)
    c.at(42, merge(rub, P({"hand.R": [("z", 15)]}))).at(48, rub).at(54, merge(rub, P({"hand.R": [("z", -15)]})))
    c.at(64, CROUCH, "smooth").at(76, scaled(yawn_up, 0.5)).at(96)
    out.append(c)

    # ---- attention / thinking -----------------------------------------------------------------------------
    c = Clip("attn_perk", 20)
    perk = merge(P({"head": [("x", -8)], "neck": [("x", -4)], "ear.R": [("z", 12)], "ear.L": [("z", -12)]},
                   loc={"hips": (0, 0, 0.035)}), squash("spine", -0.05))
    c.at(0).at(3, scaled(CROUCH, 0.25), "in").at(8, perk, "out").at(12, P({"head": [("x", -6)]}), "in").at(20, P(), "back")
    out.append(c)

    c = Clip("think_eureka", 26)
    idea = merge(P({"upper_arm.R": [("y", 70), ("x", -50)], "forearm.R": [("x", -100)], "hand.R": [("x", -10)],
                    "f2.01.R": [("x", -80)], "f2.02.R": [("x", -80)], "f3.01.R": [("x", -80)], "f3.02.R": [("x", -80)],
                    "head": [("x", -10), ("y", 6)]}, loc={"hips": (0, 0, 0.02)}), CHEST_PUFF)
    c.at(0).at(4, scaled(idea, -0.1), "in").at(9, idea, "back").at(26, idea)
    out.append(c)

    # ---- talk gestures (upper body; layered over talk at runtime) ---------------------------------------------
    open_palms = sym(P({"upper_arm.R": [("y", 8), ("x", -40)], "forearm.R": [("x", -65), ("z", -15)],
                        "hand.R": [("y", -25)]}))
    gest = {
        "talk_gest_open_palms": (open_palms, 30),
        "talk_gest_point": (merge(P({"upper_arm.R": [("x", -60), ("y", 15)], "forearm.R": [("x", -25)],
                                     "f2.01.R": [("x", -80)], "f2.02.R": [("x", -80)], "f3.01.R": [("x", -80)],
                                     "f3.02.R": [("x", -80)], "chest": [("z", -6)], "head": [("x", 4)]})), 30),
        "talk_gest_shrug": (merge(open_palms, sym(P({"shoulder.R": [("y", -14)]})),
                                  P({"head": [("y", 10)], "neck": [("y", 4)]})), 34),
        "talk_gest_thumbs_up": (merge(P({"upper_arm.R": [("y", 40), ("x", -45)], "forearm.R": [("x", -95)], **FIST}),
                                      P({"head": [("y", 6)]}), scaled(CHEST_PUFF, 0.5)), 34),
        "talk_gest_big": (merge(sym(P({"upper_arm.R": [("y", 85), ("x", -20)], "forearm.R": [("x", -40)]})),
                                CHEST_PUFF), 36),
        "talk_gest_fist_palm": (merge(T["fist_R"], P(FIST), T["palm_L"]), 28),
    }
    for name, (g, n) in gest.items():
        c = Clip(name, n)
        c.at(0).at(4, scaled(g, -0.12), "in").at(10, g, "back").at(n - 10, scaled(g, 0.9)).at(n)
        out.append(c)
    return out


def scaled_into(a, b, k):
    """Blend between two poses: a + (b - a) * k (rotations are small, so blending angle lists is fine)."""
    return merge(scaled(a, 1 - k), scaled(b, k)) if a is not b else a


def main():
    a = args()
    path = Path(a[0])
    only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
    arm = import_glb(path)
    rig = Rig(arm)
    rig.capture_base()
    for c in clips(rig):
        if only and c.name not in only:
            continue
        if c.name in bpy.data.actions:
            bpy.data.actions.remove(bpy.data.actions[c.name])
        rig.build(c)
    export_glb(Path(a[1]) if len(a) > 1 and not a[1].startswith("--") else path)


if __name__ == "__main__":
    main()
