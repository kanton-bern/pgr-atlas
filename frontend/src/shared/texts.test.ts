import { describe, expect, it } from "vitest";

import { checkLabels, fill, UiTexts } from "@/shared/texts";

describe("fill", () => {
  it("replaces each named placeholder, numbers included", () => {
    expect(fill("Anriss {id} · {area} m²", { id: 7, area: "1'100" })).toBe("Anriss 7 · 1'100 m²");
  });

  it("keeps braces that are no placeholder", () => {
    expect(fill("{label} [{unit}] {-80} {Ab}", { label: "Tiefe", unit: "m" })).toBe(
      "Tiefe [m] {-80} {Ab}",
    );
  });

  it("throws for a placeholder without a value", () => {
    expect(() => fill("Zoomstufe = {zoom}", {})).toThrow(/needs a value for \{zoom\}/);
  });
});

describe("checkLabels", () => {
  const keys = ["close", "layers"] as const;

  it("accepts exactly the component's keys", () => {
    const labels = { close: "Schliessen", layers: "Layer" };
    expect(checkLabels(keys, labels)).toBe(labels);
  });

  it("names every missing, non-string and unknown key", () => {
    expect(() => checkLabels(keys, { close: 3, legend: "Legende" })).toThrow(
      /missing or not a string: \[close, layers\], unknown: \[legend\]/,
    );
  });

  it("rejects labels that aren't an object", () => {
    expect(() => checkLabels(keys, undefined)).toThrow(/"labels" is missing/);
    expect(() => checkLabels(keys, null)).toThrow(/"labels" is missing/);
  });
});

describe("UiTexts", () => {
  const keys = ["close"] as const;
  const de = { labels: { close: "Schliessen" }, locale: "de-CH" };
  const fr = { labels: { close: "Fermer" }, locale: "fr-CH" };

  it("runs a bound part at once and after each change, not for the same texts", () => {
    const texts = new UiTexts(keys, de);
    const seen: string[] = [];
    texts.bind(() => seen.push(`${texts.locale} ${texts.labels.close}`));
    texts.update({ labels: { close: "Schliessen" }, locale: "de-CH" });
    texts.update(fr);
    texts.update(fr);
    expect(seen).toEqual(["de-CH Schliessen", "fr-CH Fermer"]);
  });

  it("follows a change of the locale alone", () => {
    const texts = new UiTexts(keys, de);
    let runs = 0;
    texts.bind(() => runs++);
    texts.update({ ...de, locale: "fr-CH" });
    expect(runs).toBe(2);
    expect(texts.locale).toBe("fr-CH");
  });

  it("rejects an unknown locale and keeps the texts it has", () => {
    expect(() => new UiTexts(keys, { ...de, locale: "it-CH" })).toThrow(/"locale" is "it-CH"/);
    const texts = new UiTexts(keys, de);
    expect(() => {
      texts.update({ labels: {}, locale: "fr-CH" });
    }).toThrow(/missing/);
    expect(texts.labels.close).toBe("Schliessen");
  });
});
