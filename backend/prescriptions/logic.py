"""
Prescription Analyzer (Phase 3): schedule and safety checks built ONLY from what is written.

- Written times are used as written: "1-0-1" -> Morning + Night; "at bedtime" -> Night.
- If only an abbreviation is written (BD/TDS/QID), its standard meaning is shown as *typical* timing, labelled
  "confirm with your doctor or pharmacist". If no frequency is written at all, nothing is guessed.
- Safety checks report what is missing, unreadable, duplicated, or matches an allergy the user entered.
  They never suggest changing, stopping or substituting a medicine.
"""

from __future__ import annotations

import re

SLOTS = ("Morning", "Afternoon", "Evening", "Night")

DISCLAIMER = (
    "This is an informational reading of your prescription, not medical advice. Your pharmacist or the "
    "prescribing doctor must confirm anything unclear. Never change, stop or substitute a medicine on your own."
)

_TIMES_PER_DAY = [
    (re.compile(r"\b(od|once\s*(a|per)?\s*day|once\s*daily|daily|qd)\b", re.I), 1),
    (re.compile(r"\b(bd|bid|twice\s*(a|per)?\s*day|twice\s*daily|2\s*times)\b", re.I), 2),
    (re.compile(r"\b(tds|tid|thrice|three\s*times|3\s*times)\b", re.I), 3),
    (re.compile(r"\b(qid|qds|four\s*times|4\s*times)\b", re.I), 4),
]
_TYPICAL = {2: ("Morning", "Night"), 3: ("Morning", "Afternoon", "Night"), 4: ("Morning", "Afternoon", "Evening", "Night")}
_AS_NEEDED = re.compile(r"\b(sos|prn|as\s*needed|when\s*required|if\s*needed)\b", re.I)
_DASH = re.compile(r"(?<!\d)([0-9½]+)\s*-\s*([0-9½]+)\s*-\s*([0-9½]+)(?:\s*-\s*([0-9½]+))?(?!\d)")


def schedule_for(med) -> dict:
    """{'slots': [...], 'note': str}: slots are filled only from explicit written instructions."""
    freq = (med.frequency or "").strip()
    timing = " ".join(x for x in (med.timing, med.food_instructions) if x).strip()
    text = f"{freq} {timing}"
    m = _DASH.search(freq)
    if m:  # 1-0-1 (morning-afternoon-night) or 1-1-1-1 (morning-afternoon-evening-night)
        parts = [p for p in m.groups() if p is not None]
        names = ("Morning", "Afternoon", "Night") if len(parts) == 3 else SLOTS
        slots = [n for n, p in zip(names, parts) if p not in ("0", "")]
        return {"slots": slots, "note": f"As written: {m.group(0).replace(' ', '')}"}
    if _AS_NEEDED.search(text):
        return {"slots": [], "note": "Only when needed (as written)"}
    if re.search(r"\b(bed\s*time|hs|at\s*night|night)\b", text, re.I) and not re.search(r"\b(bd|tds|tid|twice|thrice)\b", freq, re.I):
        return {"slots": ["Night"], "note": "At bedtime / night (as written)"}
    if re.search(r"\bmorning\b", text, re.I) and not re.search(r"\b(bd|tds|tid|twice|thrice)\b", freq, re.I):
        return {"slots": ["Morning"], "note": "In the morning (as written)"}
    for rx, n in _TIMES_PER_DAY:
        if rx.search(freq):
            # Times are not written: show the standard meaning of the abbreviation as *typical* timing, clearly
            # labelled, never as the doctor's instruction. Once-daily timing depends on the medicine, so no slot.
            if n == 1:
                return {"slots": [], "suggested": [], "note": "Once a day; take it at the same time each day. Exact time not "
                        "written: ask your doctor or pharmacist which time suits this medicine"}
            return {"slots": [], "suggested": list(_TYPICAL[n]), "note": f"{n} times a day; times not written. Shown with the "
                    "typical timing for this abbreviation: confirm with your doctor or pharmacist"}
    if freq:
        return {"slots": [], "note": f"As written: \"{freq}\" (please confirm)"}
    return {"slots": [], "note": "Frequency not written: confirm with your doctor or pharmacist"}


def _label(med) -> str:
    return " ".join(x for x in (med.generic_name or med.name_as_written, med.strength) if x).strip() or "(unreadable medicine)"


def build_schedule(meds) -> dict:
    rows, unscheduled = [], []
    for med in meds:
        s = schedule_for(med)
        instr = ", ".join(x for x in (med.dose, med.timing or med.food_instructions, med.duration and f"for {med.duration}") if x)
        if s["slots"]:
            rows.extend({"time": slot, "medicine": _label(med), "instructions": instr or "-", "line": med.line_number,
                         "confirmed": med.user_confirmed, "suggested": False} for slot in s["slots"])
        elif s.get("suggested"):
            rows.extend({"time": slot, "medicine": _label(med), "instructions": instr or "-", "line": med.line_number,
                         "confirmed": med.user_confirmed, "suggested": True} for slot in s["suggested"])
            unscheduled.append({"medicine": _label(med), "note": s["note"], "instructions": instr, "line": med.line_number})
        else:
            unscheduled.append({"medicine": _label(med), "note": s["note"], "instructions": instr, "line": med.line_number})
    rows.sort(key=lambda r: (SLOTS.index(r["time"]), r["line"]))
    return {"rows": rows, "unscheduled": unscheduled}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z]", "", (name or "").lower())


def safety_warnings(meds, allergies_text: str = "") -> list[dict]:
    out = []

    def add(level, line, message):
        out.append({"level": level, "line": line, "message": message})

    for med in meds:
        who = f"Line {med.line_number} ({med.name_as_written or 'unreadable'})"
        review = set(med.fields_needing_review or [])
        if not med.user_confirmed and ("name" in review or not med.name_as_written or med.name_as_written == "(unreadable)"):
            add("danger", med.line_number, f"{who}: the medicine name could not be read with certainty. Confirm it with your pharmacist before taking it.")
        if not med.strength:
            add("warning", med.line_number, f"{who}: strength (e.g. 500 mg) is not written or not readable.")
        if not med.frequency:
            add("warning", med.line_number, f"{who}: how often to take it is not written or not readable.")
        if not med.duration:
            add("warning", med.line_number, f"{who}: duration (how many days) is not written or not readable.")
        if not med.user_confirmed:
            add("info", med.line_number, f"{who}: not yet confirmed by you.")

    seen: dict[str, int] = {}
    for med in meds:
        key = _norm(med.generic_name or med.name_as_written)
        if len(key) >= 4:
            if key in seen:
                add("warning", med.line_number, f"Lines {seen[key]} and {med.line_number} look like the same medicine. "
                                                "Ask your pharmacist whether both are intended.")
            else:
                seen[key] = med.line_number

    words = {w for w in re.findall(r"[a-z]{4,}", (allergies_text or "").lower())}
    for med in meds:
        names = {_norm(med.generic_name), _norm(med.name_as_written)} - {""}
        hit = [w for w in words if any(w in n or n in w for n in names)]
        if hit:
            add("danger", med.line_number, f"Line {med.line_number} ({med.name_as_written}) matches an allergy in your profile "
                                           f"(\"{hit[0]}\"). Tell your doctor or pharmacist before taking it.")
    return sorted(out, key=lambda w: ({"danger": 0, "warning": 1, "info": 2}[w["level"]], w["line"]))


def identified_names(meds) -> list[str]:
    """Names safe to look up: an exact RxNorm match (generic_name) or a name the user confirmed. Never a guess."""
    names = []
    for med in meds:
        if med.generic_name:
            names.extend(n.strip() for n in med.generic_name.split("/") if n.strip())
        elif med.user_confirmed and med.name_as_written and med.name_as_written != "(unreadable)":
            names.append(med.name_as_written)
    return list(dict.fromkeys(names))[:10]
