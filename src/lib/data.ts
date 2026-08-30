import raw from "../../data/decisions.json";
import agendaData from "../../data/agendas.json";
import parcelData from "../../data/parcels.json";
import boundaryData from "../../data/boundary.json";

export type Person = { name: string; role: string | null };

export type Decision = {
  board: "HLPC" | "HAC" | "LWRP" | "COMMISSION" | null;
  scope: string | null;
  outcome: string;
  vote: string | null;
  text: string;
};

export type Item = {
  id: string;
  number: number;
  title: string;
  address: string | null;
  sbl: string | null;
  seqr: string | null;
  ward: number | null;
  zone: string | null;
  districts: string[];
  applicant: string | null;
  owner: string | null;
  project_url: string | null;
  categories: string[];
  outcome: string | null;
  discussion: string | null;
  decisions: Decision[];
  needs_review: boolean;
};

export type Meeting = {
  id: string;
  date: string;
  source_url: string;
  source_file: string;
  structured: boolean;
  boards: string[];
  meeting_type: string;
  format: string;
  start_time: string | null;
  joint_with_hac: boolean;
  members_present: Person[];
  members_absent: Person[];
  hac_members_present: Person[];
  staff_present: Person[];
  items: Item[];
};

export const meetings = (raw as unknown as Meeting[])
  .slice()
  .sort((a, b) => b.date.localeCompare(a.date));

/** An item paired with the meeting it was heard at. */
export type Entry = Item & { meeting: Meeting };

export const entries: Entry[] = meetings.flatMap((meeting) =>
  meeting.items.map((item) => ({ ...item, meeting })),
);

/**
 * Outcome vocabulary, coloured by the Sanborn fire-insurance map key that
 * surveyors used for building material: stone blue for a settled approval,
 * frame yellow for anything still provisional, brick red for a refusal,
 * iron grey for procedural business.
 */
export const OUTCOMES: Record<
  string,
  { label: string; material: string; short: string }
> = {
  approved: { label: "Approved", material: "stone", short: "App" },
  approved_with_conditions: {
    label: "Approved with conditions",
    material: "stone-hatched",
    short: "App+",
  },
  denied: { label: "Denied", material: "brick", short: "Den" },
  tabled: { label: "Tabled", material: "frame", short: "Tbl" },
  withdrawn: { label: "Withdrawn", material: "frame", short: "Wdn" },
  referred: { label: "Referred", material: "iron", short: "Ref" },
  adopted: { label: "Adopted", material: "iron", short: "Adt" },
  no_action: { label: "No action", material: "iron", short: "—" },
  mixed: { label: "Mixed", material: "mixed", short: "Mix" },
  other: { label: "Unclassified", material: "unknown", short: "?" },
};

export function outcomeMeta(outcome: string | null) {
  if (!outcome) return { label: "No decision recorded", material: "none", short: "—" };
  return OUTCOMES[outcome] ?? OUTCOMES.other;
}

export const DISTRICT_SHORT: Record<string, string> = {
  "Stockade Historic District": "Stockade",
  "Fair Street Historic District": "Fair St",
  "Chestnut Street Historic District": "Chestnut St",
  "Rondout Historic District": "Rondout",
  "Wilbur Historic District": "Wilbur",
  "Montrepose Historic District": "Montrepose",
  "Kingston Heritage Area": "Heritage Area",
};

/**
 * Prefix an internal path with the configured base. GitHub project pages serve
 * this site from /kingston-historic-data/, so a bare "/meetings/" would 404.
 * Astro rewrites neither hrefs nor fetches, so every internal link goes
 * through here.
 */
const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");

export function href(path: string) {
  return `${BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

/** Strip the base off a pathname so nav highlighting compares like for like. */
export function localPath(pathname: string) {
  const stripped = pathname.startsWith(BASE) ? pathname.slice(BASE.length) : pathname;
  return stripped || "/";
}

// Same street vocabulary the parser uses, so the address is stripped off a
// heading in full — cutting before the suffix left titles reading
// "Street Replacement of roofing on main house".
const STREET_SUFFIX =
  "St(?:reet)?|Ave(?:nue)?|Rd|Road|Blvd|Boulevard|Ln|Lane|Pl(?:ace)?|Ct|Court" +
  "|Dr(?:ive)?|Ter(?:race)?|Way|Sq(?:uare)?|Alley|Row|Broadway|Strand|Circle";

const ADDRESS_PREFIX = new RegExp(
  `^#?\\s*\\d[\\d\\-–/&\\s]*\\s*` +
    `(?:[A-Z][A-Za-z'.]*\\s+){0,3}(?:${STREET_SUFFIX})\\.?` +
    `\\s*[:\\-–—]?\\s*`,
  "i",
);

/** The heading minus the address, i.e. what the applicant asked to do. */
export function workDescription(title: string, address: string | null) {
  if (!address) return null;
  const stripped = title.replace(ADDRESS_PREFIX, "").trim();
  return stripped && stripped !== title ? stripped : null;
}

export function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

/**
 * Properties are keyed by tax parcel where the minutes record one, because an
 * SBL survives the address changes and spelling drift that a street name does
 * not. Items with no SBL fall back to their normalized address.
 */
export type Property = {
  slug: string;
  sbl: string | null;
  address: string;
  addresses: string[];
  districts: string[];
  ward: number | null;
  entries: Entry[];
};

export const properties: Property[] = (() => {
  const groups = new Map<string, Entry[]>();
  for (const entry of entries) {
    if (!entry.address && !entry.sbl) continue;
    const key = entry.sbl ? `sbl:${entry.sbl}` : `addr:${slugify(entry.address!)}`;
    const bucket = groups.get(key);
    if (bucket) bucket.push(entry);
    else groups.set(key, [entry]);
  }

  return [...groups.entries()]
    .map(([key, group]) => {
      const addresses = [
        ...new Set(group.map((e) => e.address).filter(Boolean) as string[]),
      ];
      // The most recently minuted spelling wins as the display address.
      const address = addresses[0] ?? group[0].sbl ?? key;
      return {
        slug: key.startsWith("sbl:")
          ? slugify(key.slice(4))
          : slugify(address),
        sbl: group.find((e) => e.sbl)?.sbl ?? null,
        address,
        addresses,
        districts: [...new Set(group.flatMap((e) => e.districts))],
        ward: group.find((e) => e.ward !== null)?.ward ?? null,
        entries: group,
      };
    })
    .sort((a, b) => b.entries.length - a.entries.length || a.address.localeCompare(b.address));
})();

export const propertyBySlug = new Map(properties.map((p) => [p.slug, p]));

export function propertyFor(entry: Entry) {
  if (entry.sbl) return propertyBySlug.get(slugify(entry.sbl));
  if (entry.address) return propertyBySlug.get(slugify(entry.address));
  return undefined;
}

function tally(values: string[]) {
  const counts = new Map<string, number>();
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

export const stats = {
  meetings: meetings.length,
  items: entries.length,
  decisions: entries.reduce((sum, e) => sum + e.decisions.length, 0),
  decided: entries.filter((e) => e.outcome).length,
  properties: properties.length,
  firstDate: meetings[meetings.length - 1]?.date,
  lastDate: meetings[0]?.date,
  outcomes: tally(entries.map((e) => e.outcome).filter(Boolean) as string[]),
  categories: tally(entries.flatMap((e) => e.categories)),
  districts: tally(entries.flatMap((e) => e.districts)),
  wards: tally(entries.map((e) => e.ward).filter((w) => w !== null).map(String)),
  years: tally(meetings.map((m) => m.date.slice(0, 4))).sort((a, b) =>
    a[0].localeCompare(b[0]),
  ),
};

/* ---------------------------------------------------------------------------
   Agendas

   An agenda item is a matter due to be heard. It carries every field a decided
   item has except the outcome, so it is kept separate and given a status —
   counting "not yet heard" as an outcome would corrupt the approval figures.
--------------------------------------------------------------------------- */

export type AgendaItem = {
  id: string;
  number: number;
  title: string;
  address: string | null;
  sbl: string | null;
  seqr: string | null;
  ward: number | null;
  zone: string | null;
  districts: string[];
  applicant: string | null;
  owner: string | null;
  project_url: string | null;
  categories: string[];
  detail: string | null;
};

export type Agenda = {
  id: string;
  date: string;
  source_url: string;
  source_file: string;
  status: "scheduled" | "awaiting_minutes" | "heard";
  comment_deadline: string | null;
  location: string | null;
  start_time: string | null;
  meeting_type: string;
  items: AgendaItem[];
};

export const agendas = (agendaData as unknown as Agenda[])
  .slice()
  .sort((a, b) => b.date.localeCompare(a.date));

/** Meetings whose agenda is published but which have not been held yet. */
export const upcoming = agendas
  .filter((a) => a.status === "scheduled")
  .sort((a, b) => a.date.localeCompare(b.date));

export const nextMeeting = upcoming[0] ?? null;

/** Scheduled matters at a given parcel, so a property page can show what is
 *  coming as well as what has already been decided. */
export function scheduledFor(sbl: string | null, address: string | null) {
  const key = sbl?.replace(/\s+/g, "");
  const out: Array<{ agenda: Agenda; item: AgendaItem }> = [];
  for (const agenda of upcoming) {
    for (const item of agenda.items) {
      const sameParcel = key && item.sbl?.replace(/\s+/g, "") === key;
      const sameAddress =
        !key && address && item.address && item.address.toLowerCase() === address.toLowerCase();
      if (sameParcel || sameAddress) out.push({ agenda, item });
    }
  }
  return out;
}

/* ---------------------------------------------------------------------------
   Geography

   Parcels are joined to the minutes on SBL, so a point sits on the actual tax
   lot rather than wherever a geocoder guessed the street number falls.
--------------------------------------------------------------------------- */

export type Parcel = {
  sbl: string;
  address: string | null;
  lat: number;
  lon: number;
  ring: [number, number][];
};

export const parcels = parcelData as unknown as Record<string, Parcel>;
export const boundary = boundaryData as unknown as {
  name: string;
  rings: [number, number][][];
};

/**
 * Links out to Google's street-level imagery for a property. Deliberately a
 * link and not an embed: these are private homes, the site is public, and
 * Google's terms forbid caching their imagery. Nothing is stored or
 * republished here — the coordinates come from the parcel roll and Google
 * serves whatever it has.
 */
export function streetViewUrl(lat: number, lon: number) {
  return `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${lat},${lon}`;
}

export function mapUrl(lat: number, lon: number) {
  return `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;
}

/** Without a parcel there are no coordinates, so fall back to the address. */
export function addressSearchUrl(address: string) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
    `${address}, Kingston, NY`,
  )}`;
}

/** Minutes spell SBLs loosely; the parcel roll has no spaces. */
export function parcelFor(sbl: string | null | undefined) {
  if (!sbl) return undefined;
  return parcels[sbl.replace(/\s+/g, "")];
}

export type MappedProperty = Property & { parcel: Parcel };

export const mappedProperties: MappedProperty[] = properties
  .map((property) => {
    const parcel = parcelFor(property.sbl);
    return parcel ? { ...property, parcel } : null;
  })
  .filter(Boolean) as MappedProperty[];

/**
 * Equirectangular projection. Over a city three kilometres across the
 * distortion is far below a pixel, and it keeps the map a plain SVG path with
 * no projection library.
 */
export function makeProjection(width: number, padding = 14) {
  const points = boundary.rings.flat();
  const lons = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  const [minLon, maxLon] = [Math.min(...lons), Math.max(...lons)];
  const [minLat, maxLat] = [Math.min(...lats), Math.max(...lats)];
  const stretch = Math.cos(((minLat + maxLat) / 2) * (Math.PI / 180));

  const spanX = (maxLon - minLon) * stretch;
  const spanY = maxLat - minLat;
  const scale = (width - padding * 2) / spanX;
  const height = spanY * scale + padding * 2;

  const project = (lon: number, lat: number): [number, number] => [
    padding + (lon - minLon) * stretch * scale,
    padding + (maxLat - lat) * scale,
  ];

  const path = (ring: [number, number][]) =>
    ring
      .map((point, index) => {
        const [x, y] = project(point[0], point[1]);
        return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join("") + "Z";

  return { project, path, width, height: Math.round(height) };
}

/* ---------------------------------------------------------------------------
   Reading the verbatim text

   The PDF text layer wraps lines at the column edge, so a paragraph arrives as
   a dozen fragments and renders as a wall. Rejoin the wrapped lines, break on
   the blank lines and list markers the clerk actually typed, and the passage
   reads the way it does on the page.
--------------------------------------------------------------------------- */

export type Block =
  | { type: "p"; text: string }
  | { type: "list"; ordered: boolean; items: string[] };

const LIST_MARKER = /^\s*(?:(\d{1,2})[\).]|([a-z])[\)]|[-•*–])\s+/i;
// A wrapped line continues the sentence before it; a finished one ends in
// terminal punctuation.
const SENTENCE_END = /[.:;!?]["')\]]?\s*$/;

export function passage(text: string | null | undefined): Block[] {
  if (!text) return [];
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "p", text: paragraph.join(" ").replace(/\s+/g, " ").trim() });
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list && list.items.length) blocks.push({ type: "list", ...list });
    list = null;
  };

  for (const raw of text.split(/\n/)) {
    const line = raw.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }

    const marker = line.match(LIST_MARKER);
    if (marker) {
      flushParagraph();
      const ordered = Boolean(marker[1] || marker[2]);
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push(line.slice(marker[0].length).trim());
      continue;
    }

    if (list) {
      // An unmarked line under a list is the tail of the previous item.
      list.items[list.items.length - 1] += ` ${line}`;
      continue;
    }

    paragraph.push(line);
    // Keep paragraphs from running on: break after a finished sentence when the
    // line stops well short of the column width.
    if (SENTENCE_END.test(line) && line.length < 70) flushParagraph();
  }

  flushParagraph();
  flushList();
  return blocks;
}

export function formatDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function formatDateShort(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
