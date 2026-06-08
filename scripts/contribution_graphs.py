import json
import math
import os
import urllib.request

API = "https://api.github.com/graphql"

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays {
            contributionLevel
            weekday
          }
        }
      }
    }
  }
}
"""

LEVEL_INDEX = {
    "NONE": 0,
    "FIRST_QUARTILE": 1,
    "SECOND_QUARTILE": 2,
    "THIRD_QUARTILE": 3,
    "FOURTH_QUARTILE": 4,
}

MOL_THEMES = {
    "light": {"empty": "#d0d7de", "bond": "#9aa7b0", "atoms": ["#95d5b2", "#52b788", "#0096c7", "#023e8a"]},
    "dark": {"empty": "#21262d", "bond": "#4b5963", "atoms": ["#74c69d", "#40916c", "#0096c7", "#0353a4"]},
}

TS_THEMES = {
    "light": {"axis": "#d0d7de", "area": "#52b788", "area_op": "0.22", "line": "#2d6a4f", "trend": "#0096c7"},
    "dark": {"axis": "#30363d", "area": "#52b788", "area_op": "0.18", "line": "#74c69d", "trend": "#48cae4"},
}

CELL = 11
GAP = 3
PITCH = CELL + GAP
PAD = 14


def fetch_weeks(login, token):
    body = json.dumps({"query": QUERY, "variables": {"login": login}}).encode()
    req = urllib.request.Request(API, data=body)
    req.add_header("Authorization", "bearer " + token)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    return cal["weeks"]


def to_grid(weeks):
    grid = {}
    for w, week in enumerate(weeks):
        for day in week["contributionDays"]:
            grid[(w, day["weekday"])] = LEVEL_INDEX.get(day["contributionLevel"], 0)
    return grid, len(weeks)


def cx(w):
    return PAD + w * PITCH + CELL / 2.0


def cy(d):
    return PAD + d * PITCH + CELL / 2.0


def dist(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def prim_mst(points):
    if len(points) < 2:
        return []
    in_tree = [0]
    rest = list(range(1, len(points)))
    edges = []
    while rest:
        best = None
        for i in in_tree:
            for ri, j in enumerate(rest):
                d = dist(points[i], points[j])
                if best is None or d < best[2]:
                    best = (i, ri, d)
        i, ri, _ = best
        j = rest[ri]
        edges.append((i, j))
        in_tree.append(j)
        rest.pop(ri)
    return edges


def build_molecule(weeks, theme):
    colors = MOL_THEMES[theme]
    grid, cols = to_grid(weeks)
    width = PAD * 2 + cols * PITCH - GAP
    height = PAD * 2 + 7 * PITCH - GAP

    points = []
    empties = []
    for w in range(cols):
        for d in range(7):
            level = grid.get((w, d), 0)
            if level == 0:
                empties.append('<circle cx="%.1f" cy="%.1f" r="1.4" fill="%s"/>' % (cx(w), cy(d), colors["empty"]))
            else:
                points.append({"w": w, "d": d, "x": cx(w), "y": cy(d), "lvl": level})

    edges = prim_mst(points)
    bonds = []
    for idx, (i, j) in enumerate(edges):
        p, q = points[i], points[j]
        length = round(dist(p, q), 1)
        delay = round(0.3 + idx * 0.04, 3)
        bonds.append(
            '<line class="bond" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" '
            'stroke-width="1.4" stroke-dasharray="%s" stroke-dashoffset="%s" style="animation-delay:%ss"/>'
            % (p["x"], p["y"], q["x"], q["y"], colors["bond"], length, length, delay)
        )

    atoms = []
    for pt in points:
        radius = 3.4 + pt["lvl"] * 0.6
        delay = round(pt["w"] * 0.02, 3)
        atoms.append(
            '<circle class="atom" cx="%.1f" cy="%.1f" r="%.1f" fill="%s" style="animation-delay:%ss"/>'
            % (pt["x"], pt["y"], radius, colors["atoms"][pt["lvl"] - 1], delay)
        )

    style = (
        "<style>"
        "@keyframes pop{0%{transform:scale(0);opacity:0}70%{transform:scale(1.25);opacity:1}100%{transform:scale(1)}}"
        "@keyframes draw{to{stroke-dashoffset:0}}"
        ".atom{transform-box:fill-box;transform-origin:center;animation:pop .45s ease-out both}"
        ".bond{animation:draw .4s ease-out both}"
        "</style>"
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img">'
        "<title>Contribution molecule, minimum spanning tree</title>%s%s%s%s</svg>"
        % (width, height, width, height, style, "".join(empties), "".join(bonds), "".join(atoms))
    )


def build_timeseries(weeks, theme):
    colors = TS_THEMES[theme]
    grid, cols = to_grid(weeks)
    totals = [sum(grid.get((w, d), 0) for d in range(7)) for w in range(cols)]
    max_v = max(totals + [1])

    width = PAD * 2 + cols * PITCH - GAP
    top, height = 16, 150
    base = height - 22

    def gx(w):
        return PAD + w * ((width - PAD * 2) / (cols - 1))

    def gy(v):
        return base - (v / max_v) * (base - top)

    line = "M" + " L ".join("%.1f %.1f" % (gx(w), gy(v)) for w, v in enumerate(totals))
    area = (
        "M%.1f %d L " % (gx(0), base)
        + " L ".join("%.1f %.1f" % (gx(w), gy(v)) for w, v in enumerate(totals))
        + " L %.1f %d Z" % (gx(cols - 1), base)
    )
    trend_vals = []
    for i in range(cols):
        chunk = [totals[k] for k in range(i - 2, i + 3) if 0 <= k < cols]
        trend_vals.append(sum(chunk) / len(chunk))
    trend = "M" + " L ".join("%.1f %.1f" % (gx(w), gy(v)) for w, v in enumerate(trend_vals))

    ticks = "".join(
        '<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="%s" stroke-width="0.5"/>'
        % (gx(m), base, gx(m), base + 4, colors["axis"])
        for m in range(0, cols, 4)
    )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img">'
        "<title>Weekly contribution time series</title>"
        '<defs><clipPath id="rev"><rect x="0" y="0" width="0" height="%d">'
        '<animate attributeName="width" from="0" to="%d" dur="1.4s" fill="freeze"/></rect></clipPath></defs>'
        '<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="0.5"/>%s'
        '<g clip-path="url(#rev)">'
        '<path d="%s" fill="%s" fill-opacity="%s"/>'
        '<path d="%s" fill="none" stroke="%s" stroke-width="1.8"/>'
        '<path d="%s" fill="none" stroke="%s" stroke-width="1.8" stroke-dasharray="6 4"/>'
        "</g></svg>"
        % (
            width, height, width, height,
            height, width,
            PAD, base, width - PAD, base, colors["axis"], ticks,
            area, colors["area"], colors["area_op"],
            line, colors["line"],
            trend, colors["trend"],
        )
    )


def main():
    login = os.environ["GH_LOGIN"]
    token = os.environ["GH_TOKEN"]
    weeks = fetch_weeks(login, token)
    files = (
        ("molecule-graph.svg", build_molecule(weeks, "light")),
        ("molecule-graph-dark.svg", build_molecule(weeks, "dark")),
        ("timeseries-graph.svg", build_timeseries(weeks, "light")),
        ("timeseries-graph-dark.svg", build_timeseries(weeks, "dark")),
    )
    for name, svg in files:
        with open(name, "w") as f:
            f.write(svg)
    print("Generated " + ", ".join(name for name, _ in files))


if __name__ == "__main__":
    main()
  

if __name__ == "__main__":
    main()
  
