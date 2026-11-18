"""Render-check the DSL's axis conventions: one held pose per clip (see contact_sheet.js)."""
from pathlib import Path

from anim import Clip, Rig, pose, sym
from common import args, export_glb, import_glb

arm = import_glb()
rig = Rig(arm)
rig.capture_base()
tests = {
    "t_arm_side": pose({"upper_arm.R": [("y", 60)]}),
    "t_arm_fwd": pose({"upper_arm.R": [("x", -60)]}),
    "t_elbow": pose({"forearm.R": [("x", -70)]}),
    "t_lean_fwd": pose({"spine": [("x", 15)], "chest": [("x", 15)]}),
    "t_turn_left": pose({"chest": [("z", 25)], "head": [("z", 30)]}),
    "t_tilt_left": pose({"head": [("y", 20)]}),
    "t_sym_arms": sym(pose({"upper_arm.R": [("y", 70)], "forearm.R": [("x", -40)]})),
    "t_squat": pose({"thigh.R": [("x", -40)], "shin.R": [("x", 60)]}, loc={"hips": (0, 0, -0.06)}),
}
for name, p in tests.items():
    c = Clip(name, 10)
    c.at(0, p, "snap").at(10, p, "snap")
    c.lag = False
    rig.build(c)
export_glb(Path(args()[0]))
