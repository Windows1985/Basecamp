"""
Basecamp enclosure v4 — compact Apple-style parametric CAD generator.
Body + lid STEP/STL for FDM printing.

v4 changes (from v3):
  POWER / NETWORKING ARCHITECTURE
  - USB hub DELETED: both ESP32 nodes power from the Pi's own USB-A ports
    (combined peak ~0.8A < Pi 1.2A budget; official 3A PSU covers total).
    Node 2's 5m 20AWG cable plugs into a rear USB-A and exits through the
    IO cutout itself - both rear cable slots deleted.
  - Body height 51 -> 46 (hub was the height driver). Assembled 49, pod peak 74.
  - Pi power enters through a LEFT WALL slot directly beside the Pi's USB-C
    port (right-angle plug, zero internal routing). Sockets are on the left
    side of the room, so the cable approaches from the correct side.
  - Ethernet exits through the rear IO cutout (no dedicated slot).
  MAGNETIC LID
  - 6x Ø6x3 N35 magnet pairs replace the 4 corner screws for daily access:
    2 front, 2 rear, 2 mid-side, seated in wall bosses (body) and underside
    pockets (lid). Lid lifts off tool-free; registration lip still aligns.
  - 2 REAR travel screws retained (M3x45 from below through hollow posts)
    for transport between HK / Shenzhen / California. Front posts deleted
    entirely (also permanently resolves the ESP32 corner clearance).
  VENTILATION RELOCATED (clean side faces)
  - Intakes move to the BASE (hidden by the foot gap): sensor-zone floor
    slots + chimney floor slot. Slightly lower intake = better stack effect.
  - Chimney exhaust moves to the REAR wall (utility face).
  - Sensor zone exhausts through the under-baffle gap -> compute zone ->
    rear IO opening: Pi warmth drives a continuous room->sensor->compute->out
    flow, guaranteeing air never flows compute->sensor.
  - Left wall keeps ONLY the ESP USB service slot + new Pi power slot.
    Right wall is completely blank.
  UX / SENSOR REFINEMENTS
  - Screen support rails inside the pod: module slides in and RESTS on
    rails (tape becomes anti-rattle, not structural). Vendor-thickness
    tolerant (0.7mm nominal glass recess, shim with tape if desired).
  - INMP441 mic funnel: tapered waveguide (Ø6 -> Ø2.5) reduces internal
    reflection pickup.
  - BH1750 light hole gains a 45deg countersink (wider acceptance cone).
  - Recovery-glow LED: Ø3 hole in the lid just in front of the pod; an RGB
    LED throws a colour halo onto the table (GPIO-driven, radar auto-wake).
  - Ø2 condensation drain at the sensor-zone floor line (front face, invisible).
"""
import math
import cadquery as cq

# ---------------- master ----------------
OUTER_W, OUTER_L = 96.0, 136.0
BODY_H, LID_T = 46.0, 3.0          # assembled 49 + pod
WALL = 3.0
R_CORNER, R_EDGE = 8.0, 1.5
IN_X = OUTER_W / 2 - WALL          # 45
IN_Y = OUTER_L / 2 - WALL          # 65
R_IN = R_CORNER - WALL             # 5
FLOOR_Z = WALL

# ---------------- zones ----------------
SENSOR_D, BAFFLE_T = 38.0, 3.0
BAFFLE_Y = -IN_Y + SENSOR_D        # -27 front face of baffle
BAFFLE_GAP = 8.0
BAFFLE_TOP = BODY_H - 2.7          # 43.3, clears lid lip (lip bottom 43.5)

# ---------------- Pi 4 ----------------
PI_DX = 24.5                       # PCB spans X -28..28
PI_HOLE_YF = IN_Y - 85.0 + 3.5     # -16.5  (PCB Y -20..65, ports flush rear)
PI_HOLE_YR = PI_HOLE_YF + 58.0     # 41.5
SO_H, SO_D, SO_PILOT, SO_PILOT_D = 5.0, 6.0, 2.2, 6.0
IO_W, IO_Z0, IO_Z1 = 58.0, 8.0, 27.0

# Pi power slot (left wall, beside the Pi's USB-C @ y ~ -8.8)
PWR_CY, PWR_L, PWR_Z0, PWR_Z1 = -8.8, 16.0, 6.0, 16.0

# ---------------- ESP32-S3 DevKitC ----------------
ESP_YF, ESP_W = -57.5, 28.0        # Y -57.5..-29.5
RAIL_H = 5.0
RAIL_X0, RAIL_X1 = -38.0, 18.0
ESP_CY = ESP_YF + ESP_W / 2        # -43.5
ANT_W, ANT_H, ANT_CX, ANT_CZ = 18.0, 14.0, 20.0, 12.0
SKIN = 1.0
USB_SLOT_L, USB_SLOT_H, USB_SLOT_Z0 = 22.0, 9.0, 5.0

# ---------------- front face ----------------
RADAR_W, RADAR_H, RADAR_CX, RADAR_CZ = 24.0, 17.0, -8.0, 32.0
MIC_D, MIC_CX, MIC_CZ = 2.5, -29.0, 32.0
MIC_REC_W, MIC_REC_H, MIC_REC_D = 14.0, 13.0, 1.5
FUNNEL_R1, FUNNEL_DEPTH = 3.0, 2.0          # waveguide taper Ø6 -> Ø2.5
DRAIN_D, DRAIN_X, DRAIN_Z = 2.0, -24.0, 4.0  # condensation drain

# ---------------- chimney (left-rear) ----------------
CH_Y0, CH_WALL = 30.0, 1.5
CH_XR = -28.0
CH_TOP = BODY_H - 2.5              # 43.5; lid plug drops 1.5 inside
GROMMET_D, GROMMET_Y, GROMMET_Z = 8.0, 45.0, 13.0
RIB_Y0, RIB_Y1, RIB_H = 36.0, 54.0, 4.0
RIB_X = [(-38.0, -37.0), (-34.8, -33.8)]
# chimney intake: floor slot; exhaust: rear wall slots
CH_FLOOR_SLOT = (-43.0, -31.0, 30.5, 32.5)          # x0,x1,y0,y1
CH_EXH_X0, CH_EXH_X1 = -43.0, -31.0
CH_EXH_Z = [(36.0, 37.5), (39.0, 40.5)]

# sensor-zone floor intakes (between ESP rail bands, clear of bosses)
FLOOR_SLOTS = [(-15.0, 3.0, -50.0, -48.0), (-15.0, 3.0, -44.0, -42.0)]

# ---------------- fasteners: 2 rear travel screws, M3x45 ----------------
POSTS = [(40.7, 61.35), (-40.7, 61.35)]
RIB_W = 1.5
POST_D, POST_TOP = 6.5, BODY_H - 10.0       # 36
BORE_D, CBORE_D, CBORE_DEPTH = 3.4, 6.8, 2.4
BOSS_DROP, PILOT_D = 10.0, 2.5

# ---------------- magnets: Ø6x3 N35, 6 pairs ----------------
MAG_D, MAG_H = 6.0, 3.0
MAG_POCKET_D = 6.3
MAG_BODY_DEPTH = 3.8               # magnet recessed 0.8 below boss top
MAG_LID_DEPTH = 2.2                # magnet glued proud 0.8 -> faces meet
# (cx, cy, boss footprint x0,x1,y0,y1) -- bosses on inner wall faces, z 40..46
MAGNETS = [
    ( 30.0, -63.0,  26.0,  34.0, -IN_Y - 1, -59.0),   # front pair
    (-30.0, -63.0, -34.0, -26.0, -IN_Y - 1, -59.0),
    ( 15.0,  63.0,  11.0,  19.0,  59.0,  IN_Y + 1),   # rear pair
    (-15.0,  63.0, -19.0, -11.0,  59.0,  IN_Y + 1),
    ( 41.0,  15.0,  37.0,  IN_X + 1, 11.0, 19.0),     # side pair
    (-41.0,  15.0, -IN_X - 1, -37.0, 11.0, 19.0),
]
MAG_BOSS_Z0 = BODY_H - 6.0         # 40..46

# ---------------- accessory boss grid ----------------
PAD_XY = [(31.0, -52.0), (41.0, -52.0), (31.0, -38.0), (41.0, -38.0)]
PAD_D, PAD_H, PAD_PILOT = 5.0, 4.0, 2.0

# ---------------- lid: lip, plug, pod, rails, LED ----------------
LIP_W, LIP_DROP, LIP_CLR = 1.8, 2.5, 0.25
PLUG_CLR, PLUG_DROP = 0.4, 4.0
POD_Y0, POD_Y1 = -22.0, 36.0       # low edge FRONT (faces bed)
POD_FRONT_H, POD_RISE, POD_WALL = 5.0, 20.0, 2.2
SCREEN_W, SCREEN_H = 58.6, 44.2
SRAIL_W, SRAIL_T, SRAIL_L = 3.0, 2.0, 54.0   # screen support rails
SRAIL_DROP = 15.0 + SRAIL_T / 2    # rail centre 16 below ceiling (normal)
LIGHT_D, LIGHT_X, LIGHT_Y = 6.0, -25.0, -45.0
LED_D, LED_X, LED_Y = 3.0, 0.0, -25.0        # recovery-glow LED
HOLE_LID_PILOT_TOP = 2.0


def try_fillet(wp, selector, r):
    try:
        return wp.edges(selector).fillet(r)
    except Exception as e:
        print(f'  fillet skipped ({selector}, r={r}): {type(e).__name__}')
        return wp


def box_at(w, d, h, x, y, z, centered=(False, False, False)):
    return (cq.Workplane("XY").box(w, d, h, centered=centered)
            .translate((x, y, z)))


def cone(r1, r2, h, pnt, direction):
    return cq.Workplane("XY").add(
        cq.Solid.makeCone(r1, r2, h, cq.Vector(*pnt), cq.Vector(*direction)))


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

# baffle
body = body.union(box_at(2 * IN_X, BAFFLE_T, BAFFLE_TOP - (FLOOR_Z + BAFFLE_GAP),
                         -IN_X, BAFFLE_Y, FLOOR_Z + BAFFLE_GAP))

# chimney walls
body = body.union(box_at(IN_X + CH_XR, CH_WALL, CH_TOP - FLOOR_Z,
                         -IN_X, CH_Y0 - CH_WALL, FLOOR_Z))
body = body.union(box_at(CH_WALL, IN_Y - (CH_Y0 - CH_WALL), CH_TOP - FLOOR_Z,
                         CH_XR - CH_WALL, CH_Y0 - CH_WALL, FLOOR_Z))
for x0, x1 in RIB_X:
    body = body.union(box_at(x1 - x0, RIB_Y1 - RIB_Y0, RIB_H,
                             x0, RIB_Y0, FLOOR_Z))
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

# accessory boss grid
for px, py in PAD_XY:
    body = body.union(cq.Workplane("XY", origin=(px, py, FLOOR_Z))
                      .circle(PAD_D / 2).extrude(PAD_H))
    body = body.cut(cq.Workplane("XY", origin=(px, py, FLOOR_Z + PAD_H - 3.0))
                    .circle(PAD_PILOT / 2).extrude(3.1))

# rear travel-screw posts with weld ribs
for px, py in POSTS:
    body = body.union(cq.Workplane("XY", origin=(px, py, FLOOR_Z))
                      .circle(POST_D / 2).extrude(POST_TOP - FLOOR_Z))
    sx = 1 if px > 0 else -1
    body = body.union(box_at(IN_X - abs(px) + 0.1, RIB_W, POST_TOP - FLOOR_Z,
                             px if sx > 0 else -IN_X - 0.1,
                             py - RIB_W / 2, FLOOR_Z))
    body = body.union(box_at(RIB_W, IN_Y - abs(py) + 0.1, POST_TOP - FLOOR_Z,
                             px - RIB_W / 2, py, FLOOR_Z))
    body = body.cut(cq.Workplane("XY", origin=(px, py, -1))
                    .circle(BORE_D / 2).extrude(POST_TOP + 1.5))
    body = body.cut(cq.Workplane("XY", origin=(px, py, -0.1))
                    .circle(CBORE_D / 2).extrude(CBORE_DEPTH + 0.1))

# magnet bosses (body side) with pockets
for cx, cy, bx0, bx1, by0, by1 in MAGNETS:
    body = body.union(box_at(bx1 - bx0, by1 - by0, BODY_H - MAG_BOSS_Z0,
                             bx0, by0, MAG_BOSS_Z0))
    body = body.cut(cq.Workplane("XY", origin=(cx, cy, BODY_H - MAG_BODY_DEPTH))
                    .circle(MAG_POCKET_D / 2).extrude(MAG_BODY_DEPTH + 0.1))

# ---- front face ----
body = body.cut(box_at(RADAR_W, WALL - SKIN + 1, RADAR_H,
                       RADAR_CX - RADAR_W / 2, -OUTER_L / 2 + SKIN,
                       RADAR_CZ - RADAR_H / 2))
body = body.cut(cq.Workplane("XZ", origin=(MIC_CX, -OUTER_L / 2 - 1, MIC_CZ))
                .circle(MIC_D / 2).extrude(-(WALL + 2)))
body = body.cut(cone(FUNNEL_R1, MIC_D / 2, FUNNEL_DEPTH,            # waveguide
                     (MIC_CX, -IN_Y, MIC_CZ), (0, -1, 0)))
body = body.cut(box_at(MIC_REC_W, MIC_REC_D + 1, MIC_REC_H,
                       MIC_CX - MIC_REC_W / 2, -IN_Y - MIC_REC_D,
                       MIC_CZ - MIC_REC_H / 2))
body = body.cut(box_at(ANT_W, WALL - SKIN + 1, ANT_H,
                       ANT_CX - ANT_W / 2, -OUTER_L / 2 + SKIN,
                       ANT_CZ - ANT_H / 2))
body = body.cut(cq.Workplane("XZ", origin=(DRAIN_X, -OUTER_L / 2 - 1, DRAIN_Z))
                .circle(DRAIN_D / 2).extrude(-(WALL + 2)))           # drain

# ---- left wall: ESP USB service slot + Pi power slot (only penetrations) ----
def left_cut(length, h, cy, cz):
    return box_at(WALL + 2, length, h,
                  -OUTER_W / 2 - 1, cy - length / 2, cz - h / 2)

body = body.cut(left_cut(USB_SLOT_L, USB_SLOT_H, ESP_CY,
                         USB_SLOT_Z0 + USB_SLOT_H / 2))
body = body.cut(left_cut(PWR_L, PWR_Z1 - PWR_Z0, PWR_CY,
                         (PWR_Z0 + PWR_Z1) / 2))

# ---- base intakes (hidden under foot gap) ----
for x0, x1, y0, y1 in FLOOR_SLOTS + [CH_FLOOR_SLOT]:
    body = body.cut(box_at(x1 - x0, y1 - y0, FLOOR_Z + 2, x0, y0, -1))

# ---- rear: Pi IO with chamfer + chimney exhaust slots ----
def rear_cut(w, z0, z1, cx=0.0):
    return box_at(w, WALL + 2, z1 - z0, cx - w / 2, OUTER_L / 2 - WALL - 1, z0)

body = body.cut(rear_cut(IO_W, IO_Z0, IO_Z1))
chamfer = (cq.Workplane("XY").box(IO_W, 3.0, 3.0, centered=(True, True, True))
           .rotate((0, 0, 0), (1, 0, 0), 45)
           .translate((0, OUTER_L / 2 - WALL / 2, IO_Z1)))
body = body.cut(chamfer)
for z0, z1 in CH_EXH_Z:
    body = body.cut(rear_cut(CH_EXH_X1 - CH_EXH_X0, z0, z1,
                             (CH_EXH_X0 + CH_EXH_X1) / 2))

# ============================================================ LID
lid = (cq.Workplane("XY")
       .box(OUTER_W, OUTER_L, LID_T, centered=(True, True, False))
       .edges("|Z").fillet(R_CORNER))

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

# screen support rails (module rests on these; tape is anti-rattle only)
n_y, n_z = -math.sin(theta), math.cos(theta)   # slope up-normal
mid_y = (POD_Y0 + POD_Y1) / 2
mid_zc = z_outer(mid_y) - dz                   # ceiling at mid-slope
for sx in (1, -1):
    lid = lid.union(
        cq.Workplane("XY")
        .box(SRAIL_W, SRAIL_L, SRAIL_T, centered=(True, True, True))
        .rotate((0, 0, 0), (1, 0, 0), tilt)
        .translate((sx * (IN_X + 1 - POD_WALL - SRAIL_W / 2),
                    mid_y - n_y * SRAIL_DROP,
                    mid_zc - n_z * SRAIL_DROP)))

# registration lip
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
for x0 in (39.5, -47.0):   # clear side lip beside the pod cavity
    lid = lid.cut(box_at(7.5, POD_Y1 - POD_Y0 + 1.0, LIP_DROP + 0.1,
                         x0, POD_Y0 - 0.5, -LIP_DROP - 0.05))
# clear lip at the six magnet boss positions
for cx, cy, bx0, bx1, by0, by1 in MAGNETS:
    lid = lid.cut(box_at(bx1 - bx0 + 1, by1 - by0 + 1, LIP_DROP + 0.1,
                         bx0 - 0.5, by0 - 0.5, -LIP_DROP - 0.05))

# chimney plug cap
plug = box_at((CH_XR - CH_WALL) - (-IN_X) - 2 * PLUG_CLR,
              IN_Y - PLUG_CLR - (CH_Y0 + PLUG_CLR), PLUG_DROP,
              -IN_X + PLUG_CLR, CH_Y0 + PLUG_CLR, -PLUG_DROP)
plug = plug.edges("|Z and <X and >Y").fillet(R_IN - PLUG_CLR)
lid = lid.union(plug)

# travel-screw bosses (rear pair only)
for px, py in POSTS:
    lid = lid.union(cq.Workplane("XY", origin=(px, py, -BOSS_DROP))
                    .circle(POST_D / 2).extrude(BOSS_DROP))
    lid = lid.cut(cq.Workplane("XY", origin=(px, py, -BOSS_DROP - 0.1))
                  .circle(PILOT_D / 2)
                  .extrude(BOSS_DROP + HOLE_LID_PILOT_TOP + 0.1))

# magnet pockets (lid side, magnets glued proud 0.8)
for cx, cy, *_ in MAGNETS:
    lid = lid.cut(cq.Workplane("XY", origin=(cx, cy, -0.1))
                  .circle(MAG_POCKET_D / 2).extrude(MAG_LID_DEPTH + 0.1))

# BH1750 light hole + 45deg countersink
lid = lid.cut(cq.Workplane("XY", origin=(LIGHT_X, LIGHT_Y, -0.5))
              .circle(LIGHT_D / 2).extrude(LID_T + 1))
lid = lid.cut(cone(LIGHT_D / 2 + 1.5, LIGHT_D / 2, 1.5,
                   (LIGHT_X, LIGHT_Y, LID_T), (0, 0, -1)))

# recovery-glow LED hole
lid = lid.cut(cq.Workplane("XY", origin=(LED_X, LED_Y, -0.5))
              .circle(LED_D / 2).extrude(LID_T + 1))

# ============================================================ EXPORT + CHECKS
import os
os.makedirs("/home/claude/out", exist_ok=True)
for part, name in [(body, 'body'), (lid, 'lid')]:
    cq.exporters.export(part, f"/home/claude/out/basecamp_{name}_v4.step")
    cq.exporters.export(part, f"/home/claude/out/basecamp_{name}_v4.stl")

print(f"exported v4  |  body {OUTER_W:.0f} x {OUTER_L:.0f} x {BODY_H:.0f}, "
      f"assembled {BODY_H+LID_T:.0f}, pod peak {BODY_H+LID_T+POD_FRONT_H+POD_RISE:.0f}")
print(f"Pi: PCB Y {IN_Y-85:.1f}..{IN_Y:.1f}, power slot left wall y "
      f"{PWR_CY-PWR_L/2:.1f}..{PWR_CY+PWR_L/2:.1f} z {PWR_Z0}-{PWR_Z1}")
print(f"pod slant {(POD_Y1-POD_Y0)/math.cos(theta):.1f} (module 50), tilt {tilt:.1f} deg, "
      f"rail seat {SRAIL_DROP-SRAIL_T/2:.1f} below ceiling (module 14.3 -> glass recess "
      f"{15.0-14.3:.1f})")
print(f"chimney walls to {CH_TOP}, plug to {BODY_H-PLUG_DROP}, exhaust rear z {CH_EXH_Z}")
print(f"posts (travel, rear only): top {POST_TOP}, M3x45 tip z {CBORE_DEPTH+45:.1f}, "
      f"pilot ends z {BODY_H+HOLE_LID_PILOT_TOP}")
print(f"magnets: 6x O{MAG_D:.0f}x{MAG_H:.0f}, body recess 0.8 / lid proud 0.8 -> contact")
