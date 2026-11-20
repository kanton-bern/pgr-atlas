// The Streamlit component protocol (API version 1), without Streamlit's own
// component library: ready, frame height and value go up; render args come down.
//
// Origin checks: messages go only to the page's own origin, and a
// message counts only if it comes from the parent window on that origin. The
// first render args decide where the map loads its data from, so a message
// from another window or origin must never get that far.

/** The parts of `window` the bridge uses (a fake one in the tests). */
export interface BridgeWindow {
  parent: { postMessage(message: unknown, targetOrigin: string): void };
  location: { origin: string };
  addEventListener(type: "message", listener: (event: MessageEvent) => void): void;
}

export interface StreamlitBridge {
  /** Sends a JSON value to Python, as the component's return value. */
  setComponentValue(value: unknown): void;
}

export function isTrustedMessage(
  event: Pick<MessageEvent, "source" | "origin">,
  win: Pick<BridgeWindow, "parent" | "location">,
): boolean {
  return event.source === win.parent && event.origin === win.location.origin;
}

/** The render args of a `streamlit:render` message, or null for any other message. */
export function renderArgs(data: unknown): Record<string, unknown> | null {
  if (typeof data !== "object" || data === null) return null;
  const msg = data as { type?: unknown; args?: unknown };
  if (msg.type !== "streamlit:render") return null;
  return typeof msg.args === "object" && msg.args !== null
    ? (msg.args as Record<string, unknown>)
    : {};
}

/**
 * Registers `onRender` for every trusted render message, then tells Streamlit
 * the component is ready. The component casts the args to its contract
 * (types.ts); the Python wrapper is what guarantees it.
 */
export function connectStreamlit(
  onRender: (args: Record<string, unknown>) => void,
  frameHeight = 700,
  win: BridgeWindow = window,
): StreamlitBridge {
  const send = (type: string, extra: Record<string, unknown>) => {
    win.parent.postMessage({ isStreamlitMessage: true, type, ...extra }, win.location.origin);
  };
  win.addEventListener("message", (event) => {
    if (!isTrustedMessage(event, win)) return;
    const args = renderArgs(event.data);
    if (args) onRender(args);
  });
  send("streamlit:componentReady", { apiVersion: 1 });
  send("streamlit:setFrameHeight", { height: frameHeight });
  return {
    setComponentValue: (value) => {
      send("streamlit:setComponentValue", { value, dataType: "json" });
    },
  };
}
