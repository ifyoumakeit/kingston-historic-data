#!/usr/bin/env python3
"""Derive commissioner service records from meeting attendance.

Attendance is not membership. The roster of a given meeting names who sat and
who was *absent* — and being minuted as absent is itself proof of membership.
So service is measured across present-or-absent appearances, and attendance is
reported separately as a rate within that span.

The rosters list only sitting members, so a commissioner's term is bounded by
their first and last appearance in any roster. Vacant seats are minuted too,
and are carried through as their own row so a short-handed commission stays
visible.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "decisions.json"
OUT = ROOT / "data" / "people.json"

BOARDS = {
    "HLPC": ("members_present", "members_absent"),
    "HAC": ("hac_members_present", None),
}


def slugify(value):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def build(meetings, present_key, absent_key, latest_overall):
    people = {}
    timeline = []

    for meeting in meetings:
        present = [p["name"] for p in meeting[present_key] if p["name"] != "Vacant"]
        absent = (
            [p["name"] for p in meeting[absent_key] if p["name"] != "Vacant"]
            if absent_key
            else []
        )
        vacancies = sum(
            1
            for key in (present_key, absent_key)
            if key
            for p in meeting[key]
            if p["name"] == "Vacant"
        )
        roles = {
            p["name"]: p["role"]
            for key in (present_key, absent_key)
            if key
            for p in meeting[key]
            if p["role"]
        }

        timeline.append(
            {
                "date": meeting["date"],
                "present": present,
                "absent": absent,
                "vacancies": vacancies,
            }
        )

        for name in [*present, *absent]:
            record = people.setdefault(
                name,
                {
                    "name": name,
                    "slug": slugify(name),
                    "first_meeting": meeting["date"],
                    "last_meeting": meeting["date"],
                    "present": 0,
                    "absent": 0,
                    "roles": [],
                },
            )
            record["first_meeting"] = min(record["first_meeting"], meeting["date"])
            record["last_meeting"] = max(record["last_meeting"], meeting["date"])
            if name in present:
                record["present"] += 1
            else:
                record["absent"] += 1

            role = roles.get(name)
            if role:
                held = record["roles"]
                # Collapse a role held continuously into a single span.
                if held and held[-1]["role"].lower() == role.lower():
                    held[-1]["to"] = meeting["date"]
                else:
                    held.append({"role": role, "from": meeting["date"], "to": meeting["date"]})

    dates = [m["date"] for m in timeline]
    # Nineteen narrative-era meetings record no roster at all. Measuring a term
    # against every meeting would flag a gap for all of them, so compare only
    # against meetings that actually named who sat.
    rostered = [m["date"] for m in timeline if m["present"] or m["absent"]]
    latest = latest_overall

    for record in people.values():
        span = [d for d in rostered if record["first_meeting"] <= d <= record["last_meeting"]]
        record["meetings_in_term"] = len(span)
        record["meetings_unrostered"] = len(
            [d for d in dates if record["first_meeting"] <= d <= record["last_meeting"]]
        ) - len(span)
        seen = record["present"] + record["absent"]
        record["meetings_recorded"] = seen
        record["attendance_rate"] = round(record["present"] / seen, 3) if seen else None
        record["active"] = record["last_meeting"] == latest
        # A term whose roster never lapsed is a clean read; gaps mean a roster
        # block the parser could not recover, and the term is a lower bound.
        record["complete_record"] = seen == len(span)

    ordered = sorted(
        people.values(),
        key=lambda r: (r["first_meeting"], -r["meetings_recorded"], r["name"]),
    )
    return ordered, timeline


def main():
    meetings = sorted(json.loads(SOURCE.read_text()), key=lambda m: m["date"])
    latest_overall = max(
        (m["date"] for m in meetings if m["members_present"] or m["members_absent"]),
        default=None,
    )
    payload = {}
    for board, (present_key, absent_key) in BOARDS.items():
        people, timeline = build(meetings, present_key, absent_key, latest_overall)
        payload[board] = {"people": people, "timeline": timeline}

    OUT.write_text(json.dumps(payload, indent=2) + "\n")

    for board, data in payload.items():
        print(f"{board}: {len(data['people'])} people over {len(data['timeline'])} meetings")
        for person in data["people"]:
            flag = "" if person["complete_record"] else "  (gaps in roster)"
            role = person["roles"][-1]["role"] if person["roles"] else ""
            print(
                f"  {person['first_meeting']} -> {person['last_meeting']}  "
                f"{person['name']:<18} {person['present']:>3}P/{person['absent']:>2}A  "
                f"{'ACTIVE' if person['active'] else '      '} {role}{flag}"
            )


if __name__ == "__main__":
    main()
