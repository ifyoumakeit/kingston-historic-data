# HLPC data model

Derived from the actual shape of City of Kingston Historic Landmarks
Preservation Commission minutes, 2020–2026 (87 PDFs, 78 distinct meetings).
Every field below exists because the minutes actually record it.

## Why it looks like this

Three facts about the source drive the whole model:

1. **A meeting is a list of numbered agenda items.** Item numbering is the only
   reliable structural signal in the PDFs.
2. **An item is a *project*, not a decision.** One item routinely produces
   several independent votes — `#20 Presidents Pl` in June 2026 carried
   `DECISION 1 (Paint)` and `DECISION 2 (Windows)` with different outcomes.
   135 of 627 items have more than one decision. Collapsing them to a single
   outcome per item would be lossy and wrong.
3. **The HLPC and the HAC are two separate commissions** that for a stretch
   met together. They have different jurisdictions and vote independently, so
   the board belongs on the *decision*, not on the meeting or the item.

So: `Meeting 1—* Item 1—* Decision`, and `Decision` names its board.

### The two commissions

| | HLPC | HAC |
|---|---|---|
| Body | Historic Landmarks Preservation Commission | Heritage Area Commission |
| Authority | Form-Based Code §405.26.L — Certificates of Appropriateness | NYS Heritage Area program review |
| Territory | Local historic districts (Stockade, Fair St, Chestnut St, Rondout, Wilbur) + individually designated landmarks | The Kingston Heritage Area, a larger overlay |

They are **not** the same body and their votes can differ. On joint meetings
each item is minuted once but voted twice — HAC casts more votes overall
because the Heritage Area covers more ground than the local districts do.

### Joint-meeting timeline (measured, not assumed)

| Period | Meetings | Arrangement |
|---|---|---|
| Jan 2020 – Dec 2020 | 11 | HLPC alone; narrative minutes, no `DECISION:` blocks |
| Jan 2021 – Aug 2023 | 28 joint | HLPC **and** HAC, separate motions per item |
| Sept 2023 – Jul 2026 | 33 | HLPC alone again |

Six meetings inside the joint era were HLPC-only (special meetings and early
2021), so joint status is derived per-meeting from the votes actually
recorded — never from the date range.

**Consequence for the site:** the default view is HLPC decisions. HAC votes are
retained and filterable, but silently mixing them would double-count outcomes
and misattribute a HAC approval to the HLPC.

---

## Entities

### Meeting

One HLPC meeting, keyed by date. Meetings are monthly, with occasional special
meetings and public hearings.

| Field | Type | Notes |
|---|---|---|
| `id` | string | The ISO date; unique — no two meetings share a day |
| `date` | date | `YYYY-MM-DD` |
| `source_url` | url | The minutes PDF on kingston-ny.gov |
| `source_file` | string | Original filename, kept for traceability |
| `structured` | bool | Whether the deterministic parser found `DECISION:` blocks |
| `boards` | string[] | Which commissions actually voted at this meeting |
| `meeting_type` | enum | `regular` \| `special` |
| `format` | enum | `in_person` \| `virtual` — the 2020–21 Zoom/GoToMeeting era |
| `start_time` | string? | e.g. `6:30 PM` |
| `joint_with_hac` | bool | HAC sat and voted at this meeting |
| `members_present` | Person[] | HLPC commissioners |
| `members_absent` | Person[] | |
| `hac_members_present` | Person[] | Only on joint meetings |
| `staff_present` | Person[] | Planning Director, counsel, preservation admin |
| `items` | Item[] | |

**Person** — `{ name, role? }`. Role is `Chairman`, `Vice Chairman`, `RA`,
`Planning Director`, etc. Names are *not* deduplicated into a commissioner
table by the parser; a `people.json` roll-up is a downstream derivation.

### Item

A numbered agenda item: one property, one application, one deliberation.

| Field | Type | Notes |
|---|---|---|
| `id` | string | `{meeting date}-{number}`, e.g. `2026-06-04-3` |
| `number` | int | Position on the agenda |
| `title` | string | Heading with the SBL/SEQR tail stripped |
| `address` | string? | Normalized, e.g. `20 Presidents Place`. ~61% of items |
| `sbl` | string? | Section-Block-Lot tax parcel id — the join key to the assessor roll |
| `seqr` | string? | `Type I` \| `Type II` \| `Unlisted` |
| `ward` | int? | 1–9 |
| `zone` | string? | Form-Based Code transect (`T4N`) or legacy zone (`C-2`, `RT`) |
| `districts` | string[] | Stockade / Fair Street / Chestnut Street / Rondout / Wilbur HD, Heritage Area |
| `applicant` | string? | |
| `owner` | string? | |
| `project_url` | url? | The municollab project dashboard, when cited |
| `categories` | string[] | Work types — see below |
| `outcome` | enum? | Roll-up of this item's decisions |
| `discussion` | text? | Verbatim `DISCUSSION:` narrative |
| `decisions` | Decision[] | |
| `needs_review` | bool | No decision could be parsed; the LLM pass targets these |

`sbl` is the most valuable field in the dataset — it is a stable parcel
identifier that survives address changes and joins to county assessment,
sales, and GIS data. `address` is display; `sbl` is identity.

### Decision

One recorded motion and its result.

| Field | Type | Notes |
|---|---|---|
| `board` | enum | `HLPC` \| `HAC` \| `LWRP` — which commission cast this vote. Never aggregate across boards without grouping by it |
| `scope` | string? | Qualifier from `DECISION 2 (Windows):` → `Windows` |
| `outcome` | enum | See below |
| `vote` | string? | `Motion – MG; 2nd – AP; KM, MR, RT – yes`, or `unanimous` |
| `text` | text | Verbatim decision language |

`vote` is deliberately kept as recorded text rather than parsed into tallies:
the minutes use bare initials (`MG`, `RT`) that only resolve against that
meeting's roster, and the notation changed several times between 2020 and 2026.
Resolving initials → commissioners is a downstream enrichment, not a parse.

---

## Controlled vocabularies

### `outcome`

| Value | Meaning |
|---|---|
| `approved` | Certificate of Appropriateness granted |
| `approved_with_conditions` | Approved subject to stated conditions |
| `denied` | Application refused |
| `tabled` | Held over, usually pending more material |
| `withdrawn` | Applicant pulled the application |
| `referred` | Sent on / lead agency consented to another board |
| `adopted` | Minutes, bylaws, resolutions |
| `no_action` | Discussed, no vote taken |
| `mixed` | Item-level only: its decisions resolved differently |
| `other` | A vote occurred but matched no pattern — review candidate |
| `null` | No decision recorded |

### `categories` — the work type

Multi-label; an item can be several at once (a rehab with new windows and
paint). Derived from the item heading, which is the commission's own concise
statement of the work.

`Signage` · `Solar` · `Windows & doors` · `Roofing` · `Siding & masonry` ·
`Paint & finishes` · `Porches & decks` · `Additions & alterations` ·
`New construction` · `Demolition` · `Mechanical & utilities` ·
`Fences & site work` · `Parking` · `Lighting` · `Landmark designation` ·
`SEQR & referrals` · `Enforcement` · `Administrative`

`Enforcement` is the notable one: it flags after-the-fact applications, work
done without review, and violations — the items with the most public interest.

---

## Provenance

Nothing is asserted without a citation. Every item carries its meeting's
`source_url`, and the verbatim `discussion` / `decisions[].text` are preserved
so any claim on the site links back to the sentence in the PDF that supports
it. Fields filled by the LLM pass are marked, never silently merged with
parsed ones.

## Known limits

- **Coverage starts at 2020.** 2010–2019 minutes exist (120 more PDFs) but are
  scanned with poor OCR or written as loose narrative.
- **The narrative era.** 19 meetings from Jan 2020 to Aug 2021 predate the
  `DECISION:` convention; their items parse but their outcomes require the LLM
  pass.
- **~39% of items have no address** — these are largely administrative items,
  minutes adoptions, and policy discussions, which correctly have none.
