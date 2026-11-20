import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AREA_CLASSES, areaFilter, initialAreas } from "@/shared/anriss-areas";
import { AREA_LEGEND_LABELS, buildAreaLegend } from "@/shared/area-legend";
import type { Labels, TextSource } from "@/shared/texts";

type LabelKey = (typeof AREA_LEGEND_LABELS)[number];

/** A stand-in for the few element features the legend uses. */
class FakeElement {
  type = "";
  className = "";
  checked = false;
  textContent = "";
  readonly style: Record<string, string> = {};
  readonly children: FakeElement[] = [];
  readonly attributes = new Map<string, string>();
  private readonly listeners = new Map<string, () => void>();

  constructor(readonly tagName: string) {}

  append(...elements: FakeElement[]) {
    this.children.push(...elements);
  }
  appendChild(element: FakeElement) {
    this.children.push(element);
  }
  setAttribute(name: string, value: string) {
    this.attributes.set(name, value);
  }
  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, listener);
  }
  /** What a user's click or tick fires. */
  fire(type: string) {
    this.listeners.get(type)?.();
  }
}

const GERMAN: Labels<LabelKey> = {
  area_classes_all: "Alle",
  area_classes_none: "Keine",
  area_classes_all_aria: "Alle Grössenklassen anzeigen",
  area_classes_none_aria: "Alle Grössenklassen ausblenden",
};
const FRENCH: Labels<LabelKey> = {
  area_classes_all: "Toutes",
  area_classes_none: "Aucune",
  area_classes_all_aria: "Afficher toutes les classes de taille",
  area_classes_none_aria: "Masquer toutes les classes de taille",
};

/** Texts that switch language on `switchTo`, like UiTexts on a rerun. */
function fakeTexts(): TextSource<LabelKey> & { switchTo(labels: Labels<LabelKey>): void } {
  const listeners: (() => void)[] = [];
  const texts = {
    labels: GERMAN,
    locale: "de-CH" as const,
    bind(apply: () => void) {
      listeners.push(apply);
      apply();
    },
    switchTo(labels: Labels<LabelKey>) {
      texts.labels = labels;
      for (const apply of listeners) apply();
    },
  };
  return texts;
}

const ALL = AREA_CLASSES.map((c) => c.area);

function build(active: Set<number>, showClassColors = false) {
  const rows = new FakeElement("div");
  const allNoneButtons = new FakeElement("div");
  const texts = fakeTexts();
  const onChange = vi.fn();
  buildAreaLegend({
    rows: rows as unknown as HTMLElement,
    allNoneButtons: allNoneButtons as unknown as HTMLElement,
    active,
    texts,
    showClassColors,
    onChange,
  });
  const checkboxes = rows.children.map((row) => childAt(row, 0));
  return {
    rows,
    checkboxes,
    allButton: childAt(allNoneButtons, 0),
    separator: childAt(allNoneButtons, 1),
    noneButton: childAt(allNoneButtons, 2),
    texts,
    onChange,
  };
}

/** The element's child at `index`; a missing one fails the test. */
function childAt(element: FakeElement, index: number): FakeElement {
  const child = element.children[index];
  if (!child) throw new Error(`${element.tagName} has no child ${String(index)}`);
  return child;
}

const checkedStates = (checkboxes: FakeElement[]) => checkboxes.map((box) => box.checked);

beforeEach(() => {
  vi.stubGlobal("document", { createElement: (tag: string) => new FakeElement(tag) });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("buildAreaLegend", () => {
  it("builds one checkbox row per class, ticked as `active` says", () => {
    const { checkboxes } = build(new Set([55, 700]));
    expect(checkedStates(checkboxes)).toEqual([true, false, false, false, true, false]);
  });

  it("shows the class colours only when asked", () => {
    const withColors = childAt(build(new Set(ALL), true).rows, 0);
    expect(withColors.children.map((child) => child.className)).toEqual(["", "legend-dot", ""]);
    expect(childAt(withColors, 1).style.background).toBe(AREA_CLASSES[0]?.color);
    const withoutColors = childAt(build(new Set(ALL)).rows, 0);
    expect(withoutColors.children).toHaveLength(2);
  });

  it("'Keine' unticks every class and the filter then matches nothing", () => {
    const active = new Set([55, 700]);
    const { checkboxes, noneButton, onChange } = build(active);
    noneButton.fire("click");
    expect(checkedStates(checkboxes)).toEqual(Array(6).fill(false));
    expect(active.size).toBe(0);
    expect(areaFilter(active, "A")).toEqual(["==", ["get", "A"], -1]);
    expect(onChange).toHaveBeenCalledOnce();
  });

  it("'Alle' ticks every class and the filter then goes", () => {
    const active = new Set<number>();
    const { checkboxes, allButton, onChange } = build(active);
    allButton.fire("click");
    expect(checkedStates(checkboxes)).toEqual(Array(6).fill(true));
    expect([...active].sort((a, b) => a - b)).toEqual(ALL);
    expect(areaFilter(active, "A")).toBeNull();
    expect(onChange).toHaveBeenCalledOnce();
  });

  it("a checkbox still changes its one class", () => {
    const active = new Set(ALL);
    const { checkboxes, onChange } = build(active);
    const firstCheckbox = checkboxes[0];
    if (!firstCheckbox) throw new Error("no checkbox");
    firstCheckbox.checked = false;
    firstCheckbox.fire("change");
    expect(active.has(55)).toBe(false);
    expect(active.size).toBe(5);
    expect(onChange).toHaveBeenCalledOnce();
  });

  it("the buttons are real buttons with screen reader texts that follow the language", () => {
    const { allButton, separator, noneButton, texts } = build(new Set(ALL));
    expect([allButton.tagName, noneButton.tagName]).toEqual(["button", "button"]);
    expect([allButton.type, noneButton.type]).toEqual(["button", "button"]);
    expect(separator.attributes.get("aria-hidden")).toBe("true");
    expect([allButton.textContent, noneButton.textContent]).toEqual(["Alle", "Keine"]);
    expect(allButton.attributes.get("aria-label")).toBe("Alle Grössenklassen anzeigen");

    texts.switchTo(FRENCH);
    expect([allButton.textContent, noneButton.textContent]).toEqual(["Toutes", "Aucune"]);
    expect(noneButton.attributes.get("aria-label")).toBe("Masquer toutes les classes de taille");
  });

  it("'Keine' survives the round trip through Python (the value it sends back mounts as none)", () => {
    const active = new Set(ALL);
    build(active).noneButton.fire("click");
    const sentToPython = [...active];
    expect(initialAreas(sentToPython).size).toBe(0);
  });
});
