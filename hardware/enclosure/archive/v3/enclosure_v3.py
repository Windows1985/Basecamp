"""
Basecamp enclosure v3 — compact Apple-style parametric CAD generator.
Body + lid STEP/STL for Taobao 3D printing.

v3 changes (from v2 review):
  FIXES
  - Pi 4 standoffs repositioned: port face now flush with inner rear wall,
    USB/Ethernet align with the rear IO cutout (v2 had ports facing the baffle)
  - Chimney no longer a sealed box: walls stop below the lid, the lid carries a
    plug cap (labyrinth seal); SCD40 drops into a card slot; 8mm wire grommet
    through the chimney wall straight to the Pi GPIO edge
  - Chimney relocated to the left-rear dead zone beside the Pi (frees the
    sensor zone, lets the box shrink, plug welds to solid lid)
  COMPACTNESS  96 x 132 x 54 assembled (was 100 x 150 x 73), pod max height 79
  - Width driven by the 86mm screen module pod (92) + 2mm reveal each side
  - Length = 34 sensor zone + 3 baffle + 89 Pi zone (85 PCB + 4 slack)
  - Height = Pi USB stack (25.4) + cable headroom; hub stands on edge in the
    17mm right-hand margin beside the Pi
  APPLE AESTHETIC / UX
  - Zero visible fasteners: 4x M3x50 enter from below through hollow corner
    posts into lid bosses; counterbores hidden under adhesive feet
  - Lid registration lip (1.8 x 2.5) for a tight, repeatable seam
  - ESP32 antenna window replaced by a 1mm membrane (clean front face,
    negligible at 2.4GHz) - front face now has zero open holes except the mic
  - Screen pod flipped: low edge faces the bed, display readable from bed
    (backlight off at night via GPIO22), 0.5mm bezel margin on the cutout
  - Radar pocket +1mm height; mic alignment recess; BH1750 light hole in lid;
    accessory boss grid for SHT40/SGP40 breakouts
  - 45 deg chamfer over the rear IO opening (printability)
  ASSEMBLY
  - Everything reachable with the lid off; screen foam-tapes into the pod from
    below; SCD40 serviceable by lifting the lid; ESP flashes in place through
    the left-wall USB-C service slot
"""
import math
import cadquery as cq

# ---------------- master ----------------
OUTER_W, OUTER_L = 96.0, 136.0
BODY_H, LID_T = 51.0, 3.0          # assembled height 54 + pod
WALL = 3.0
R_CORNER, R_EDGE = 8.0, 1.5
IN_X = OUTER_W / 2 - WALL          # 45
IN_Y = OUTER_L / 2 - WALL          # 63
R_IN = R_CORNER - WALL             # 5
FLOOR_Z = WALL

# ---------------- zones ----------------
SENSOR_D, BAFFLE_T = 38.0, 3.0
BAFFLE_Y = -IN_Y + SENSOR_D        # -29 front face of baffle
BAFFLE_GAP = 8.0                   # cable + pressure-equalisation gap
BAFFLE_TOP = 48.3                  # clears lid lip (lip bottom 48.5)

# ---------------- Pi 4 (holes 58x49, 3.5 inset; USB end overhangs 23.5) ----
PI_DX = 24.5                       # PCB spans X -28..28
PI_HOLE_YF = IN_Y - 85.0 + 3.5     # -18.5  (PCB Y -22..63, ports flush rear)
PI_HOLE_YR = PI_HOLE_YF + 58.0     # 39.5
SO_H, SO_D, SO_PILOT, SO_PILOT_D = 5.0, 6.0, 2.2, 6.0
IO_W, IO_Z0, IO_Z1 = 58.0, 8.0, 27.0

# ---------------- ESP32-S3 DevKitC (70x28 flat, USB end at left wall) ------
ESP_YF, ESP_W = -57.5, 28.0        # Y -57.5..-29.5 (clears front posts)
RAIL_H = 5.0
RAIL_X0, RAIL_X1 = -38.0, 18.0     # board X -43.5..26.5, antenna at +X end
ESP_CY = ESP_YF + ESP_W / 2        # -46
ANT_W, ANT_H, ANT_CX, ANT_CZ = 18.0, 14.0, 20.0, 12.0
SKIN = 1.0                         # RF membrane thickness (radar + antenna)
USB_SLOT_L, USB_SLOT_H, USB_SLOT_Z0 = 22.0, 9.0, 5.0

# ---------------- front face ----------------
RADAR_W, RADAR_H, RADAR_CX, RADAR_CZ = 24.0, 17.0, -8.0, 36.0
MIC_D, MIC_CX, MIC_CZ = 2.5, -29.0, 36.0
MIC_REC_W, MIC_REC_H, MIC_REC_D = 14.0, 13.0, 1.5   # INMP441 alignment recess

# ---------------- chimney (left-rear, beside Pi) ----------------
CH_Y0, CH_WALL = 30.0, 1.5         # front wall 28.5..30; rear/left = body walls
CH_XR = -28.0                      # right wall outer face (Pi PCB edge at -28)
CH_TOP = 48.5                      # lid plug drops 1.5 inside
GROMMET_D, GROMMET_Y, GROMMET_Z = 8.0, 45.0, 13.0
RIB_Y0, RIB_Y1, RIB_H = 36.0, 54.0, 4.0
RIB_X = [(-38.0, -37.0), (-34.8, -33.8)]   # 2.2mm card slot, board stands in X-gap
CVENT_LEN, CVENT_CY = 14.0, 44.0
CVENT_Z = [8.0, 12.0, 40.0, 44.0]      # low in, high out
LVENT_LEN, LVENT_CY = 20.0, -46.0      # sensor-zone ambient vents
LVENT_Z = [30.0, 36.0, 42.0]
VENT_H = 1.5

# ---------------- rear cable slots (right margin) ----------------
SLOT_W, SLOT_CX = 13.0, 35.0
SLOT_Z = [(8.0, 16.0), (20.0, 28.0)]   # PSU / hub power / Node 2 cable

# ---------------- fasteners: M3x50 from below ----------------
POSTS = [(40.7, 61.35), (-40.7, 61.35), (40.7, -61.35), (-40.7, -61.35)]
RIB_W = 1.5                        # weld ribs tying posts to both walls
POST_D, POST_TOP = 6.5, 41.0       # hollow posts, lid bosses drop to meet them
BORE_D, CBORE_D, CBORE_DEPTH = 3.4, 6.8, 2.4   # pan head flush; feet placed inboard
BOSS_DROP, PILOT_D = 10.0, 2.5     # M3 thread-forming pilot

# ---------------- accessory boss grid (SHT40 / SGP40) ----------------
PAD_XY = [(31.0, -52.0), (41.0, -52.0), (31.0, -38.0), (41.0, -38.0)]
PAD_D, PAD_H, PAD_PILOT = 5.0, 4.0, 2.0

# ---------------- lid: lip, plug, pod ----------------
LIP_W, LIP_DROP, LIP_CLR = 1.8, 2.5, 0.25
PLUG_CLR, PLUG_DROP = 0.4, 4.0
POD_Y0, POD_Y1 = -22.0, 36.0       # low edge FRONT (faces bed), high edge rear
POD_FRONT_H, POD_RISE, POD_WALL = 5.0, 20.0, 2.2
SCREEN_W, SCREEN_H = 58.6, 44.2    # active 57.6x43.2 + 0.5 margin
LIGHT_D, LIGHT_X, LIGHT_Y = 6.0, -25.0, -45.0
HOLE_LID_PILOT_TOP = 2.0           # pilot may run 2mm up into lid plate


def try_fillet(wp, selector, r):
    try:
        return wp.edges(selector).fillet(r)
    except Exception as e:
        print(f'  fillet skipped ({selector}, r={r}): {type(e).__name__}')
        return wp


def box_at(w, d, h, x, y, z, centered=(False, False, False)):
    return (cq.Workplane("XY").box(w, d, h, centered=centered)
            .translate((x, y, z)))


# ============================================================ BODY
body = (cq.Workplane("XY")
        .box(OUTER_W, OUTER_L, BODY_H, centered=(True, True, False)))
body = body.edges("|Z").fillet(R_CORNER)
body = try_fillet(body, "<Z", R_EDGE)

cavity = (cq.Workplane("XY")
          .box(2 * IN_X, 2 * IN_Y, BODY_H, centered=(True, True, False))
          .edges("|Z").fillet(R_IN)
          .translate((0, 0, FLOOR_Z)))
body = body.cut(cavity)

# baffle (hangs over an 8mm cable/air gap, stops just under the lid lip)
body = body.union(box_at(2 * IN_X, BAFFLE_T, BAFFLE_TOP - (FLOOR_Z + BAFFLE_GAP),
                         -IN_X, BAFFLE_Y, FLOOR_Z + BAFFLE_GAP))

# chimney walls (rear + left are the enclosure walls)
body = body.union(box_at(IN_X + CH_XR, CH_WALL, CH_TOP - FLOOR_Z,
                         -IN_X, CH_Y0 - CH_WALL, FLOOR_Z))            # front
body = body.union(box_at(CH_WALL, IN_Y - (CH_Y0 - CH_WALL), CH_TOP - FLOOR_Z,
                         CH_XR - CH_WALL, CH_Y0 - CH_WALL, FLOOR_Z))  # right
# SCD40 card-slot ribs
for x0, x1 in RIB_X:
    body = body.union(box_at(x1 - x0, RIB_Y1 - RIB_Y0, RIB_H,
                             x0, RIB_Y0, FLOOR_Z))
# wire grommet straight through to the Pi GPIO edge
body = body.cut(cq.Workplane("YZ", origin=(CH_XR - CH_WALL - 1, GROMMET_Y, GROMMET_Z))
                .circle(GROMMET_D / 2).extrude(CH_WALL + 2))

# ESP32 rails
for y0, y1 in ((ESP_YF, ESP_YF + 3.0), (ESP_YF + ESP_W - 3.0, ESP_YF + ESP_W)):
    body = body.union(box_at(RAIL_X1 - RAIL_X0, y1 - y0, RAIL_H,
                             RAIL_X0, y0, FLOOR_Z))

# Pi standoffs
for sx in (PI_DX, -PI_DX):
    for sy in (PI_HOLE_YF, PI_HOLE_YR):
        body = body.union(cq.Workplane("XY", origin=(sx, sy, FLOOR_Z))
                          .circle(SO_D / 2).extrude(SO_H))
        body = body.cut(cq.Workplane("XY", origin=(sx, sy, FLOOR_Z + SO_H - SO_PILOT_D))
                        .circle(SO_PILOT / 2).extrude(SO_PILOT_D + 0.1))

# accessory boss grid (SHT40 / SGP40 breakouts, M2 self-tap)
for px, py in PAD_XY:
    body = body.union(cq.Workplane("XY", origin=(px, py, FLOOR_Z))
                      .circle(PAD_D / 2).extrude(PAD_H))
    body = body.cut(cq.Workplane("XY", origin=(px, py, FLOOR_Z + PAD_H - 3.0))
                    .circle(PAD_PILOT / 2).extrude(3.1))

# hollow corner posts: M3x50 screw channel from below, heads hidden by feet
for px, py in POSTS:
    body = body.union(cq.Workplane("XY", origin=(px, py, FLOOR_Z))
                      .circle(POST_D / 2).extrude(POST_TOP - FLOOR_Z))
    sx, sy = (1 if px > 0 else -1), (1 if py > 0 else -1)
    body = body.union(box_at(IN_X - abs(px) + 0.1, RIB_W, POST_TOP - FLOOR_Z,
                             px if sx > 0 else -IN_X - 0.1,
                             py - RIB_W / 2, FLOOR_Z))
    body = body.union(box_at(RIB_W, IN_Y - abs(py) + 0.1, POST_TOP - FLOOR_Z,
                             px - RIB_W / 2,
                             py if sy > 0 else py - (IN_Y - abs(py)) - 0.1,
                             FLOOR_Z))
    body = body.cut(cq.Workplane("XY", origin=(px, py, -1))
                    .circle(BORE_D / 2).extrude(POST_TOP + 1.5))
    body = body.cut(cq.Workplane("XY", origin=(px, py, -0.1))
                    .circle(CBORE_D / 2).extrude(CBORE_DEPTH + 0.1))

# ---- front face: radar membrane pocket, mic hole + recess, antenna membrane
body = body.cut(box_at(RADAR_W, WALL - SKIN + 1, RADAR_H,
                       RADAR_CX - RADAR_W / 2, -OUTER_L / 2 + SKIN,
                       RADAR_CZ - RADAR_H / 2))
body = body.cut(cq.Workplane("XZ", origin=(MIC_CX, -OUTER_L / 2 - 1, MIC_CZ))
                .circle(MIC_D / 2).extrude(-(WALL + 2)))
body = body.cut(box_at(MIC_REC_W, MIC_REC_D + 1, MIC_REC_H,        # inside recess
                       MIC_CX - MIC_REC_W / 2, -IN_Y - MIC_REC_D,
                       MIC_CZ - MIC_REC_H / 2))
body = body.cut(box_at(ANT_W, WALL - SKIN + 1, ANT_H,
                       ANT_CX - ANT_W / 2, -OUTER_L / 2 + SKIN,
                       ANT_CZ - ANT_H / 2))

# ---- left wall: ESP USB-C service slot, sensor vents, chimney vents ----
def left_cut(length, h, cy, cz):
    return box_at(WALL + 2, length, h,
                  -OUTER_W / 2 - 1, cy - length / 2, cz - h / 2)

body = body.cut(left_cut(USB_SLOT_L, USB_SLOT_H, ESP_CY,
                         USB_SLOT_Z0 + USB_SLOT_H / 2))
for z in LVENT_Z:
    body = body.cut(left_cut(LVENT_LEN, VENT_H, LVENT_CY, z))
for z in CVENT_Z:
    body = body.cut(left_cut(CVENT_LEN, VENT_H, CVENT_CY, z))

# ---- rear: Pi IO with 45deg chamfer, two cable slots in the right margin ----
def rear_cut(w, z0, z1, cx=0.0):
    return box_at(w, WALL + 2, z1 - z0, cx - w / 2, OUTER_L / 2 - WALL - 1, z0)

body = body.cut(rear_cut(IO_W, IO_Z0, IO_Z1))
chamfer = (cq.Workplane("XY").box(IO_W, 3.0, 3.0, centered=(True, True, True))
           .rotate((0, 0, 0), (1, 0, 0), 45)
           .translate((0, OUTER_L / 2 - WALL / 2, IO_Z1)))
body = body.cut(chamfer)
for z0, z1 in SLOT_Z:
    body = body.cut(rear_cut(SLOT_W, z0, z1, SLOT_CX))

# ============================================================ LID
lid = (cq.Workplane("XY")
       .box(OUTER_W, OUTER_L, LID_T, centered=(True, True, False))
       .edges("|Z").fillet(R_CORNER))

# screen pod: low edge to the FRONT so the display faces the bed
pod = (cq.Workplane("YZ")
       .polyline([(POD_Y0, LID_T), (POD_Y1, LID_T),
                  (POD_Y1, LID_T + POD_FRONT_H + POD_RISE),
                  (POD_Y0, LID_T + POD_FRONT_H)])
       .close().extrude(2 * IN_X + 2)
       .translate((-(IN_X + 1), 0, 0)))
lid = lid.union(pod)
lid = try_fillet(lid, "|Z", 3.0)

theta = math.atan2(POD_RISE, POD_Y1 - POD_Y0)
dz = POD_WALL / math.cos(theta)
z_outer = lambda y: LID_T + POD_FRONT_H + (y - POD_Y0) * math.tan(theta)
lid = lid.cut(cq.Workplane("YZ")
              .polyline([(POD_Y0 + POD_WALL, -1), (POD_Y1 - POD_WALL, -1),
                         (POD_Y1 - POD_WALL, z_outer(POD_Y1 - POD_WALL) - dz),
                         (POD_Y0 + POD_WALL, z_outer(POD_Y0 + POD_WALL) - dz)])
              .close().extrude(2 * (IN_X + 1) - 2 * POD_WALL)
              .translate((-(IN_X + 1) + POD_WALL, 0, 0)))

tilt = math.degrees(theta)
lid = lid.cut(cq.Workplane("XY")
              .box(SCREEN_W, SCREEN_H, 24, centered=(True, True, True))
              .rotate((0, 0, 0), (1, 0, 0), tilt)
              .translate((0, (POD_Y0 + POD_Y1) / 2,
                          LID_T + POD_FRONT_H + POD_RISE / 2)))

# registration lip (interrupted beside the pod walls)
lip_o = (cq.Workplane("XY")
         .box(2 * IN_X - 2 * LIP_CLR, 2 * IN_Y - 2 * LIP_CLR, LIP_DROP,
              centered=(True, True, False))
         .edges("|Z").fillet(R_IN - LIP_CLR)
         .translate((0, 0, -LIP_DROP)))
lip_i = (cq.Workplane("XY")
         .box(2 * IN_X - 2 * (LIP_CLR + LIP_W), 2 * IN_Y - 2 * (LIP_CLR + LIP_W),
              LIP_DROP + 2, centered=(True, True, False))
         .edges("|Z").fillet(max(R_IN - LIP_CLR - LIP_W, 0.5))
         .translate((0, 0, -LIP_DROP - 1)))
lid = lid.union(lip_o.cut(lip_i))
for x0 in (39.5, -47.0):   # clear side lip where the pod cavity passes through
    lid = lid.cut(box_at(7.5, POD_Y1 - POD_Y0 + 1.0, LIP_DROP + 0.1,
                         x0, POD_Y0 - 0.5, -LIP_DROP - 0.05))

# chimney plug cap (labyrinth seal, welded to solid lid)
plug = box_at((CH_XR - CH_WALL) - (-IN_X) - 2 * PLUG_CLR,
              IN_Y - PLUG_CLR - (CH_Y0 + PLUG_CLR), PLUG_DROP,
              -IN_X + PLUG_CLR, CH_Y0 + PLUG_CLR, -PLUG_DROP)
plug = plug.edges("|Z and <X and >Y").fillet(R_IN - PLUG_CLR)  # follow cavity corner
lid = lid.union(plug)

# fastener bosses + pilots (meet the body posts at z 41)
for px, py in POSTS:
    lid = lid.union(cq.Workplane("XY", origin=(px, py, -BOSS_DROP))
                    .circle(POST_D / 2).extrude(BOSS_DROP))
    lid = lid.cut(cq.Workplane("XY", origin=(px, py, -BOSS_DROP - 0.1))
                  .circle(PILOT_D / 2)
                  .extrude(BOSS_DROP + HOLE_LID_PILOT_TOP + 0.1))

# BH1750 light hole (sensor foam-taped underneath)
lid = lid.cut(cq.Workplane("XY", origin=(LIGHT_X, LIGHT_Y, -0.5))
              .circle(LIGHT_D / 2).extrude(LID_T + 1))

# ============================================================ EXPORT + CHECKS
import os
os.makedirs("/home/claude/out", exist_ok=True)
for part, name in [(body, 'body'), (lid, 'lid')]:
    cq.exporters.export(part, f"/home/claude/out/basecamp_{name}_v3.step")
    cq.exporters.export(part, f"/home/claude/out/basecamp_{name}_v3.stl")

print(f"exported v3  |  body {OUTER_W:.0f} x {OUTER_L:.0f} x {BODY_H:.0f}, assembled {BODY_H+LID_T:.0f}, pod peak", 
      f"{BODY_H + LID_T + POD_FRONT_H + POD_RISE:.0f}")
print(f"Pi: PCB Y {IN_Y-85:.1f}..{IN_Y:.1f} (ports flush w/ inner rear wall {IN_Y})")
print(f"    front gap to baffle: {(IN_Y-85) - (BAFFLE_Y+BAFFLE_T):.1f}")
print(f"pod inner width: {2*IN_X+2-2*POD_WALL:.1f} (module 86.0)")
print(f"pod slant: {(POD_Y1-POD_Y0)/math.cos(theta):.1f} (module 50.0), tilt {tilt:.1f} deg")
print(f"chimney interior: {abs(CH_XR-CH_WALL-(-IN_X))-CH_WALL:.1f} x {IN_Y-(CH_Y0+CH_WALL):.1f}, walls to {CH_TOP}, plug to {BODY_H-PLUG_DROP}")
print(f"screw: M3x50 from below -> tip z {CBORE_DEPTH+50:.1f}, pilot ends z {BODY_H+HOLE_LID_PILOT_TOP}")
print(f"hub margin (right of Pi): {IN_X-28:.1f}mm")
