import { describe, expect, it, vi } from "vitest";

import { PopoverGroup } from "./popover";
import { setPressed } from "./pressed";

type Listener = (e: { key?: string; target?: unknown }) => void;

/** A stand-in for an element: attributes, listeners, focus, containment. */
class FakeElement {
  hidden = false;
  readonly attrs = new Map<string, string>();
  readonly listeners = new Map<string, Listener>();
  readonly children = new Set<unknown>();

  constructor(
    readonly id: string,
    private readonly doc: FakeDocument,
  ) {}

  setAttribute(name: string, value: string) {
    this.attrs.set(name, value);
  }
  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, listener);
  }
  focus() {
    this.doc.activeElement = this;
  }
  contains(node: unknown) {
    return node === this || this.children.has(node);
  }
  click() {
    this.listeners.get("click")?.({});
  }
}

class FakeDocument {
  activeElement: unknown = null;
  readonly listeners = new Map<string, Listener>();
  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, listener);
  }
  key(key: string) {
    this.listeners.get("keydown")?.({ key });
  }
  pointerDown(target: unknown) {
    this.listeners.get("pointerdown")?.({ target });
  }
}

function setup() {
  const doc = new FakeDocument();
  const group = new PopoverGroup(doc);
  const make = (name: string) => {
    const trigger = new FakeElement(`${name}-toggle`, doc);
    const panel = new FakeElement(`${name}-panel`, doc);
    const field = new FakeElement(`${name}-field`, doc);
    panel.children.add(field);
    const place = vi.fn();
    const popover = group.add({
      trigger,
      panel,
      place,
      initialFocus: () => field,
    });
    return { trigger, panel, field, place, popover };
  };
  return { doc, search: make("search"), basemap: make("basemap") };
}

describe("PopoverGroup", () => {
  it("starts closed, and the trigger names its panel", () => {
    const { search } = setup();
    expect(search.panel.hidden).toBe(true);
    expect(search.trigger.attrs.get("aria-expanded")).toBe("false");
    expect(search.trigger.attrs.get("aria-controls")).toBe("search-panel");
  });

  it("opens on a trigger click, places the panel and focuses its first control", () => {
    const { doc, search } = setup();
    search.trigger.click();
    expect(search.panel.hidden).toBe(false);
    expect(search.trigger.attrs.get("aria-expanded")).toBe("true");
    expect(search.place).toHaveBeenCalledOnce();
    expect(doc.activeElement).toBe(search.field);
  });

  it("closes on a second trigger click", () => {
    const { search } = setup();
    search.trigger.click();
    search.trigger.click();
    expect(search.panel.hidden).toBe(true);
    expect(search.trigger.attrs.get("aria-expanded")).toBe("false");
  });

  it("closes on Escape and returns focus to the trigger", () => {
    const { doc, search } = setup();
    search.trigger.click();
    doc.key("Escape");
    expect(search.popover.isOpen).toBe(false);
    expect(search.panel.hidden).toBe(true);
    expect(doc.activeElement).toBe(search.trigger);
  });

  it("ignores other keys and Escape while nothing is open", () => {
    const { doc, search } = setup();
    doc.key("Escape");
    expect(doc.activeElement).toBeNull();
    search.trigger.click();
    doc.key("Enter");
    expect(search.popover.isOpen).toBe(true);
  });

  it("keeps one panel open at a time", () => {
    const { search, basemap } = setup();
    search.trigger.click();
    basemap.trigger.click();
    expect(search.panel.hidden).toBe(true);
    expect(search.trigger.attrs.get("aria-expanded")).toBe("false");
    expect(basemap.panel.hidden).toBe(false);
  });

  it("closes on a press outside, without moving focus", () => {
    const { doc, search } = setup();
    search.trigger.click();
    const elsewhere = {};
    doc.activeElement = elsewhere;
    doc.pointerDown(elsewhere);
    expect(search.popover.isOpen).toBe(false);
    expect(doc.activeElement).toBe(elsewhere);
  });

  it("stays open on a press inside its panel or on its trigger", () => {
    const { doc, search } = setup();
    search.trigger.click();
    doc.pointerDown(search.field);
    doc.pointerDown(search.trigger);
    expect(search.popover.isOpen).toBe(true);
  });
});

describe("setPressed", () => {
  it("sets the class and aria-pressed together", () => {
    const classes = new Set<string>();
    const attrs = new Map<string, string>();
    const btn = {
      classList: {
        toggle: (name: string, on: boolean) => (on ? classes.add(name) : classes.delete(name)),
      },
      setAttribute: (name: string, value: string) => attrs.set(name, value),
    } as unknown as HTMLElement;
    setPressed(btn, true);
    expect(classes.has("active")).toBe(true);
    expect(attrs.get("aria-pressed")).toBe("true");
    setPressed(btn, false);
    expect(classes.has("active")).toBe(false);
    expect(attrs.get("aria-pressed")).toBe("false");
  });
});
