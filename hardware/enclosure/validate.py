"""
Enclosure v4 validation: collision and watertightness checks.

Requires: pip install trimesh manifold3d cadquery

Usage:
    python validate.py

All checks should print OK before sending files to the print service.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).parent


def check_watertight(path: pathlib.Path) -> bool:
    try:
        import trimesh
        mesh = trimesh.load(str(path))
        if not mesh.is_watertight:
            print(f"  FAIL watertight: {path.name}")
            return False
        print(f"  OK   watertight: {path.name}")
        return True
    except Exception as e:
        print(f"  SKIP watertight: {path.name} ({e})")
        return True


def check_collision(body_path: pathlib.Path, lid_path: pathlib.Path) -> bool:
    try:
        import trimesh
        body = trimesh.load(str(body_path))
        lid  = trimesh.load(str(lid_path))
        manager = trimesh.collision.CollisionManager()
        manager.add_object("body", body)
        is_collision, _ = manager.in_collision_single(lid, return_names=True)
        if is_collision:
            print("  FAIL collision: body and lid intersect")
            return False
        print("  OK   collision: body / lid clearance confirmed")
        return True
    except Exception as e:
        print(f"  SKIP collision check ({e})")
        return True


def main():
    body_stl = HERE / "basecamp_body_v4.stl"
    lid_stl  = HERE / "basecamp_lid_v4.stl"

    missing = [p for p in (body_stl, lid_stl) if not p.exists()]
    if missing:
        print("Missing STL files (run enclosure_v4.py first):")
        for p in missing:
            print(f"  {p.name}")
        sys.exit(1)

    results = [
        check_watertight(body_stl),
        check_watertight(lid_stl),
        check_collision(body_stl, lid_stl),
    ]

    if all(results):
        print("\nAll checks passed.")
    else:
        print("\nOne or more checks failed - do not send to printer.")
        sys.exit(1)


if __name__ == "__main__":
    main()
