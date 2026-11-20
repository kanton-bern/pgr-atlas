// The texts a map component shows and the locale of its numbers. Python sends
// both in the render args (`labels`, `locale`), filled from app/texts.toml, so
// the components hold no UI text of their own. A rerun can change them (a
// language switch): the component then updates its texts in place, and the
// map, its view and the selection stay.

export const LOCALES = ["de-CH", "fr-CH"] as const;
export type Locale = (typeof LOCALES)[number];

/** A component's texts by key. A text may hold `{name}` placeholders (see fill). */
export type Labels<K extends string> = Readonly<Record<K, string>>;

/** The render args every map component takes for its texts. */
export interface TextArgs {
  labels: Record<string, unknown>;
  locale: string;
}

/** What the shared parts read: the current texts, and a hook for when they change. */
export interface TextSource<K extends string> {
  readonly labels: Labels<K>;
  readonly locale: Locale;
  /** Runs `apply` now and again after every change of the texts or the locale. */
  bind(apply: () => void): void;
}

const PLACEHOLDER = /\{([a-z_][a-z0-9_]*)\}/g;

/**
 * `template` with each `{name}` replaced by `values[name]`, like Python's
 * ui_text.t(). Any other brace is a literal character. A placeholder without
 * a value is a bug in the caller, so it throws.
 */
export function fill(template: string, values: Readonly<Record<string, string | number>>): string {
  return template.replace(PLACEHOLDER, (whole, name: string) => {
    const value = values[name];
    if (value === undefined) throw new Error(`text "${template}" needs a value for {${name}}`);
    return String(value);
  });
}

function checkLocale(locale: unknown): Locale {
  const known: readonly unknown[] = LOCALES;
  if (known.includes(locale)) return locale as Locale;
  throw new Error(
    `render arg "locale" is ${JSON.stringify(locale)}; expected one of ${LOCALES.join(", ")}`,
  );
}

/**
 * `labels` as the component's texts. Python must send exactly the component's
 * keys, each a string: a missing or extra key is a bug in the Python wrapper
 * (app/*_component.py), so it throws and names every such key.
 */
export function checkLabels<K extends string>(keys: readonly K[], labels: unknown): Labels<K> {
  if (typeof labels !== "object" || labels === null) {
    throw new Error(
      'render arg "labels" is missing: the Python wrapper must send the map\'s texts',
    );
  }
  const given = labels as Record<string, unknown>;
  const expected = new Set<string>(keys);
  const missing = keys.filter((k) => typeof given[k] !== "string");
  const extra = Object.keys(given).filter((k) => !expected.has(k));
  if (missing.length || extra.length) {
    throw new Error(
      `render arg "labels" does not match the component: ` +
        `missing or not a string: [${missing.join(", ")}], unknown: [${extra.join(", ")}]`,
    );
  }
  return given as Labels<K>;
}

/** The texts of one component instance, updated by each render. */
export class UiTexts<K extends string> implements TextSource<K> {
  labels: Labels<K>;
  locale: Locale;
  private readonly listeners: (() => void)[] = [];
  private key: string;

  constructor(
    private readonly keys: readonly K[],
    args: TextArgs,
  ) {
    this.labels = checkLabels(keys, args.labels);
    this.locale = checkLocale(args.locale);
    this.key = JSON.stringify([this.locale, this.labels]);
  }

  bind(apply: () => void): void {
    this.listeners.push(apply);
    apply();
  }

  /** Takes a render's texts; the bound parts run only if something changed. */
  update(args: TextArgs): void {
    const labels = checkLabels(this.keys, args.labels);
    const locale = checkLocale(args.locale);
    const key = JSON.stringify([locale, labels]);
    if (key === this.key) return;
    this.labels = labels;
    this.locale = locale;
    this.key = key;
    for (const apply of this.listeners) apply();
  }
}

/** The label `key`; index.html naming a key the component doesn't have is a bug. */
export function labelOf(texts: TextSource<string>, key: string): string {
  const text = texts.labels[key];
  if (text === undefined) throw new Error(`index.html names label "${key}", which isn't one`);
  return text;
}

/**
 * Fills index.html's static texts, now and on every change: an element with
 * `data-text="key"` shows the label `key`.
 */
export function bindDataTexts(root: ParentNode, texts: TextSource<string>): void {
  texts.bind(() => {
    root.querySelectorAll<HTMLElement>("[data-text]").forEach((el) => {
      el.textContent = labelOf(texts, el.dataset.text ?? "");
    });
  });
}
