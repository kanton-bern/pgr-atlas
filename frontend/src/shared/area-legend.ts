// The area-class filter in the layer box of the overview and IFK maps: one
// checkbox row per Anrissfläche class, and "Alle · Keine" next to its title,
// which tick or untick every class at once.

import { AREA_CLASSES } from "@/shared/anriss-areas";
import type { TextSource } from "@/shared/texts";

/** The labels of the "Alle · Keine" buttons (app/map_labels.py, AREA_CLASSES). */
export const AREA_LEGEND_LABELS = [
  "area_classes_all",
  "area_classes_none",
  "area_classes_all_aria",
  "area_classes_none_aria",
] as const;

type AreaLegendLabelKey = (typeof AREA_LEGEND_LABELS)[number];

export interface AreaLegendOptions {
  /** Takes the checkbox rows. */
  rows: HTMLElement;
  /** Takes the "Alle · Keine" buttons; it sits next to the filter's title. */
  allNoneButtons: HTMLElement;
  /** The ticked classes (m²); the legend changes it in place. */
  active: Set<number>;
  texts: TextSource<AreaLegendLabelKey>;
  /** Shows each class's colour in its row (the overview colours its circles by class). */
  showClassColors: boolean;
  /** Runs after every change of `active`, once per click. */
  onChange: () => void;
}

function linkButton(className: string): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `area-classes-link ${className}`;
  return button;
}

/** Builds the rows and the "Alle · Keine" buttons into the options' elements. */
export function buildAreaLegend(options: AreaLegendOptions): void {
  const { active, texts, onChange } = options;
  const checkboxes = new Map<number, HTMLInputElement>();
  for (const areaClass of AREA_CLASSES) {
    const row = document.createElement("label");
    row.className = "legend-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = active.has(areaClass.area);
    row.append(checkbox);
    if (options.showClassColors) {
      const dot = document.createElement("div");
      dot.className = "legend-dot";
      dot.style.background = areaClass.color;
      row.append(dot);
    }
    const text = document.createElement("span");
    text.textContent = areaClass.label;
    row.append(text);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) active.add(areaClass.area);
      else active.delete(areaClass.area);
      onChange();
    });
    options.rows.appendChild(row);
    checkboxes.set(areaClass.area, checkbox);
  }

  const setAll = (ticked: boolean) => {
    for (const [area, checkbox] of checkboxes) {
      checkbox.checked = ticked;
      if (ticked) active.add(area);
      else active.delete(area);
    }
    onChange();
  };
  const allButton = linkButton("area-classes-all");
  const noneButton = linkButton("area-classes-none");
  // A dot between the two, drawn by CSS: decoration, so screen readers skip it.
  const separator = document.createElement("span");
  separator.className = "area-classes-separator";
  separator.setAttribute("aria-hidden", "true");
  allButton.addEventListener("click", () => {
    setAll(true);
  });
  noneButton.addEventListener("click", () => {
    setAll(false);
  });
  texts.bind(() => {
    const { labels } = texts;
    allButton.textContent = labels.area_classes_all;
    allButton.setAttribute("aria-label", labels.area_classes_all_aria);
    noneButton.textContent = labels.area_classes_none;
    noneButton.setAttribute("aria-label", labels.area_classes_none_aria);
  });
  options.allNoneButtons.append(allButton, separator, noneButton);
}
