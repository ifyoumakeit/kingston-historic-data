# Kingston HLPC Docket

An index of every decision the City of Kingston's **Historic Landmarks
Preservation Commission** has recorded since 2020.

Kingston reviews exterior work on every building in its five local historic
districts. Those rulings are published as PDFs, reachable only through a
cascading-dropdown archive with no list, no search, and no way to ask what the
commission has said about a given house. This repo scrapes that archive, parses
the minutes, and builds a static site that answers the question.

**78 meetings · 627 agenda items · 369 recorded decisions · 251 properties**

---

## How it works

```
scripts/scrape_index.py   walks the ASP.NET dropdown archive  -> data/index.json
scripts/fetch_minutes.py  downloads PDFs, extracts text       -> data/{pdf,text}/
scripts/parse_minutes.py  parses meetings, items, decisions   -> data/decisions.json
scripts/build_people.py   derives commissioner service records -> data/people.json
scripts/fetch_geo.py      joins parcels by SBL, city outline   -> data/parcels.json
scripts/parse_agendas.py  parses agendas into scheduled items  -> data/agendas.json
src/                      Astro site built from those JSON files
```

`data/index.json` and `data/decisions.json` are committed; the PDFs and
extracted text are cached locally and gitignored (re-fetchable, ~40 MB).

### Rebuild from scratch

```sh
python3 -m venv .venv && .venv/bin/pip install pypdf cryptography
.venv/bin/python scripts/scrape_index.py      # ~5 min, sequential postbacks
.venv/bin/python scripts/fetch_minutes.py --since 2020
.venv/bin/python scripts/parse_minutes.py
.venv/bin/python scripts/fetch_minutes.py --kind agenda --since 2020
.venv/bin/python scripts/parse_agendas.py
.venv/bin/python scripts/build_people.py
.venv/bin/python scripts/fetch_geo.py         # optional; parcel geometry
npm install && npm run dev
```

`fetch_minutes.py` caches, so a monthly re-run only pulls the new meeting.

## The data model

See [`docs/data-model.md`](docs/data-model.md). The short version:

**`Meeting 1—* Item 1—* Decision`**

An *item* is a project, not a decision. One item routinely produces several
independent votes — `#20 Presidents Pl` carried `DECISION 1 (Paint)` and
`DECISION 2 (Windows)` with different outcomes. 135 of 627 items have more
than one decision.

The **HLPC and the Heritage Area Commission are separate bodies.** They met
jointly from January 2021 to August 2023 and voted separately on the same
applications, so the board is recorded on each *decision*. Aggregating without
grouping by board double-counts every outcome in that period.

`sbl` (the tax parcel) is identity; `address` is display. It is also what puts
properties on the map: New York State publishes every parcel keyed by that same
number, so a point sits on the real tax lot rather than a geocoder's guess at
where a street number falls. 229 of 243 referenced parcels resolve.

`sbl` (the tax parcel) is identity; `address` is display. A parcel number
survives the address spellings that drift between meetings, and joins to county
assessment, sales, and GIS data.

## Design

Readability first. The site is mostly long-form public record — findings of
fact, motions, minutes — so type carries the design and colour is kept to
almost nothing: warm paper, warm ink, two greys, and a single accent reserved
for things you can interact with.

Outcomes are encoded in value and texture rather than hue. A settled approval
is a solid mark, an approval with conditions is hatched, an open matter is
hollow, a refusal is struck through. It reads the same in greyscale, in print,
and with any colour vision, and it means no information here depends on colour.

Accessibility is checked with axe-core against every page type; all report
clean, and text clears WCAG AA against the darkest surface it sits on.

## Known limits

- **Coverage starts in 2020.** Minutes back to 2010 exist but are scans with
  poor OCR or loose narrative; parsing them would invent precision the
  documents don't have.
- **18 meetings (Jan 2020 – Jun 2021) predate the `DECISION:` convention.**
  Their items are indexed and searchable; their outcomes are shown as "no
  decision recorded" rather than guessed.
- **Votes are kept verbatim.** The minutes use bare initials that only resolve
  against that meeting's roster, and the notation changed several times.

## Sources and reuse

- **Minutes and agendas** — published by the City of Kingston, which the Open
  Meetings Law (NY Public Officers Law art. 7 §106) requires it to make
  available. Only linked to, never rehosted. `robots.txt` permits these paths
  and asks for a 15-second crawl delay, which the scripts honour.
- **Parcel geometry** — NYS 2025 Tax Parcels Public, shared for the counties
  that granted permission (Ulster among them). Credit: contributing counties,
  NYS ITS Geospatial Services, and the NYS Department of Taxation and
  Finance's Office of Real Property Tax Services.
- **City outline** — US Census TIGER. **District boundaries** — National Park
  Service. Both federal works in the public domain.

Applicant and owner names are deliberately not extracted. Scattered across
PDFs they are public record; lifted into a searchable field they become a
directory of who owns what, which is a different thing from an index of
decisions.

## Source and standing

All content is derived from minutes published by the City of Kingston at
<https://kingston-ny.gov/Agendas>. Every item links back to the PDF it was read
from. This is an unofficial index — the signed minutes are the record.
