import type { Provenance } from "@/lib/types";

// A metric is never shown without saying where it came from. This badge is the
// visible half of Rule 2 (no fake dashboards): observed data reads differently
// from inferred, and synthetic demonstration data is unmistakable.

const STYLES: Record<Provenance, { label: string; className: string; title: string }> = {
  observed: {
    label: "measured",
    className: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
    title: "Measured from a connected provider or an actual crawl.",
  },
  user_provided: {
    label: "you provided",
    className: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    title: "Supplied by you as part of the brand's own data.",
  },
  inferred: {
    label: "inferred",
    className: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    title: "Derived from observed data, not measured directly.",
  },
  estimated: {
    label: "estimated",
    className: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    title: "An estimate, not a measurement.",
  },
  synthetic_demo: {
    label: "synthetic demo",
    className: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40",
    title:
      "Synthetic demonstration data from a development adapter. Not a measurement of this business.",
  },
  unknown: {
    label: "not measured",
    className: "bg-slate-500/15 text-slate-300 border-slate-500/30",
    title: "The platform could not measure this. No value has been estimated.",
  },
};

export function Provenance({ value }: { value: Provenance }) {
  const style = STYLES[value] ?? STYLES.unknown;
  return (
    <span
      title={style.title}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${style.className}`}
    >
      {style.label}
    </span>
  );
}

// A measured value with its provenance, or an honest "not measured" when the
// value is null — never a zero or a dash standing in for a real figure.
export function Metric({
  value,
  provenance,
  unit,
  source,
}: {
  value: number | null;
  provenance: Provenance;
  unit?: string | null;
  source?: string | null;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      {value === null ? (
        <span className="text-text-dim">not measured</span>
      ) : (
        <span className="font-semibold tabular-nums">
          {value.toLocaleString()}
          {unit ? ` ${unit}` : ""}
        </span>
      )}
      <Provenance value={provenance} />
      {source ? <span className="text-xs text-text-dim">· {source}</span> : null}
    </span>
  );
}
