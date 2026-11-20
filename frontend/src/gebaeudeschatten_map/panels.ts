// The swatches of Gebäudeschatten's layer box and the colour key below the
// cells row. Colours go through the CSSOM and labels are text.

import type { CellsKeyEntry } from "@/gebaeudeschatten_map/args";
import { swatch } from "@/shared/layer-box";
import type { OutlineOverlay } from "@/shared/outline-overlays";

const SWATCH = "legend-swatch";

export function outlineSwatch(ov: OutlineOverlay): HTMLElement {
  return swatch(SWATCH, {
    border: `2px ${ov.dash ? "dashed" : "solid"} ${ov.color}`,
    ...(ov.fill ? { background: ov.fill } : {}),
  });
}

export function fillSwatch(background: string, border = ""): HTMLElement {
  return swatch(SWATCH, { background, border });
}

/** The first three key colours as equal stripes, e.g. "#a 0% 33%,#b 33% 66%,…". */
export function stripes(key: readonly CellsKeyEntry[]): string {
  const stops = key
    .slice(0, 3)
    .map((k, i) => `${k.color} ${String(i * 33)}% ${String((i + 1) * 33)}%`);
  return `linear-gradient(to right,${stops.join(",")})`;
}

/** Shows the cells' colour key right below `row`, or hides it. */
export function showCellsKey(
  row: HTMLElement | null,
  key: readonly CellsKeyEntry[],
  shown: boolean,
): void {
  const box = document.getElementById("cells-legend");
  if (!box) throw new Error("gebaeudeschatten_map: #cells-legend is missing from index.html");
  row?.after(box);
  box.replaceChildren(
    ...key.map((k) => {
      const entry = document.createElement("div");
      entry.className = "cl-row";
      const label = document.createElement("span");
      label.textContent = k.label;
      entry.append(swatch(SWATCH, { background: k.color }), label);
      return entry;
    }),
  );
  box.hidden = !(shown && key.length > 0);
}
