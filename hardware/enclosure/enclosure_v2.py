"""
Basecamp enclosure v2 — Apple-style parametric CAD generator.
Body + lid STEP/STL for Taobao 3D printing.

v2 changes:
  - R8 rounded vertical corners, softened edges (Apple-like)
  - Radar hidden behind 1mm membrane (clean front face, LD2410 penetrates 1mm PLA)
  - ESP32 node integration: antenna window (front) + USB-C service slot (left wall)
    so the integrated node can be flashed/provisioned without opening the box
  - Screen pod widened to fit REAL module: 86x50mm PCB (verified), not active area
  - Chimney moved to right wall, enlarged, self-capped (sealed from pod cavity)
  - Verified dims: ESP32-S3-DevKitC-1 ~70x28, ILI9341 module 86x50x14.3,
    Pi4 holes 58x49, RJ45 ~13.5 / USB-A stack ~15.6 above PCB
"""
import math
import cadquery as cq

# ---------------- master ----------------
OUTER_L, OUTER_W, OUTER_H = 150.0, 100.0, 70.0
WALL, LID_T = 3.0, 3.0
R_CORNER = 8.0            # Apple-style vertical corner radius
R_EDGE = 1.5              # soft horizontal edges

IN_XMAX = OUTER_W/2 - WALL            # 47
IN_YMIN, IN_YMAX = -OUTER_L/2+WALL, OUTER_L/2-WALL   # -72, 72
FLOOR_Z = WALL

# ---------------- zones ----------------
SENSOR_DEPTH, BAFFLE_T, BAFFLE_GAP = 40.0, 3.0, 5.0
BAFFLE_Y0 = IN_YMIN + SENSOR_DEPTH          # -32

# ---------------- Pi 4 (verified: holes 58x49, ports to ~25mm over floor) ----------------
PI_DX, PI_YR, PI_YF = 24.5, 67.5, 9.5
SO_H, SO_D, SO_HOLE, SO_HOLE_D = 5.0, 5.0, 2.2, 6.0
IO_W, IO_Z0, IO_Z1 = 60.0, 8.0, 27.0        # raised: USB-A stack 15.6 + PCB top 9.4

# ---------------- ESP32 (verified ~70x28, lies flat, antenna right) ----------------
ESP_L, ESP_W = 70.0, 28.0
ESP_X0 = -45.5                               # USB end 1.5mm from left inner wall
RAIL_H, RAIL_T = 5.0, 3.0
RAIL_X0, RAIL_X1 = -40.0, 20.0
RAIL1_Y, RAIL2_Y = (-69.0, -66.0), (-50.0, -47.0)
ANT_WIN_W, ANT_WIN_H = 18.0, 12.0            # antenna window, front face
ANT_WIN_CX, ANT_WIN_CZ = 16.0, 11.0
USB_SLOT_LEN, USB_SLOT_H = 22.0, 9.0         # left-wall service slot (2x USB-C)
USB_SLOT_CY, USB_SLOT_Z0 = -56.0, 5.0

# ---------------- front face ----------------
RADAR_W, RADAR_H, RADAR_CX, RADAR_CZ = 24.0, 16.0, -10.0, 35.0
RADAR_SKIN = 1.0                             # membrane left in 3mm wall
MIC_D, MIC_CX, MIC_CZ = 2.5, -35.0, 35.0

# ---------------- chimney (right wall + baffle, self-capped) ----------------
CHIM_X0, CHIM_X1 = 28.0, IN_XMAX
CHIM_Y0, CHIM_Y1 = -60.0, BAFFLE_Y0
CHIM_WALL, CHIM_CAP_Z = 1.5, 66.0
CVENT_LEN, CVENT_H, CVENT_CY = 16.0, 1.5, -46.0
CVENT_Z = [8.0, 12.0, 58.0, 62.0]            # low in, high out

# ---------------- left wall micro vents ----------------
LVENT_LEN, LVENT_H, LVENT_CY = 20.0, 1.5, -56.0
LVENT_Z = [40.0, 46.0, 52.0, 58.0]

# ---------------- rear ----------------
USBC_W, USBC_H, USBC_CX, USBC_Z0 = 12.0, 7.0, -38.0, 10.0
NODE2_W, NODE2_H, NODE2_CX, NODE2_Z0 = 12.0, 6.0, 38.0, 58.0

# ---------------- lid pod (sized for REAL 86x50x14.3 module) ----------------
POD_X0, POD_X1 = -46.0, 46.0                 # 92 wide
POD_Y0, POD_Y1 = -62.0, -7.0                 # 55 deep
POD_WALL = 2.2                               # inner 87.6 -> 1.6mm module clearance
POD_REAR_H, POD_RISE = 5.0, 20.0             # 20deg
SCREEN_W, SCREEN_H = 58.0, 44.0
POSTS = [(43.5, 68.5), (-43.5, 68.5), (43.5, -68.5), (-43.5, -68.5)]
HOLE_BODY, HOLE_LID, POST_R = 2.2, 2.8, 3.5

def try_fillet(wp, selector, r):
    try:
        return wp.edges(selector).fillet(r)
    except Exception as e:
        print(f'  fillet skipped ({selector}, r={r}): {type(e).__name__}')
        return wp

# ============================================================ BODY
body = (cq.Workplane("XY")
        .box(OUTER_W, OUTER_L, OUTER_H, centered=(True, True, False)))
body = body.edges("|Z").fillet(R_CORNER)
body = try_fillet(body, "<Z", R_EDGE)

cavity = (cq.Workplane("XY")
          .box(OUTER_W-2*WALL, OUTER_L-2*WALL, OUTER_H, centered=(True, True, False))
          .edges("|Z").fillet(R_CORNER-WALL)
          .translate((0, 0, FLOOR_Z)))
body = body.cut(cavity)

# baffle
body = body.union(
    cq.Workplane("XY").box(2*IN_XMAX, BAFFLE_T, OUTER_H-FLOOR_Z-BAFFLE_GAP,
                           centered=(True, False, False))
    .translate((0, BAFFLE_Y0, FLOOR_Z+BAFFLE_GAP)))

# chimney: front wall, left wall, cap (right=enclosure wall, rear=baffle)
body = body.union(
    cq.Workplane("XY").box(CHIM_X1-CHIM_X0, CHIM_WALL, CHIM_CAP_Z-FLOOR_Z,
                           centered=(False, False, False))
    .translate((CHIM_X0, CHIM_Y0, FLOOR_Z)))
body = body.union(
    cq.Workplane("XY").box(CHIM_WALL, CHIM_Y1-CHIM_Y0, CHIM_CAP_Z-FLOOR_Z,
                           centered=(False, False, False))
    .translate((CHIM_X0, CHIM_Y0, FLOOR_Z)))
body = body.union(
    cq.Workplane("XY").box(CHIM_X1-CHIM_X0, CHIM_Y1-CHIM_Y0+CHIM_WALL, 1.5,
                           centered=(False, False, False))
    .translate((CHIM_X0, CHIM_Y0, CHIM_CAP_Z)))

# ESP32 rails
for y0, y1 in (RAIL1_Y, RAIL2_Y):
    body = body.union(
        cq.Workplane("XY").box(RAIL_X1-RAIL_X0, y1-y0, RAIL_H,
                               centered=(False, False, False))
        .translate((RAIL_X0, y0, FLOOR_Z)))

# Pi standoffs + corner posts
for sx in (PI_DX, -PI_DX):
    for sy in (PI_YR, PI_YF):
        body = body.union(cq.Workplane("XY", origin=(sx, sy, FLOOR_Z))
                          .circle(SO_D/2).extrude(SO_H))
        body = body.cut(cq.Workplane("XY", origin=(sx, sy, FLOOR_Z+SO_H-SO_HOLE_D))
                        .circle(SO_HOLE/2).extrude(SO_HOLE_D+0.1))
for px, py in POSTS:
    body = body.union(cq.Workplane("XY", origin=(px, py, FLOOR_Z))
                      .circle(POST_R).extrude(OUTER_H-FLOOR_Z))
    body = body.cut(cq.Workplane("XY", origin=(px, py, OUTER_H-12))
                    .circle(HOLE_BODY/2).extrude(12.1))

# ---- front face: radar membrane pocket (from inside), mic, antenna window ----
body = body.cut(cq.Workplane("XY")
                .box(RADAR_W, WALL-RADAR_SKIN+1, RADAR_H, centered=(True, False, True))
                .translate((RADAR_CX, -OUTER_L/2+RADAR_SKIN, RADAR_CZ)))
body = body.cut(cq.Workplane("XZ", origin=(MIC_CX, -OUTER_L/2-1, MIC_CZ))
                .circle(MIC_D/2).extrude(-(WALL+2)))
body = body.cut(cq.Workplane("XY")
                .box(ANT_WIN_W, WALL+2, ANT_WIN_H, centered=(True, False, True))
                .translate((ANT_WIN_CX, -OUTER_L/2-1, ANT_WIN_CZ)))

# ---- left wall: ESP32 USB service slot + micro vents ----
def left_cut(length, h, cy, cz):
    return (cq.Workplane("XY").box(WALL+2, length, h, centered=(False, True, True))
            .translate((-OUTER_W/2-1, cy, cz)))
body = body.cut(left_cut(USB_SLOT_LEN, USB_SLOT_H, USB_SLOT_CY, USB_SLOT_Z0+USB_SLOT_H/2))
for z in LVENT_Z:
    body = body.cut(left_cut(LVENT_LEN, LVENT_H, LVENT_CY, z))

# ---- right wall: chimney vents ----
for z in CVENT_Z:
    body = body.cut(cq.Workplane("XY").box(WALL+2, CVENT_LEN, CVENT_H,
                                            centered=(False, True, True))
                    .translate((OUTER_W/2-WALL-1, CVENT_CY, z)))

# ---- rear ----
def rear_cut(w, z0, z1, cx=0.0):
    return (cq.Workplane("XY").box(w, WALL+2, z1-z0, centered=(True, False, False))
            .translate((cx, OUTER_L/2-WALL-1, z0)))
body = body.cut(rear_cut(IO_W, IO_Z0, IO_Z1))
body = body.cut(rear_cut(USBC_W, USBC_Z0, USBC_Z0+USBC_H, USBC_CX))
body = body.cut(rear_cut(NODE2_W, NODE2_Z0, NODE2_Z0+NODE2_H, NODE2_CX))

# ============================================================ LID
lid = (cq.Workplane("XY")
       .box(OUTER_W, OUTER_L, LID_T, centered=(True, True, False))
       .edges("|Z").fillet(R_CORNER))

pod = (cq.Workplane("YZ")
       .polyline([(POD_Y0, LID_T), (POD_Y1, LID_T),
                  (POD_Y1, LID_T+POD_REAR_H),
                  (POD_Y0, LID_T+POD_REAR_H+POD_RISE)])
       .close().extrude(POD_X1-POD_X0).translate((POD_X0, 0, 0)))
lid = lid.union(pod)
lid = try_fillet(lid, "|Z", 3.0)            # soften pod vertical edges

theta = math.atan2(POD_RISE, POD_Y1-POD_Y0)
dz = POD_WALL/math.cos(abs(theta))
lid = lid.cut(cq.Workplane("YZ")
              .polyline([(POD_Y0+POD_WALL, -1), (POD_Y1-POD_WALL, -1),
                         (POD_Y1-POD_WALL, LID_T+POD_REAR_H-dz),
                         (POD_Y0+POD_WALL, LID_T+POD_REAR_H+POD_RISE-dz)])
              .close().extrude(POD_X1-POD_X0-2*POD_WALL)
              .translate((POD_X0+POD_WALL, 0, 0)))

tilt = math.degrees(abs(theta))
lid = lid.cut(cq.Workplane("XY")
              .box(SCREEN_W, SCREEN_H, 24, centered=(True, True, True))
              .rotate((0, 0, 0), (1, 0, 0), -tilt)
              .translate(((POD_X0+POD_X1)/2, (POD_Y0+POD_Y1)/2,
                          LID_T+POD_REAR_H+POD_RISE/2)))
for px, py in POSTS:
    lid = lid.cut(cq.Workplane("XY", origin=(px, py, -0.5))
                  .circle(HOLE_LID/2).extrude(LID_T+POD_REAR_H+POD_RISE+2))

# ============================================================ EXPORT
for part, name in [(body, 'body'), (lid, 'lid')]:
    cq.exporters.export(part, f"/home/claude/out/basecamp_{name}_v2.step")
    cq.exporters.export(part, f"/home/claude/out/basecamp_{name}_v2.stl")
print("exported v2")
print(f"pod inner width: {POD_X1-POD_X0-2*POD_WALL:.1f} (module 86.0 -> {POD_X1-POD_X0-2*POD_WALL-86:.1f} clearance)")
print(f"pod slant length: {(POD_Y1-POD_Y0)/math.cos(abs(theta)):.1f} (module 50.0)")
print(f"tilt: {tilt:.1f} deg")
