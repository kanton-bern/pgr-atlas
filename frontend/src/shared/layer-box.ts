// The rows of the layer box (#layer-rows, top left) for layers that come and
// go with the render args: a checkbox, a swatch and a label per layer, and
// for a raster layer an opacity slider below its row.
//
// Each render passes the server's default visibility. A row follows it until
// the user ticks the row's checkbox; from then on the user's choice holds,
// until the view calls reset() (a new raster shows itself again).

import type { Map as MapLibreMap } from "maplibre-gl";

import {
  OPACITY_STEP_PERCENT,
  type OpacityMemory,
  opacityPercent,
  pageOpacityMemory,
  type RasterStyle,
  styleLayers,
} from "./raster-opacity";
import { fill, type TextSource } from "./texts";

/** The labels of the opacity slider. */
export const RASTER_OPACITY_LABELS = ["opacity", "opacity_aria", "opacity_value"] as const;
export type OpacityTexts = TextSource<(typeof RASTER_OPACITY_LABELS)[number]>;

/** The opacity slider of a raster layer's row. */
export interface OpacitySlider {
  /** The user's choice is remembered for the page under this key. */
  memoryKey: string;
  /** The opacity until the user moves the slider, in percent. */
  defaultPercent: number;
}

export interface LayerRow {
  label: string;
  swatch: HTMLElement;
  /** The map layers the checkbox shows and hides. */
  layers: readonly string[];
  /** The server's default, until the user ticks the checkbox. */
  visible: boolean;
  /** False hides the row and its layers, e.g. while the layer has no data. */
  shown: boolean;
  /** Raster layers only: a slider for their `raster-opacity`. */
  opacity?: OpacitySlider;
}

interface Slider {
  element: HTMLLabelElement;
  input: HTMLInputElement;
  readout: HTMLSpanElement;
  memoryKey: string;
  percent: number;
}

interface Row {
  element: HTMLLabelElement;
  checkbox: HTMLInputElement;
  layers: readonly string[];
  label: string;
  touched: boolean;
  slider: Slider | null;
}

export class LayerBox {
  private readonly rows = new Map<string, Row>();

  /**
   * `onToggle` runs after the user ticks a checkbox. `texts` labels the
   * opacity sliders; a box with a raster row needs them.
   */
  constructor(
    private readonly map: MapLibreMap,
    private readonly onToggle: (id: string, visible: boolean) => void = () => undefined,
    private readonly texts: OpacityTexts | null = null,
    private readonly memory: OpacityMemory = pageOpacityMemory(),
  ) {}

  /** Adds or updates the row of layer `id`; a new row goes below the others. */
  set(id: string, spec: LayerRow): void {
    const row = this.rows.get(id) ?? this.create(id);
    row.layers = spec.layers;
    row.label = spec.label;
    row.element.replaceChildren(row.checkbox, spec.swatch, rowLabel(spec.label));
    row.element.hidden = !spec.shown;
    if (!row.touched) row.checkbox.checked = spec.visible;
    if (spec.opacity) row.slider ??= this.createSlider(row, spec.opacity);
    this.showSlider(row);
    this.apply(row);
  }

  /** Hides the row of layer `id` and its layers, if it has one. */
  hide(id: string): void {
    const row = this.rows.get(id);
    if (!row) return;
    row.element.hidden = true;
    this.showSlider(row);
    this.apply(row);
  }

  /** Lets the row follow the server's default again from the next set(). */
  reset(id: string): void {
    const row = this.rows.get(id);
    if (row) row.touched = false;
  }

  /** Whether the row's checkbox is ticked; true for a layer without a row. */
  isChecked(id: string): boolean {
    return this.rows.get(id)?.checkbox.checked ?? true;
  }

  /**
   * How the raster layer of row `id` is drawn now. A layer without a row is
   * drawn as it is, opaque.
   */
  rasterStyle(id: string): RasterStyle {
    const row = this.rows.get(id);
    if (!row) return { visible: true, opacity: 1 };
    return { visible: isVisible(row), opacity: (row.slider?.percent ?? 100) / 100 };
  }

  /** The row's element, e.g. to put a colour key below it. */
  element(id: string): HTMLElement | null {
    return this.rows.get(id)?.element ?? null;
  }

  private create(id: string): Row {
    const element = document.createElement("label");
    element.className = "legend-row";
    element.id = `row-${id}`;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    const row: Row = { element, checkbox, layers: [], label: "", touched: false, slider: null };
    checkbox.addEventListener("change", () => {
      row.touched = true;
      this.showSlider(row);
      this.apply(row);
      this.onToggle(id, checkbox.checked);
    });
    const container = document.getElementById("layer-rows");
    if (!container) throw new Error("#layer-rows is missing from index.html");
    container.appendChild(element);
    this.rows.set(id, row);
    return row;
  }

  /** The slider below `row`: a label, a range input and the value in percent. */
  private createSlider(row: Row, spec: OpacitySlider): Slider {
    const texts = this.texts;
    if (!texts) throw new Error("LayerBox: a row with an opacity slider needs the box's texts");
    const element = document.createElement("label");
    element.className = "legend-opacity";
    element.id = `${row.element.id}-opacity`;
    const title = document.createElement("span");
    title.className = "legend-opacity-title";
    const input = document.createElement("input");
    input.type = "range";
    input.min = "0";
    input.max = "100";
    input.step = String(OPACITY_STEP_PERCENT);
    const readout = document.createElement("span");
    readout.className = "legend-opacity-value";
    readout.setAttribute("aria-hidden", "true");
    element.replaceChildren(title, input, readout);
    row.element.after(element);

    const remembered = this.memory.get(spec.memoryKey);
    const percent = opacityPercent(remembered ?? spec.defaultPercent, spec.defaultPercent);
    const slider: Slider = { element, input, readout, memoryKey: spec.memoryKey, percent };
    input.value = String(percent);
    input.addEventListener("input", () => {
      slider.percent = opacityPercent(input.value, slider.percent);
      this.memory.set(slider.memoryKey, slider.percent);
      this.labelSlider(row, slider, texts);
      this.apply(row);
    });
    texts.bind(() => {
      title.textContent = texts.labels.opacity;
      this.labelSlider(row, slider, texts);
    });
    return slider;
  }

  private labelSlider(row: Row, slider: Slider, texts: OpacityTexts): void {
    const value = fill(texts.labels.opacity_value, { percent: slider.percent });
    slider.readout.textContent = value;
    slider.input.setAttribute("aria-label", fill(texts.labels.opacity_aria, { label: row.label }));
    slider.input.setAttribute("aria-valuetext", value);
  }

  /** The slider shows with its row and is disabled while the layer is off. */
  private showSlider(row: Row): void {
    const slider = row.slider;
    if (!slider) return;
    slider.element.hidden = row.element.hidden;
    slider.input.disabled = !row.checkbox.checked;
    slider.element.classList.toggle("legend-opacity--off", !row.checkbox.checked);
    if (this.texts) this.labelSlider(row, slider, this.texts);
  }

  private apply(row: Row): void {
    const opacity = row.slider ? row.slider.percent / 100 : undefined;
    styleLayers(this.map, row.layers, isVisible(row), opacity);
  }
}

/** A row's layers show while the row is shown and its checkbox ticked. */
function isVisible(row: Row): boolean {
  return !row.element.hidden && row.checkbox.checked;
}

function rowLabel(text: string): HTMLSpanElement {
  const span = document.createElement("span");
  span.className = "row-label";
  span.textContent = text;
  return span;
}

/** A swatch element of `className`, styled through the CSSOM (never as HTML). */
export function swatch(className: string, style: Partial<CSSStyleDeclaration>): HTMLDivElement {
  const el = document.createElement("div");
  el.className = className;
  Object.assign(el.style, style);
  return el;
}
