#!/usr/bin/env python3
"""Turn extracted HLPC minutes text into structured meetings + decisions.

From roughly July 2021 onward the minutes follow a rigid shape that parses
cleanly:

    7.  #95 John Street  Replacement of windows. SBL 48.330-3-27. SEQR Type II.
        Transect Zone T4N, FSHD. Ward 5. Jane Doe, applicant; Acme LLC, owner.
        DISCUSSION: ...
        DECISION: The Commission voted unanimously to approve ...

Earlier meetings are narrative, so items are still segmented but carry no
DECISION block; those are flagged `needs_review` for the LLM pass to resolve.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TXT_DIR = ROOT / "data" / "text"
INDEX = ROOT / "data" / "index.json"
OUT = ROOT / "data" / "decisions.json"

# Page header/footer repeated on every page of the modern minutes.
BOILERPLATE = re.compile(
    r"""(?ix)
    ^\s*(
        CITY\ OF\ KINGSTON
      | planning@kingston-ny\.gov
      | .*,\ Planning\ Director .*
      | City\ Hall\ ·.*
      | _{10,}
      | Page\ \d+(\ of\ \d+)?
      | \d+\ \|\ P\ ?a\ ?g\ ?e
    )\s*$
    """
)

# "12.  #43-47 North Front Street ..." — the leading number of an agenda item.
ITEM_RE = re.compile(r"^\s{0,6}(\d{1,2})\.\s+(?=\S)")

# From 2021 to 2023 the HLPC met jointly with the Heritage Area Commission and
# each board recorded its own motion, so a marker may carry a board prefix:
#   "HLPC DECISION:", "HAC DECISION 2 (Paint):", "DISCUSSION:"
# The separator drifted too: "HLPC DECISION:", "HAC DECISION :" and, through
# most of 2021, "HLPC Decision –". A dash only counts when whitespace follows,
# so hyphenated words ("DECISION-MAKING") are not mistaken for markers.
_MARKER = (
    r"^\s*(?:(?P<board>HLPC|HAC|LWRP|COMMISSION|BOARD)\s+)?"
    r"{word}S?\s*(?P<seq>\d+)?\s*(?P<qual>\([^)]*\))?"
    r"\s*(?::|[\-–—](?=\s))"
)
DECISION_RE = re.compile(_MARKER.format(word="DECISION"), re.I)
DISCUSSION_RE = re.compile(_MARKER.format(word="DISCUSSION"), re.I)

# Public-hearing minutes number each speaker, which otherwise looks like an
# agenda item: "14. Cheryl Schneider (via zoom)".
SPEAKER_RE = re.compile(
    r"^[A-Z][A-Za-z'\.\-]+(?:\s+[A-Z][A-Za-z'\.\-]+){1,3}"
    r"(?:\s*\((?:via\s+)?(?:zoom|phone|in[-\s]person)[^)]*\))?"
    r"(?:\s*[-–,]\s*.{0,40})?$",
    re.I,
)

SECTION_RE = re.compile(
    r"^\s*(NEW BUSINESS|OLD BUSINESS|GENERAL BUSINESS|CONTINUED BUSINESS"
    r"|OTHER BUSINESS|COMMISSION BUSINESS|ADJOURN\w*|CALL MEETING TO ORDER)\b",
    re.I,
)

STREET_WORDS = (
    r"St(?:reet)?|Ave(?:nue)?|Rd|Road|Blvd|Boulevard|Ln|Lane|Pl(?:ace)?|Ct|Court"
    r"|Dr(?:ive)?|Ter(?:race)?|Way|Sq(?:uare)?|Alley|Row|Broadway|Strand|Circle"
)
ADDRESS_RE = re.compile(
    rf"#?\s*(\d+[\d\-–/&\s]*?)\s+"
    rf"((?:[A-Z][A-Za-z'\.]*\s+){{0,3}}(?:{STREET_WORDS}))\b",
    re.I,
)

FIELD_PATTERNS = {
    # Section.Block-Lot with an optional sublot: "56.42-7-12", "48.330-3-27",
    # "56.108-2-27.100". The clerk drops spaces in at random ("56. 43-8-61.100"),
    # so whitespace is tolerated between every part and stripped downstream.
    # Matching the shape positively beats scanning to the next full stop, which
    # truncated "56. 43-..." to "56".
    "sbl": re.compile(
        r"SBL[:#\s]*(\d{1,3}\s*\.\s*\d{1,3}\s*-\s*\d{1,3}\s*-\s*\d{1,4}"
        r"(?:\s*\.\s*\d{1,4})?)",
        re.I,
    ),
    "seqr": re.compile(r"SEQR[:\s]*(Type\s*[IVX]+|Unlisted)", re.I),
    "ward": re.compile(r"\bWard\s*[:#]?\s*(\d{1,2})\b", re.I),
    "transect": re.compile(r"Transect\s*Zone[:\s]*([A-Z0-9\-]+)", re.I),
    "zone": re.compile(r"(?<!Transect )\bZone[:\s]+([A-Z0-9\-]{1,8})\b"),
    # "Jane Doe, applicant; Acme LLC, owner." but also "David Garwacke;
    # applicant/owner." — separator and role labels both vary.
    "applicant": re.compile(r"([A-Z][^;.\n]{2,60}?)\s*[;,]\s*applicant", re.I),
    "owner": re.compile(r"([A-Z][^;.\n]{2,60}?)\s*[;,]\s*owner", re.I),
    "applicant_owner": re.compile(
        r"([A-Z][^;.\n]{2,60}?)\s*[;,]\s*applicant\s*/\s*owner", re.I
    ),
    "project_url": re.compile(r"(https://cityofkingstonny\.municollab\.com/\S+)"),
}

# Local historic districts / overlays that show up as abbreviations.
# Each district appears either abbreviated ("FSHD") or spelled out
# ("Fair Street Historic District"); both forms show up in the same era.
# The Form-Based Code (August 2023) renamed two districts, and the minutes
# switch abbreviation the moment it passes: SHD becomes KSHD, RHD becomes
# RWSHD. They are the same places, and the old and new codes never appear in
# the same meeting — so both forms map to one district here.
DISTRICTS = {
    "Stockade Historic District": r"\bK?SHD\b|\b(?:Kingston\s+)?Stockade\s+(?:Area\s+|Expansion\s+|Local\s+)*Historic\s+District\b",
    "Fair Street Historic District": r"\bFSHD\b|\bFair\s+St(?:reet)?\.?\s+(?:Local\s+)?Historic\s+District\b",
    "Chestnut Street Historic District": r"\bCSHD\b|\bChestnut\s+St(?:reet)?\.?\s+(?:Local\s+)?Historic\s+District\b",
    "Rondout Historic District": r"\bR(?:WS)?HD\b|\bRondout(?:[-–\s]+West\s+Strand)?\s+(?:Local\s+)?Historic\s+District\b",
    "Wilbur Historic District": r"\bWHD\b|\bWilbur\s+(?:Local\s+)?Historic\s+District\b",
    "Montrepose Historic District": r"\bMRHD\b|\bMontrepose\s+(?:Local\s+)?Historic\s+District\b",
    # "HA" is the Heritage Area overlay (a place); "HAC" is the Heritage Area
    # Commission (a body). Matching HAC here would file every joint-meeting
    # heading under the overlay.
    "Kingston Heritage Area": r"\bHA\b|\bHeritage\s+Area\b",
    # Not a historic district — the waterfront overlay from the city's Local
    # Waterfront Revitalization Program, which triggers its own review.
    "Coastal Zone": r"\bCZ\b|\bCoastal\s+Zone\b",
}

# Ordered: the first pattern that matches the DECISION text wins.
OUTCOMES = [
    ("withdrawn", r"\bwithdrew\b|\bwithdrawn\b"),
    ("tabled", r"\bto\s+TABLE\b|\btabled\b|\blay(?:ing)?\s+the\s+matter\s+on\s+the\s+table\b"),
    ("denied", r"\bden(?:y|ied|ial)\b|\bdisapprov\w*\b|\breject\w*\b"),
    ("approved_with_conditions", r"approv\w*[^.]{0,120}\b(with|subject to)\s+(the\s+)?(following\s+)?condition"),
    ("approved", r"\bapprov\w*\b|\bgrant\w*\s+(?:a\s+)?(?:certificate|COA)\b"),
    ("referred", r"\brefer\w*\b|\blead\s+agency\b"),
    ("adopted", r"\badopt\w*\b"),
    ("no_action", r"\bno\s+action\b|\btook\s+no\s+vote\b"),
]

# Work-type categories, matched against the item heading + discussion text.
CATEGORIES = [
    ("Signage", r"\bsign(?:s|age)?\b|\bawning\b|\bmarquee\b"),
    ("Solar", r"\bsolar\b|\bphotovoltaic\b|\bPV\s+panel"),
    ("Windows & doors", r"\bwindow|\bdoor(?:s|way)?\b|\bstorm\s+door|\bfenestration\b"),
    ("Roofing", r"\broof(?:ing|s)?\b|\bshingle|\bgutter|\bcornice\b|\bchimney\b"),
    ("Siding & masonry", r"\bsiding\b|\bmasonry\b|\bbrick\b|\bstucco\b|\bpoint(?:ing)?\b|\bclapboard\b|\bshake\b"),
    ("Paint & finishes", r"\bpaint\w*\b|\bcolor\s+scheme\b"),
    ("Porches & decks", r"\bporch\w*\b|\bdeck\b|\bstoop\b|\bbalcon\w+\b|\bstair"),
    ("Additions & alterations", r"\baddition\b|\balteration\b|\bexpansion\b|\bdormer\b|\brenovat\w+\b|\brehabilitat\w+\b"),
    ("New construction", r"\bnew\s+construction\b|\bconstruction\s+of\s+a\b|\bnew\s+building\b|\bnew\s+\d+\s*unit\b|\binfill\b"),
    ("Demolition", r"\bdemoli\w+\b|\braz(?:e|ing)\b|\btear[-\s]down\b"),
    ("Mechanical & utilities", r"\bHVAC\b|\bcondenser\b|\bmini[-\s]split\b|\bheat\s+pump\b|\bmechanical\s+equipment\b|\bgenerator\b|\bmeter\b|\bantenna\b"),
    ("Fences & site work", r"\bfenc\w+\b|\bpatio\b|\blandscap\w+\b|\bdriveway\b|\bpaving\b|\bshed\b|\b(?:retaining|garden|yard)\s+wall\b"),
    ("Parking", r"\bparking\s+lot\b|\bparking\s+area\b"),
    ("Lighting", r"\blight(?:ing|s)?\s+fixture|\bexterior\s+lighting\b|\bsconce\b"),
    ("Landmark designation", r"\blandmark\s+designation\b|\bdesignat\w+\s+(?:as|a)\s+(?:a\s+)?(?:local\s+)?landmark\b|\bhistoric\s+district\s+(?:expansion|nomination|boundary|designation)\b|\bnominat\w+\b"),
    ("SEQR & referrals", r"\blead\s+agency\b|\breferral\b|\bSEQR\s+determination\b|\bcoordinated\s+review\b"),
    ("Enforcement", r"\bviolation\b|\bwithout\s+review\b|\bafter[-\s]the[-\s]fact\b|\bstop\s+work\b|\bunapproved\b"),
    ("Administrative", r"\badoption\s+of\b.*\bminutes\b|\bby[-\s]?laws\b|\belection\s+of\s+officers\b|\btraining\b|\bwork\s*session\b"),
]

VOTE_RE = re.compile(
    r"\(\s*Motion[^)]{0,300}?\)"
    r"|Motion\s*[-–—:]\s*[^;\n]{1,40};\s*2nd\s*[-–—:]\s*[^;\n)]{1,40}",
    re.I,
)
UNANIMOUS_RE = re.compile(r"\bunanimous\w*\b", re.I)


def clean(text):
    lines = []
    for line in text.splitlines():
        line = line.replace(" ", " ").rstrip()
        if BOILERPLATE.match(line):
            continue
        lines.append(line)
    # Collapse runs of blank lines left behind by stripped headers.
    out, blank = [], False
    for line in lines:
        if not line.strip():
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(line)
    return "\n".join(out)


def split_items(text):
    """Split the body into (number, lines) agenda items.

    Numbered sub-lists inside an item restart at 1, so an item number is only
    accepted when it advances the running count.
    """
    lines = text.splitlines()
    items, current, expected, first_line = [], None, 1, len(lines)
    for line in lines:
        match = ITEM_RE.match(line)
        if match and int(match.group(1)) >= expected:
            number = int(match.group(1))
            if current:
                items.append(current)
            current = {"number": number, "lines": [line[match.end():]]}
            expected = number + 1
            first_line = min(first_line, lines.index(line))
            continue
        if current is not None:
            if SECTION_RE.match(line) and not DECISION_RE.match(line):
                # Section banners sit between items; keep them out of the body.
                continue
            current["lines"].append(line)
    if current:
        items.append(current)
    return items, first_line


def blocks(lines):
    """Separate an item body into heading, discussion, and decision parts."""
    heading, discussion, decisions = [], [], []
    mode, buffer, label, board = "heading", [], None, None

    def flush():
        text = "\n".join(buffer).strip()
        if not text:
            return
        if mode == "heading":
            heading.append(text)
        elif mode == "discussion":
            discussion.append(text)
        else:
            decisions.append({"label": label, "board": board, "text": text})

    for line in lines:
        dec = DECISION_RE.match(line)
        dis = DISCUSSION_RE.match(line)
        if dec or dis:
            flush()
            buffer = [line[(dec or dis).end():].strip()]
            if dec:
                mode = "decision"
                label = (dec.group("qual") or dec.group("seq") or "").strip("() ") or None
                board = (dec.group("board") or "HLPC").upper()
            else:
                mode, label, board = "discussion", None, None
            continue
        buffer.append(line)
    flush()
    return (
        " ".join(heading).strip(),
        "\n\n".join(discussion).strip(),
        decisions,
    )


def squash(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_address(heading):
    match = ADDRESS_RE.search(heading)
    if not match:
        return None
    number = re.sub(r"\s+", "", match.group(1)).strip("-–/&")
    street = squash(match.group(2)).title()
    street = re.sub(r"\bSt\b\.?$", "Street", street)
    street = re.sub(r"\bAve\b\.?$", "Avenue", street)
    street = re.sub(r"\bRd\b\.?$", "Road", street)
    street = re.sub(r"\bDr\b\.?$", "Drive", street)
    street = re.sub(r"\bPl\b\.?$", "Place", street)
    return f"{number} {street}"


def outcome_of(text):
    for name, pattern in OUTCOMES:
        if re.search(pattern, text, re.I):
            return name
    return "other"


def roll_up(decisions):
    """Item-level outcome. The HLPC's own motion is authoritative; a joint HAC
    vote is advisory. An item with two differently-resolved decisions (e.g.
    paint approved, windows tabled) rolls up to "mixed"."""
    if not decisions:
        return None
    hlpc = [d for d in decisions if d["board"] in (None, "HLPC", "COMMISSION")]
    outcomes = {d["outcome"] for d in (hlpc or decisions)}
    outcomes.discard("other")
    if not outcomes:
        return "other"
    if len(outcomes) == 1:
        return outcomes.pop()
    return "mixed"


def categorize(text):
    found = [name for name, pattern in CATEGORIES if re.search(pattern, text, re.I)]
    # "Administrative" is only meaningful when nothing substantive matched.
    if len(found) > 1 and "Administrative" in found:
        found.remove("Administrative")
    return found


def find_districts(text):
    return [name for name, pattern in DISTRICTS.items() if re.search(pattern, text)]


def extract_vote(text):
    match = VOTE_RE.search(text)
    if match:
        return squash(match.group(0)).strip("()")
    if UNANIMOUS_RE.search(text):
        return "unanimous"
    return None


ROSTER_BLOCKS = [
    ("present", r"(?:HLPC\s+)?(?:COMMISSION|BOARD)\s+MEMBERS(?:\s+PRESENT)?"),
    ("absent", r"(?:COMMISSION\s+|BOARD\s+)?MEMBERS?\s+ABSENT|ABSENT"),
    ("hac_present", r"HAC\s+(?:COMMISSION\s+)?MEMBERS(?:\s+PRESENT)?"),
    ("staff", r"(?:CITY\s+STAFF[^:]*|OTHERS(?:\s+PRESENT)?)"),
]
ROSTER_RE = {
    key: re.compile(rf"^\s*{pattern}\s*:\s*(.*)$", re.I)
    for key, pattern in ROSTER_BLOCKS
}
ANY_HEADING_RE = re.compile(r"^\s*[A-Z][A-Z &/#\d'\.\-]{4,}\s*:")

TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*([AaPp]\.?[Mm]\.?)")
SPECIAL_RE = re.compile(r"\bspecial\s+meeting\b|\bpublic\s+hearing\b|\bwork\s*session\b", re.I)
VIRTUAL_RE = re.compile(r"\bzoom\b|\bvirtual\b|\bGoToMeeting\b|\bGTM\b|\bwebinar\b", re.I)


# Attendance annotations the clerk appends to a name. They describe how someone
# attended, not who they are, so they are stripped from the name and kept out
# of the roster identity.
ATTENDANCE_NOTE = re.compile(
    r"""(?ix)
    \s*(?:[\-–—,]\s*|\()
    (?: absent | excused | present | arrived \s+ late | late
      | attend(?:ed|ing)? (?:\s+\w+){0,3}
      | remote(?:ly)? (?:\s+attendee)? | via \s+ \w+ | by \s+ \w+
      | recus\w+ | resigned | term \s+ expired )
    \s*\)? \s*$
    """
)

# Honorifics and credentials that trail a name.
SUFFIX = re.compile(r"(?i),?\s*\b(Esq|Jr|Sr|II|III|RA|AIA|PE|LEED\s*AP)\b\.?\s*$")

ROLE_RE = re.compile(
    r"(?i),\s*((?:Vice[\s-]?)?Chair\w*|Secretary|[\w\.\s]*"
    r"(?:Director|Counsel|Planner|Architect|Admin\w*)|RA|AIA)\b"
)

# Words that appear in a roster block but are not people.
NOT_A_NAME = re.compile(
    r"(?i)^(vacant|none|n/?a|absent|present|others?|staff|tbd|open\s+seat)$"
)

# A piece of a roster line that names a title rather than a person. Titles run
# from a bare "RA" to "Asst. Corporation Counsel", so this matches on a role
# keyword within a short piece rather than on the whole string.
ROLE_WORD = re.compile(
    r"(?i)^(?=[\w\.\s-]{2,34}$)(?:[\w\.-]+\s+){0,3}"
    r"(chair\w*|vice[\s-]?chair\w*|secretary|architect|director|counsel"
    r"|planner|admin\w*|RA|AIA|esq|member)\.?$"
)


def strip_annotations(text):
    """Remove attendance notes, credentials, and stray punctuation."""
    name = squash(text)
    for _ in range(3):  # notes stack: "Kevin McEvoy - Absent (via Zoom)"
        stripped = ATTENDANCE_NOTE.sub("", name)
        stripped = SUFFIX.sub("", stripped)
        if stripped == name:
            break
        name = stripped
    return name.strip(" .,;-–—")


def split_people(blob):
    """Rosters are written with semicolons, commas, or one name per line, and
    the PDF text layer wraps long names across lines. Titles trail the name they
    modify, so pieces are walked in order and a title attaches to the person
    before it:

        "Mark, Grunblatt, Chairman, Andrea Puetz, RA, Nettie Morano"
         └── one person ──┘  title   └ person ┘ title  └ person ┘
    """
    people = []
    pending = ""   # a one-word piece that is probably half a wrapped name

    def flush_pending():
        nonlocal pending
        if pending:
            name = strip_annotations(pending)
            if name and not ROLE_WORD.match(name):
                people.append({"name": name, "role": None})
            pending = ""

    for line in blob.split("\n"):
        for piece in re.split(r"[;,]+", line):
            piece = squash(piece)
            if not piece:
                continue

            if ROLE_WORD.match(piece):
                flush_pending()
                if people and not people[-1]["role"]:
                    people[-1]["role"] = piece.strip(".")
                continue

            name = strip_annotations(piece)
            if not name or len(name) > 80 or not re.search(r"[A-Za-z]{2}", name):
                continue

            if len(name.split()) == 1:
                # Join consecutive single words: "Mark" + "Grunblatt".
                pending = f"{pending} {name}".strip()
                if len(pending.split()) >= 2:
                    people.append({"name": pending, "role": None})
                    pending = ""
                continue

            flush_pending()
            people.append({"name": name, "role": None})

    flush_pending()
    return people


def parse_preamble(text, first_item_line):
    """Read attendance and meeting logistics from the text above item 1."""
    lines = text.splitlines()[:first_item_line]
    rosters = {key: [] for key, _ in ROSTER_BLOCKS}
    key, buffer = None, []

    def flush():
        if key and buffer:
            rosters[key].extend(split_people("\n".join(buffer)))

    for line in lines:
        matched = None
        for name, pattern in ROSTER_RE.items():
            hit = pattern.match(line)
            if hit:
                matched = (name, hit.group(1))
                break
        if matched:
            flush()
            key, buffer = matched[0], [matched[1]]
            continue
        if key and (ANY_HEADING_RE.match(line) or not line.strip()):
            flush()
            key, buffer = None, []
            continue
        if key:
            buffer.append(line)
    flush()

    head = "\n".join(lines)
    time_match = TIME_RE.search(head)
    return {
        "members_present": rosters["present"],
        "members_absent": rosters["absent"],
        "hac_members_present": rosters["hac_present"],
        "staff_present": rosters["staff"],
        "start_time": (
            f"{time_match.group(1)} {time_match.group(2).upper().replace('.', '')}"
            if time_match
            else None
        ),
        "meeting_type": "special" if SPECIAL_RE.search(head) else "regular",
        "format": "virtual" if VIRTUAL_RE.search(head) else "in_person",
        "joint_with_hac": bool(rosters["hac_present"]),
    }


def pick_documents(records):
    """One minutes document per meeting date, preferring real minutes to
    raw recording transcripts and amended versions to originals."""
    by_date = {}
    for record in records:
        if record["kind"] != "minutes" or not record.get("date_exact"):
            continue
        if record["date"][:4] < "2020":
            continue
        name = record["filename"].lower()
        score = 0
        if "transcript" in name:
            score -= 10
        if "amend" in name or "final" in name:
            score += 2
        if "draft" in name:
            score -= 1
        by_date.setdefault(record["date"], []).append((score, record))
    chosen = {}
    for date, candidates in by_date.items():
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        chosen[date] = candidates[0][1]
    return chosen


def slug_for(record):
    stem = record["filename"].rsplit(".", 1)[0]
    stem = "".join(c if c.isalnum() else "-" for c in stem).strip("-").lower()
    while "--" in stem:
        stem = stem.replace("--", "-")
    return f"{record['date']}_{stem}"


def edit_distance(a, b, limit=2):
    """Levenshtein distance, giving up once it exceeds `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


ROSTER_KEYS = (
    "members_present",
    "members_absent",
    "hac_members_present",
    "staff_present",
)


def canonicalize_rosters(meetings):
    """Resolve roster spellings against the commission's actual membership.

    The clerk's spelling drifts ("Andrea Puetz" / "Andrea Bornhoft Puetz",
    "Matthew Rickie" / "Matthew Ricke"), and two people occasionally land on one
    line. The commission is small, so the reliable signal is the surname: build
    an index of surnames from the names that recur, then map every fragment onto
    the fullest form of that surname.
    """
    counts = {}
    for meeting in meetings:
        for key in ROSTER_KEYS:
            for person in meeting[key]:
                name = person["name"]
                if NOT_A_NAME.match(name):
                    continue
                counts[name] = counts.get(name, 0) + 1

    # A surname maps to the spelling seen most often, tie-broken by length so
    # "Andrea Bornhoft Puetz" loses to the everyday "Andrea Puetz".
    by_surname = {}
    for name, count in counts.items():
        tokens = name.split()
        if len(tokens) < 2:
            continue
        surname = tokens[-1].lower().strip(".,")
        if NOT_A_NAME.match(surname) or ROLE_WORD.match(surname):
            # "Nettie Morano Vacant Vacant" is a name plus empty seats, and
            # "Mark Grunblatt Vacant, Vice Chair" trails a title. Neither is a
            # surname; indexing them would swallow the real name.
            continue
        best = by_surname.get(surname)
        if best is None or (count, -len(name)) > (counts[best], -len(best)):
            by_surname[surname] = name

    # Near-miss surnames collapse onto the commoner form. "Ricke" and "Rickie"
    # differ by one inserted letter and are not prefixes of each other, so this
    # compares edit distance. Kept deliberately tight — one edit, five letters
    # or more, same opening — so that genuinely different commissioners with
    # similar surnames are never merged.
    for surname in sorted(by_surname, key=lambda s: counts[by_surname[s]]):
        if len(surname) < 5 or counts[by_surname[surname]] > 2:
            continue
        for other in by_surname:
            if other == surname or len(other) < 5:
                continue
            if counts[by_surname[other]] <= counts[by_surname[surname]]:
                continue
            if surname[:3] == other[:3] and edit_distance(surname, other) <= 1:
                by_surname[surname] = by_surname[other]
                break

    surnames = set(by_surname)

    def resolve(name):
        """Return the canonical names contained in a roster fragment.

        A fragment may hold several people, and may trail empty seats
        ("Nettie Morano Vacant Vacant"), which are reported as their own
        entries so a short-handed commission stays visible.
        """
        vacancies = len(re.findall(r"(?i)\bvacant\b", name))
        name = re.sub(r"(?i)\bvacant\b", " ", name).strip(" ,;")
        if NOT_A_NAME.match(name) or ROLE_WORD.match(name) or not name:
            # A title that never found a person to attach to is not a member.
            return ["Vacant"] * vacancies
        tokens = [t for t in name.replace(",", " ").split() if t]
        found, cursor = [], 0
        for index, token in enumerate(tokens):
            key = token.lower().strip(".,")
            if key in surnames and index >= cursor:
                found.append(by_surname[key])
                cursor = index + 1
        if found:
            return found + ["Vacant"] * vacancies
        return ([name] if len(tokens) >= 2 else []) + ["Vacant"] * vacancies

    for meeting in meetings:
        for key in ROSTER_KEYS:
            resolved, seen = [], set()
            for person in meeting[key]:
                names = resolve(person["name"])
                for index, canonical in enumerate(names):
                    if canonical != "Vacant":
                        if canonical in seen:
                            continue
                        seen.add(canonical)
                    # A piece holds one person, so any title on it is theirs.
                    role = person["role"] if index == 0 else None
                    resolved.append({"name": canonical, "role": role})
            meeting[key] = resolved


def main():
    records = json.loads(INDEX.read_text())
    chosen = pick_documents(records)

    meetings = []
    for date in sorted(chosen):
        record = chosen[date]
        path = TXT_DIR / f"{slug_for(record)}.txt"
        if not path.exists():
            continue
        text = clean(path.read_text(errors="replace"))
        items, first_item_line = split_items(text)
        meta = parse_preamble(text, first_item_line)

        entries = []
        for item in items:
            heading, discussion, decisions = blocks(item["lines"])
            heading = squash(heading)
            if not heading:
                continue
            fields = {}
            for key, pattern in FIELD_PATTERNS.items():
                # The municollab project link often sits below the heading.
                scope = f"{heading}\n{discussion}" if key == "project_url" else heading
                match = pattern.search(scope)
                value = squash(match.group(1)) if match else None
                # A parcel number is an identifier, not prose: the clerk drops
                # spaces into it at random ("56.107- 4-11"), and leaving them in
                # splits one property into several.
                if value and key == "sbl":
                    value = value.replace(" ", "")
                fields[key] = value

            # A single party listed as "applicant/owner" fills both roles.
            if fields.get("applicant_owner"):
                fields["applicant"] = fields["applicant_owner"]
                fields["owner"] = fields["applicant_owner"]

            title = re.split(r"\bSBL\b|\bSEQR\b|https?://", heading)[0].strip(" .;")

            parsed = [
                {
                    "board": d["board"],
                    "scope": d["label"],
                    "outcome": outcome_of(d["text"]),
                    "vote": extract_vote(d["text"]),
                    "text": squash(d["text"]),
                }
                for d in decisions
            ]

            address = parse_address(heading)
            # A bare personal name with no application details is a speaker,
            # not an agenda item.
            if not parsed and not address and not fields["sbl"]:
                if SPEAKER_RE.match(squash(title)) and len(discussion) < 200:
                    continue

            # Categories come from the heading (the concise statement of work);
            # the discussion is only consulted when the heading says nothing.
            categories = categorize(heading) or categorize(discussion)

            entries.append(
                {
                    "id": f"{date}-{item['number']}",
                    "number": item["number"],
                    "title": squash(title)[:300],
                    "address": address,
                    "sbl": fields["sbl"],
                    "seqr": fields["seqr"],
                    "ward": int(fields["ward"]) if fields["ward"] else None,
                    "zone": fields["transect"] or fields["zone"],
                    "districts": find_districts(heading),
                    "applicant": fields["applicant"],
                    "owner": fields["owner"],
                    "project_url": fields["project_url"],
                    "categories": categories,
                    "outcome": roll_up(parsed),
                    "discussion": discussion or None,
                    "decisions": parsed,
                    "needs_review": not parsed,
                }
            )

        boards = sorted({d["board"] for e in entries for d in e["decisions"]} - {None})
        meta["joint_with_hac"] = meta["joint_with_hac"] or "HAC" in boards

        meetings.append(
            {
                "id": date,
                "date": date,
                "source_url": record["url"],
                "source_file": record["filename"],
                "structured": any(not e["needs_review"] for e in entries),
                "boards": boards,
                **meta,
                "items": entries,
            }
        )

    canonicalize_rosters(meetings)
    OUT.write_text(json.dumps(meetings, indent=2) + "\n")

    total = sum(len(m["items"]) for m in meetings)
    resolved = sum(1 for m in meetings for e in m["items"] if not e["needs_review"])
    addressed = sum(1 for m in meetings for e in m["items"] if e["address"])
    print(f"{len(meetings)} meetings, {total} items -> {OUT}")
    print(f"  with a parsed DECISION: {resolved} ({resolved * 100 // max(total,1)}%)")
    print(f"  with an address:        {addressed} ({addressed * 100 // max(total,1)}%)")
    unstructured = [m["date"] for m in meetings if not m["structured"]]
    print(f"  meetings needing the LLM pass: {len(unstructured)}")
    print("   ", ", ".join(unstructured))


if __name__ == "__main__":
    main()
