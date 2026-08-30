import raw from "../../data/decisions.json";

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
