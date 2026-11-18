#!/usr/bin/env python3
"""Compare two cuff meshes as geometry (not bytes): volume, bounding box and surface deviation.

    python cad/compare.py built.stl reference.stl [--samples 20000]

The deviation is two-sided: points sampled on each surface, distance to the closest point of the other
surface; it reports the maximum (a sampled Hausdorff distance) and the 99th percentile. Useful because
web/grade/*.stl are refined (subdivided) copies of the CAD meshes, so their bytes never match.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import trimesh


def compare(a_path, b_path, samples=20000, seed=0):
    a, b = trimesh.load(a_path, force='mesh'), trimesh.load(b_path, force='mesh')
    rng = np.random.default_rng(seed)

    def one_way(src, dst):
        pts, _ = trimesh.sample.sample_surface(src, samples, seed=int(rng.integers(1 << 31)))
        _, dist, _ = trimesh.proximity.closest_point(dst, pts)
        return dist

    d_ab, d_ba = one_way(a, b), one_way(b, a)
    d = np.concatenate([d_ab, d_ba])
    return dict(
        a=str(a_path), b=str(b_path),
        identical_bytes=hashlib.sha256(Path(a_path).read_bytes()).digest() == hashlib.sha256(Path(b_path).read_bytes()).digest(),
        faces=[len(a.faces), len(b.faces)],
        watertight=[bool(a.is_watertight), bool(b.is_watertight)],
        volume_mm3=[round(float(a.volume), 3), round(float(b.volume), 3)],
        volume_diff_mm3=round(float(a.volume - b.volume), 4),
        bbox_min_diff_mm=np.round(a.bounds[0] - b.bounds[0], 5).tolist(),
        bbox_max_diff_mm=np.round(a.bounds[1] - b.bounds[1], 5).tolist(),
        extents_mm=[np.round(a.extents, 3).tolist(), np.round(b.extents, 3).tolist()],
        deviation_max_mm=round(float(d.max()), 7),
        deviation_p99_mm=round(float(np.percentile(d, 99)), 7),
        deviation_mean_mm=round(float(d.mean()), 8),
        samples_per_side=samples,
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('a', type=Path)
    ap.add_argument('b', type=Path)
    ap.add_argument('--samples', type=int, default=20000)
    args = ap.parse_args(argv)
    r = compare(args.a, args.b, args.samples)
    print(json.dumps(r, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
