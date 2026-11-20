/**
 * Marks a toggle button on or off: the .active class for the look, and
 * aria-pressed so a screen reader says the same.
 */
export function setPressed(btn: Pick<HTMLElement, "classList" | "setAttribute">, on: boolean) {
  btn.classList.toggle("active", on);
  btn.setAttribute("aria-pressed", String(on));
}
