// The value legend (bottom centre) and the variable switch (top left) of the
// Anriss view's map. Every value is set as text.

import type { ValueLegend, Variable } from "@/anriss_map/args";
import { setPressed } from "@/shared/pressed";

function element(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`anriss_map: #${id} is missing from index.html`);
  return el;
}

export function showValueLegend(legend: ValueLegend | null): void {
  const box = element("value-legend");
  if (!legend) {
    box.hidden = true;
    return;
  }
  element("vl-title").textContent = legend.title;
  element("vl-bar").style.background = `linear-gradient(to right, ${legend.gradient})`;
  element("vl-min").textContent = legend.vmin_label;
  element("vl-mid").textContent = legend.vmid_label;
  element("vl-max").textContent = legend.vmax_label;
  box.hidden = false;
}

/**
 * One button per variable, `active` marked. A click marks its button right
 * away and calls `onPick`; Python reruns with that variable's cells.
 */
export function showVariableButtons(
  variables: readonly Variable[],
  active: string,
  onPick: (key: string) => void,
): void {
  const box = element("var-btns");
  const buttons = variables.map((v) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "var-btn";
    setPressed(btn, v.key === active);
    btn.dataset.var = v.key;
    btn.textContent = v.label;
    btn.addEventListener("click", () => {
      if (btn.classList.contains("active")) return;
      for (const other of buttons) setPressed(other, other === btn);
      onPick(v.key);
    });
    return btn;
  });
  box.replaceChildren(...buttons);
}
