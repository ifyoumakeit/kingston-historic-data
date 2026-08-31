#!/usr/bin/env python3
"""Parse HLPC agendas into scheduled items, and reconcile them with minutes.

An agenda carries everything an item has except the outcome — address, parcel,
SEQR class, ward, transect zone — because the decision is the
part that has not happened yet. Scheduled items are therefore kept in their own
file and given a `status`, never an `outcome`: folding "not yet heard" into the
approval figures would corrupt them.

An agenda item is `heard` once minutes exist for that meeting date, and
`scheduled` until then.
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import parse_minutes as M  # noqa: E402  (shares the item grammar)

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "data" / "index.json"
MINUTES = ROOT / "data" / "decisions.json"
OUT = ROOT / "data" / "agendas.json"

# "All comments must be in writing and received by 2PM on Tuesday, September 1, 2026."
DEADLINE_RE = re.compile(
    r"received\s+by\s+(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))\s+on\s+"
    r"(?:\w+day,?\s+)?([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})",
    re.I,
)
LOCATION_RE = re.compile(
    r"^\s*((?:In-Person|Virtual|Hybrid)[^\n]{0,90})$", re.I | re.M
)


def pick_agendas(records):
    """Latest agenda document per meeting date."""
    chosen = {}
    for record in records:
        if record["kind"] != "agenda" or not record.get("date_exact"):
            continue
        if record["date"][:4] < "2020":
            continue
        name = record["filename"].lower()
        score = 2 if ("final" in name or "amend" in name) else 0
        if "draft" in name:
            score -= 1
        current = chosen.get(record["date"])
        if current is None or score > current[0]:
            chosen[record["date"]] = (score, record)
    return {d: r for d, (_, r) in chosen.items()}


def main():
    records = json.loads(INDEX.read_text())
    agendas = pick_agendas(records)
    minutes_dates = {m["date"] for m in json.loads(MINUTES.read_text())}
    today = date.today().isoformat()

    meetings = []
    for meeting_date in sorted(agendas):
        record = agendas[meeting_date]
        path = M.TXT_DIR / f"{M.slug_for(record)}.txt"
        if not path.exists():
            continue

        text = M.clean(path.read_text(errors="replace"))
        items, first_item_line = M.split_items(text)
        meta = M.parse_preamble(text, first_item_line)

        head = "\n".join(text.splitlines()[:first_item_line])
        deadline = DEADLINE_RE.search(head)
        location = LOCATION_RE.search(head)

        entries = []
        for item in items:
            heading, discussion, _ = M.blocks(item["lines"])
            heading = M.squash(heading)
            if not heading:
                continue

            fields = {}
            for key, pattern in M.FIELD_PATTERNS.items():
                scope = f"{heading}\n{discussion}" if key == "project_url" else heading
                match = pattern.search(scope)
                value = M.squash(match.group(1)) if match else None
                if value and key in ("sbl", "transect", "zone"):
                    value = value.replace(" ", "")
                fields[key] = value

            title = re.split(r"\bSBL\b|\bSEQR\b|https?://", heading)[0].strip(" .;")
            if not title:
                # The heading opens with a URL or the parcel line, so there is
                # nothing before them to use as a title. Fall back to the
                # heading with the URLs taken out.
                title = re.sub(r"https?://\S+", "", heading).strip(" .;")
            title = M.strip_parties(title)
            address = M.parse_address(heading)
            if not address and not fields["sbl"] and M.SPEAKER_RE.match(M.squash(title)):
                continue

            entries.append(
                {
                    "id": f"{meeting_date}-a{item['number']}",
                    "number": item["number"],
                    "title": M.squash(title)[:300],
                    "address": address,
                    "sbl": fields["sbl"],
                    "seqr": fields["seqr"],
                    "ward": int(fields["ward"]) if fields["ward"] else None,
                    "zone": fields["transect"] or fields["zone"],
                    "districts": M.find_districts(heading),
                    "project_url": fields["project_url"],
                    "categories": M.categorize(heading) or M.categorize(discussion),
                    "detail": discussion or None,
                }
            )

        meetings.append(
            {
                "id": meeting_date,
                "date": meeting_date,
                "source_url": record["url"],
                "source_file": record["filename"],
                # An agenda is only a forecast until the minutes land.
                "status": "heard" if meeting_date in minutes_dates else (
                    "scheduled" if meeting_date >= today else "awaiting_minutes"
                ),
                "comment_deadline": (
                    f"{re.sub(r'\\s+', ' ', deadline.group(2)).replace(' ,', ',')}"
                    f"{'' if ',' in deadline.group(2) else ','}"
                    f" at {deadline.group(1).upper().replace(' ', '')}"
                    if deadline
                    else None
                ),
                "location": M.squash(location.group(1)) if location else None,
                "start_time": meta["start_time"],
                "meeting_type": meta["meeting_type"],
                "members_expected": meta["members_present"],
                "items": entries,
            }
        )

    OUT.write_text(json.dumps(meetings, indent=2) + "\n")

    counts = {}
    for meeting in meetings:
        counts[meeting["status"]] = counts.get(meeting["status"], 0) + 1
    total = sum(len(m["items"]) for m in meetings)
    print(f"{len(meetings)} agendas, {total} items -> {OUT}")
    print(f"  {counts}")
    for meeting in meetings:
        if meeting["status"] == "scheduled":
            print(f"\n  UPCOMING {meeting['date']} — {len(meeting['items'])} items")
            print(f"    comment deadline: {meeting['comment_deadline']}")
            print(f"    {meeting['location']}")
            for entry in meeting["items"]:
                print(f"      {entry['number']:>2}. {entry['address'] or '—':<22} {entry['title'][:52]}")


if __name__ == "__main__":
    main()
