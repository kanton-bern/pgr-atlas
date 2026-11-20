import { describe, expect, it, vi } from "vitest";
import { ACCEPTED_KEY, createGate, tabStorage } from "./gate";
import type { GatePage, GateStorage } from "./gate";

function memoryStorage(initial: Record<string, string> = {}): GateStorage {
  const items = new Map(Object.entries(initial));
  return {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => void items.set(key, value),
  };
}

function brokenStorage(): GateStorage {
  const fail = () => {
    throw new Error("SecurityError");
  };
  return { getItem: fail, setItem: fail };
}

const control = {} as HTMLElement;

function setup(storage: GateStorage | null) {
  const page = {
    storage,
    openDialog: vi.fn(),
    closeDialog: vi.fn(),
    replay: vi.fn(),
    openLegal: vi.fn(),
  } satisfies GatePage;
  return { page, gate: createGate(page) };
}

describe("first download in a tab", () => {
  it("holds the click back and opens the dialog", () => {
    const { page, gate } = setup(memoryStorage());
    expect(gate.intercept(control)).toBe(true);
    expect(page.openDialog).toHaveBeenCalledOnce();
    expect(page.replay).not.toHaveBeenCalled();
  });

  it("downloads nothing when declined or closed with Escape", () => {
    const { page, gate } = setup(memoryStorage());
    gate.intercept(control);
    gate.cancel();
    expect(page.closeDialog).toHaveBeenCalled();
    gate.accept();
    expect(page.replay).not.toHaveBeenCalled();
  });

  it("asks again after a decline", () => {
    const { gate } = setup(memoryStorage());
    gate.intercept(control);
    gate.cancel();
    expect(gate.intercept(control)).toBe(true);
  });
});

describe("the dialog's link", () => {
  it("closes the dialog, opens the legal page and downloads nothing", () => {
    const { page, gate } = setup(memoryStorage());
    gate.intercept(control);
    gate.openLegal();
    expect(page.closeDialog).toHaveBeenCalled();
    expect(page.openLegal).toHaveBeenCalledOnce();
    gate.accept();
    expect(page.replay).not.toHaveBeenCalled();
  });

  it("does not count as accepting", () => {
    const { gate } = setup(memoryStorage());
    gate.intercept(control);
    gate.openLegal();
    expect(gate.intercept(control)).toBe(true);
  });
});

describe("accepting", () => {
  it("stores the key, closes the dialog and clicks the original control again", () => {
    const storage = memoryStorage();
    const { page, gate } = setup(storage);
    gate.intercept(control);
    gate.accept();
    expect(storage.getItem(ACCEPTED_KEY)).toBe("1");
    expect(page.closeDialog).toHaveBeenCalled();
    expect(page.replay).toHaveBeenCalledWith(control);
  });

  it("lets the replayed click pass", () => {
    const { page, gate } = setup(memoryStorage());
    page.replay.mockImplementation((c: HTMLElement) => {
      expect(gate.intercept(c)).toBe(false);
    });
    gate.intercept(control);
    gate.accept();
    expect(page.replay).toHaveBeenCalledOnce();
  });

  it("lets later clicks pass", () => {
    const { page, gate } = setup(memoryStorage());
    gate.intercept(control);
    gate.accept();
    expect(gate.intercept(control)).toBe(false);
    expect(page.openDialog).toHaveBeenCalledOnce();
  });
});

describe("a stored acceptance", () => {
  it("lets the click pass without a dialog, as after a reload", () => {
    const { page, gate } = setup(memoryStorage({ [ACCEPTED_KEY]: "1" }));
    expect(gate.intercept(control)).toBe(false);
    expect(page.openDialog).not.toHaveBeenCalled();
  });

  it("ignores any other value", () => {
    const { gate } = setup(memoryStorage({ [ACCEPTED_KEY]: "0" }));
    expect(gate.intercept(control)).toBe(true);
  });
});

describe.each([
  ["throws on every access", brokenStorage()],
  ["is missing", null],
])("storage that %s", (_name, storage) => {
  it("asks on every download but still downloads after accepting", () => {
    const { page, gate } = setup(storage);
    expect(gate.intercept(control)).toBe(true);
    gate.accept();
    expect(page.replay).toHaveBeenCalledWith(control);
    expect(gate.intercept(control)).toBe(true);
  });

  it("lets the replayed click pass", () => {
    const { page, gate } = setup(storage);
    page.replay.mockImplementation((c: HTMLElement) => {
      expect(gate.intercept(c)).toBe(false);
    });
    gate.intercept(control);
    gate.accept();
    expect(page.replay).toHaveBeenCalledOnce();
  });
});

describe("tabStorage", () => {
  it("returns null when reading sessionStorage throws", () => {
    const win = {
      get sessionStorage(): Storage {
        throw new Error("SecurityError");
      },
    } as unknown as Window;
    expect(tabStorage(win)).toBeNull();
  });
});
