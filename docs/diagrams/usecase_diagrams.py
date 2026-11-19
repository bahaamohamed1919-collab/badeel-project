"""Draws the two UML diagrams for Chapter 1, section 4:

  use_case_diagram.png    actors and use cases of Badeel
  misuse_case_diagram.png attacker, misuse cases, and the security use cases
                          that mitigate them (Sindre & Opdahl notation)

    python docs/diagrams/usecase_diagrams.py
"""
import math
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                                     # noqa: E402
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, Rectangle  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
INK = "#1b2540"
SEC = "#0b7a56"
RED = "#a8322a"
EW, EH = 2.9, 0.82           # ellipse width / height

plt.rcParams["font.family"] = "DejaVu Sans"


def canvas(w, h):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def actor(ax, x, y, name, dark=False):
    color = "black" if dark else INK
    ax.add_patch(Circle((x, y + 0.55), 0.2, fill=dark, facecolor=color, edgecolor=color, lw=1.6))
    ax.plot([x, x], [y + 0.35, y - 0.15], color=color, lw=1.6)
    ax.plot([x - 0.32, x + 0.32], [y + 0.18, y + 0.18], color=color, lw=1.6)
    ax.plot([x, x - 0.28], [y - 0.15, y - 0.55], color=color, lw=1.6)
    ax.plot([x, x + 0.28], [y - 0.15, y - 0.55], color=color, lw=1.6)
    ax.text(x, y - 0.78, name, ha="center", va="top", fontsize=10, fontweight="bold", color=color)
    return {"x": x, "y": y}


def usecase(ax, x, y, text, kind="normal", w=EW, h=EH):
    face, edge, tc = {"normal": ("white", INK, INK), "misuse": ("black", "black", "white"),
                      "security": ("#e2f3eb", SEC, "#08583e")}[kind]
    ax.add_patch(Ellipse((x, y), w, h, facecolor=face, edgecolor=edge, lw=1.4, zorder=3))
    ax.text(x, y, text, ha="center", va="center", fontsize=8.6, color=tc, zorder=4,
            linespacing=1.15)
    return {"x": x, "y": y, "w": w, "h": h}


def edge_point(e, tx, ty):
    """Point on an ellipse boundary in the direction of (tx, ty)."""
    dx, dy = tx - e["x"], ty - e["y"]
    if dx == 0 and dy == 0:
        return e["x"], e["y"]
    a, b = e["w"] / 2, e["h"] / 2
    t = 1 / math.sqrt((dx / a) ** 2 + (dy / b) ** 2)
    return e["x"] + dx * t, e["y"] + dy * t


def link(ax, a, uc, color=INK):
    x0, y0 = a["x"] + (0.35 if uc["x"] > a["x"] else -0.35), a["y"] + 0.15
    x1, y1 = edge_point(uc, x0, y0)
    ax.plot([x0, x1], [y0, y1], color=color, lw=1.0, zorder=2)


def relation(ax, src, dst, label, color, label_pos=0.5, offset=(0, 0.12)):
    x0, y0 = edge_point(src, dst["x"], dst["y"])
    x1, y1 = edge_point(dst, src["x"], src["y"])
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=11,
                                 color=color, lw=1.1, linestyle=(0, (4, 3)), zorder=2))
    lx, ly = x0 + (x1 - x0) * label_pos + offset[0], y0 + (y1 - y0) * label_pos + offset[1]
    ax.text(lx, ly, label, ha="center", va="bottom", fontsize=7.4, color=color, style="italic",
            zorder=5, bbox=dict(facecolor="white", edgecolor="none", pad=0.6, alpha=0.9))


def generalize(ax, child, parent):
    ax.add_patch(FancyArrowPatch((child["x"], child["y"] + 0.78), (parent["x"], parent["y"] - 1.05),
                                 arrowstyle="-|>", mutation_scale=16, color=INK, lw=1.1,
                                 facecolor="white", zorder=2))


def boundary(ax, x0, y0, x1, y1, title):
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor=INK, lw=1.4))
    ax.text(x0 + 0.2, y1 - 0.15, title, ha="left", va="top", fontsize=11, fontweight="bold",
            color=INK)


# ----------------------------------------------------------- use case diagram
def use_case_diagram():
    # Layout rule: from each actor, lines to the second column pass through the
    # gaps of the first column, so no line crosses a use case.
    fig, ax = canvas(15.8, 12.6)
    ax.add_patch(Rectangle((2.9, 0.25), 15.2 - 2.9, 11.95 - 0.25, fill=False, edgecolor=INK,
                           lw=1.4))
    ax.text(2.9, 12.1, "Badeel - Medication Alternative Recommendation System", ha="left",
            va="bottom", fontsize=11, fontweight="bold", color=INK)
    visitor = actor(ax, 1.3, 10.0, "Visitor")
    patient = actor(ax, 1.3, 6.6, "Patient")
    pharm = actor(ax, 1.3, 4.3, "Pharmacist")
    admin = actor(ax, 1.3, 1.9, "Admin")
    for child, parent in ((patient, visitor), (pharm, patient), (admin, pharm)):
        ax.add_patch(FancyArrowPatch((child["x"], child["y"] + 0.78),
                                     (parent["x"], parent["y"] - 1.2), arrowstyle="-|>",
                                     mutation_scale=16, edgecolor=INK, facecolor="white", lw=1.1))
    c1, c2, c3 = 5.6, 9.4, 13.2
    v = [usecase(ax, c1, 11.35, "Search drug by name\n(typo-tolerant, AR/EN)"),
         usecase(ax, c1, 10.15, "Log in"),
         usecase(ax, c1, 8.95, "Register account"),
         usecase(ax, c2, 11.11, "View drug and its\nalternatives (3 levels)"),
         usecase(ax, c2, 9.19, "Switch language")]
    for uc in v:
        link(ax, visitor, uc)
    warn = usecase(ax, c3, 11.11, "Show allergy warning")
    relation(ax, warn, v[3], "«extend»", INK, offset=(0, 0.08))

    p = [usecase(ax, c1, 7.95, "Manage allergies\n(explicit consent)"),
         usecase(ax, c1, 6.75, "Change password"),
         usecase(ax, c1, 5.55, "View / clear\nsearch history"),
         usecase(ax, c2, 7.71, "Save medicines")]
    for uc in p:
        link(ax, patient, uc)

    ph = [usecase(ax, c3, 4.75, "Update availability\nand price"),
          usecase(ax, c3, 3.75, "View shortage list")]
    for uc in ph:
        link(ax, pharm, uc)

    ad = [usecase(ax, c1, 3.25, "Add / edit / delete drugs"),
          usecase(ax, c1, 2.05, "Import drugs from CSV"),
          usecase(ax, c1, 0.85, "View security log\nand change log"),
          usecase(ax, c2, 3.01, "Approve pharmacists,\nmanage users"),
          usecase(ax, c2, 1.09, "Train search model")]
    for uc in ad:
        link(ax, admin, uc)
    note = ("Generalization arrows: each role can also do\neverything the role above it can.\n"
            "A pharmacist account is active only\nafter an admin approves it.")
    ax.text(c3, 7.2, note, ha="center", va="center", fontsize=7.8, color="#566076",
            bbox=dict(facecolor="#f4f6f9", edgecolor="#d5dbe5", pad=6))
    fig.savefig(os.path.join(OUT, "use_case_diagram.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


# --------------------------------------------------------- misuse case diagram
def misuse_case_diagram():
    fig, ax = canvas(18.5, 12.2)
    boundary(ax, 2.6, 0.4, 12.2, 11.9, "Badeel")
    patient = actor(ax, 1.2, 7.9, "Patient")
    pharm = actor(ax, 1.2, 3.6, "Pharmacist")
    admin = actor(ax, 1.2, 1.2, "Admin")
    attacker = actor(ax, 17.6, 5.9, "Attacker", dark=True)

    rows = [10.0, 8.3, 6.6, 4.9, 3.2, 1.5]
    uc = [usecase(ax, 4.5, rows[0], "Log in"),
          usecase(ax, 4.5, rows[1], "Search drug"),
          usecase(ax, 4.5, rows[2], "Change profile\nor password"),
          usecase(ax, 4.5, rows[3], "Manage allergies"),
          usecase(ax, 4.5, rows[4], "Update availability\nand price"),
          usecase(ax, 4.5, rows[5], "Manage drugs\nand users")]
    sec = [usecase(ax, 9.6, rows[0] + 0.85, "Lock account after\n5 failed tries", "security"),
           usecase(ax, 9.6, rows[1] + 0.85, "Parameterized queries,\ninput validation", "security"),
           usecase(ax, 9.6, rows[2] + 0.85, "Check CSRF token", "security"),
           usecase(ax, 9.6, rows[3] + 0.85, "Hash passwords,\nencrypt health data", "security"),
           usecase(ax, 9.6, rows[4] + 0.85, "Admin approves\npharmacist accounts", "security"),
           usecase(ax, 9.6, rows[5] + 0.85, "Honeypot traps and\nlogs scanners", "security")]
    mis = [usecase(ax, 14.6, rows[0], "Guess passwords\n(brute force)", "misuse"),
           usecase(ax, 14.6, rows[1], "Inject SQL", "misuse"),
           usecase(ax, 14.6, rows[2], "Forge a request\n(CSRF)", "misuse"),
           usecase(ax, 14.6, rows[3], "Steal the\ndatabase file", "misuse"),
           usecase(ax, 14.6, rows[4], "Register as a\nfake pharmacist", "misuse"),
           usecase(ax, 14.6, rows[5], "Scan for admin\npages", "misuse")]
    for i in range(4):
        link(ax, patient, uc[i])
    link(ax, pharm, uc[4])
    link(ax, admin, uc[5])
    for m in mis:
        link(ax, attacker, m, color="black")
    for u, s, m in zip(uc, sec, mis):
        relation(ax, m, u, "«threatens»", RED, label_pos=0.62, offset=(0, 0.04))
        relation(ax, s, m, "«mitigates»", SEC, label_pos=0.5, offset=(0.15, 0.05))
        relation(ax, u, s, "«include»", INK, label_pos=0.45, offset=(-0.1, 0.06))
    fig.savefig(os.path.join(OUT, "misuse_case_diagram.png"), bbox_inches="tight",
                facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    use_case_diagram()
    misuse_case_diagram()
    print("saved use_case_diagram.png and misuse_case_diagram.png")
