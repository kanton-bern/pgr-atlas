// Values from tiles, render args or files go into popup and legend HTML only
// through escapeHtml.

const ENTITIES: Readonly<Record<string, string>> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/** Returns `value` as text that is safe inside HTML content and quoted attributes. */
export function escapeHtml(value: string | number): string {
  return String(value).replace(/[&<>"']/g, (c) => ENTITIES[c] ?? c);
}
