"""Build ../geo.json (simplified, projected SVG paths) from Census 2023 cartographic boundary files.

  curl -LO https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_34_sldu_500k.zip   # NJ legislative districts
  curl -LO https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_5m.zip    # counties
  unzip cb_2023_34_sldu_500k.zip && unzip cb_2023_us_county_5m.zip && python3 build_geo.py
"""
import shapefile, json, math
def dp(pts, eps):
    if len(pts) < 3: return pts
    a, b = pts[0], pts[-1]
    dx, dy = b[0]-a[0], b[1]-a[1]; L = math.hypot(dx, dy) or 1e-12
    dmax, idx = 0, 0
    for i in range(1, len(pts)-1):
        d = abs(dy*(pts[i][0]-a[0]) - dx*(pts[i][1]-a[1]))/L
        if d > dmax: dmax, idx = d, i
    if dmax > eps:
        return dp(pts[:idx+1], eps)[:-1] + dp(pts[idx:], eps)
    return [a, b]
LAT0 = 40.1; K = math.cos(math.radians(LAT0))
X0, Y0, S = -75.6, 41.36, 600  # px per degree lat
def proj(lon, lat): return ((lon-X0)*K*S, (Y0-lat)*S)
def path(shape, eps=0.6, minarea=4):
    parts = list(shape.parts)+[len(shape.points)]
    out = []
    for i in range(len(parts)-1):
        ring = [proj(*p) for p in shape.points[parts[i]:parts[i+1]]]
        area = abs(sum(ring[j][0]*ring[j-1][1]-ring[j-1][0]*ring[j][1] for j in range(len(ring))))/2
        if area < minarea: continue
        k = max(range(len(ring)), key=lambda j: (ring[j][0]-ring[0][0])**2+(ring[j][1]-ring[0][1])**2)
        r = dp(ring[:k+1], eps)[:-1] + dp(ring[k:], eps)
        if len(r) < 4: continue
        out.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in r) + "Z")
    return "".join(out)
def centroid(shape):
    # label point: centroid of largest ring
    parts = list(shape.parts)+[len(shape.points)]
    best = None
    for i in range(len(parts)-1):
        ring = [proj(*p) for p in shape.points[parts[i]:parts[i+1]]]
        A = cx = cy = 0
        for j in range(len(ring)):
            x0,y0 = ring[j-1]; x1,y1 = ring[j]; c = x0*y1-x1*y0
            A += c; cx += (x0+x1)*c; cy += (y0+y1)*c
        if A and (best is None or abs(A) > abs(best[0])): best = (A, cx/(3*A), cy/(3*A))
    return [round(best[1],1), round(best[2],1)]
ld = shapefile.Reader("cb_2023_34_sldu_500k")
lds = []
for sr in ld.iterShapeRecords():
    r = sr.record.as_dict()
    n = int(r["SLDUST"])
    lds.append({"id": n, "d": path(sr.shape), "c": centroid(sr.shape)})
lds.sort(key=lambda x: x["id"])
co = shapefile.Reader("cb_2023_us_county_5m")
cos_ = []
for sr in co.iterShapeRecords():
    r = sr.record.as_dict()
    if r["STATEFP"] != "34": continue
    cos_.append({"id": r["NAME"], "d": path(sr.shape, 0.5), "c": centroid(sr.shape)})
cos_.sort(key=lambda x: x["id"])
allx = []; 
import re
for f in lds+cos_:
    for m in re.finditer(r"(-?[\d.]+),(-?[\d.]+)", f["d"]): allx.append((float(m.group(1)), float(m.group(2))))
print(len(lds), len(cos_), min(p[0] for p in allx), max(p[0] for p in allx), min(p[1] for p in allx), max(p[1] for p in allx))
json.dump({"lds": lds, "counties": cos_}, open("../geo.json","w"), separators=(",",":"))
