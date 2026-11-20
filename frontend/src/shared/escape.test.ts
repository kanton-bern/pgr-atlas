import { describe, expect, it } from "vitest";

import { escapeHtml } from "./escape";

describe("escapeHtml", () => {
  it("escapes the five HTML-special characters", () => {
    expect(escapeHtml(`<img src=x onerror="a('b')">&`)).toBe(
      "&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt;&amp;",
    );
  });

  it("leaves plain text, umlauts and numbers unchanged", () => {
    expect(escapeHtml("Prozessquelle Grünbach")).toBe("Prozessquelle Grünbach");
    expect(escapeHtml(4711)).toBe("4711");
    expect(escapeHtml("")).toBe("");
  });

  it("escapes an already escaped entity again", () => {
    expect(escapeHtml("&lt;")).toBe("&amp;lt;");
  });
});
