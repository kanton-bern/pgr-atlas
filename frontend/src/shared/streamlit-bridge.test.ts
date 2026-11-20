import { describe, expect, it, vi } from "vitest";

import {
  connectStreamlit,
  isTrustedMessage,
  renderArgs,
  type BridgeWindow,
} from "./streamlit-bridge";

const ORIGIN = "http://localhost:18501";

function fakeWindow() {
  const parent = { postMessage: vi.fn() };
  let listener: ((event: MessageEvent) => void) | undefined;
  const win: BridgeWindow = {
    parent,
    location: { origin: ORIGIN },
    addEventListener: (_type, l) => {
      listener = l;
    },
  };
  const deliver = (source: unknown, origin: string, data: unknown) => {
    listener?.({ source, origin, data } as MessageEvent);
  };
  return { win, parent, deliver };
}

const render = (args: unknown) => ({ type: "streamlit:render", args });

describe("isTrustedMessage", () => {
  const { win, parent } = fakeWindow();

  it("accepts the parent window on the page's own origin", () => {
    expect(isTrustedMessage({ source: parent as unknown as Window, origin: ORIGIN }, win)).toBe(
      true,
    );
  });

  it("rejects another origin, even from the parent", () => {
    const event = { source: parent as unknown as Window, origin: "https://evil.example" };
    expect(isTrustedMessage(event, win)).toBe(false);
  });

  it("rejects another window, even on the same origin", () => {
    expect(isTrustedMessage({ source: null, origin: ORIGIN }, win)).toBe(false);
  });
});

describe("renderArgs", () => {
  it("returns the args of a render message", () => {
    expect(renderArgs(render({ pmtiles_port: 8505 }))).toEqual({ pmtiles_port: 8505 });
  });

  it("returns empty args when a render message has none", () => {
    expect(renderArgs({ type: "streamlit:render" })).toEqual({});
  });

  it("returns null for anything that is not a render message", () => {
    expect(renderArgs({ type: "other", args: {} })).toBeNull();
    expect(renderArgs(null)).toBeNull();
    expect(renderArgs("streamlit:render")).toBeNull();
  });
});

describe("connectStreamlit", () => {
  it("announces the component to the parent, on the page's own origin only", () => {
    const { win, parent } = fakeWindow();
    connectStreamlit(() => undefined, 640, win);
    expect(parent.postMessage.mock.calls).toEqual([
      [{ isStreamlitMessage: true, type: "streamlit:componentReady", apiVersion: 1 }, ORIGIN],
      [{ isStreamlitMessage: true, type: "streamlit:setFrameHeight", height: 640 }, ORIGIN],
    ]);
  });

  it("passes trusted render args on and ignores everything else", () => {
    const { win, parent, deliver } = fakeWindow();
    const onRender = vi.fn();
    connectStreamlit(onRender, 700, win);

    deliver(parent, "https://evil.example", render({ pmtiles_port: 1 }));
    deliver({}, ORIGIN, render({ pmtiles_port: 2 }));
    deliver(parent, ORIGIN, { type: "streamlit:somethingElse" });
    expect(onRender).not.toHaveBeenCalled();

    deliver(parent, ORIGIN, render({ pmtiles_port: 8505 }));
    expect(onRender).toHaveBeenCalledExactlyOnceWith({ pmtiles_port: 8505 });
  });

  it("sends the component value as JSON", () => {
    const { win, parent } = fakeWindow();
    connectStreamlit(() => undefined, 700, win).setComponentValue({ nonce: 1 });
    expect(parent.postMessage).toHaveBeenLastCalledWith(
      {
        isStreamlitMessage: true,
        type: "streamlit:setComponentValue",
        value: { nonce: 1 },
        dataType: "json",
      },
      ORIGIN,
    );
  });
});
