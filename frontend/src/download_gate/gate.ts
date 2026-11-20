// The download disclaimer gate: one capture-phase click listener on the
// document that holds back the first download of a browser tab behind a
// modal <dialog>, and lets every later one through.
//
// All visible text arrives as data from Python; this file holds none.
import css from "./gate.css?inline";

export const ACCEPTED_KEY = "pgr-download-accepted";
const ACCEPTED_VALUE = "1";
const BUTTON_SELECTOR = '[data-testid="stDownloadButton"] button';
const LINK_CONTAINER_PREFIX = "st-key-pgr_download_";
// Where the running gate's teardown is kept, so a second mount (a rerun that
// did not unmount the first) replaces it instead of adding a second listener.
const ACTIVE = Symbol.for("pgr-download-gate-teardown");

/** The strings and link the dialog shows. */
export interface GateData {
  title: string;
  statementBefore: string;
  linkText: string;
  statementAfter: string;
  linkHref: string;
  /** The id of the heading to show on mount, after the link led here; "" for none. */
  showSection: string;
  accept: string;
  decline: string;
}

/** The parts of `sessionStorage` the gate uses. */
export type GateStorage = Pick<Storage, "getItem" | "setItem">;

/** The storage, or null where even looking at it throws (some private modes). */
export function tabStorage(win: Window = window): GateStorage | null {
  try {
    return win.sessionStorage;
  } catch {
    return null;
  }
}

function isAccepted(storage: GateStorage | null): boolean {
  try {
    return storage?.getItem(ACCEPTED_KEY) === ACCEPTED_VALUE;
  } catch {
    return false;
  }
}

function remember(storage: GateStorage | null): void {
  try {
    storage?.setItem(ACCEPTED_KEY, ACCEPTED_VALUE);
  } catch {
    // Storage is full or blocked: the gate asks again on the next download.
  }
}

function insideDownloadLinkContainer(link: Element): boolean {
  for (let el = link.parentElement; el; el = el.parentElement) {
    for (const name of el.classList) {
      if (name.startsWith(LINK_CONTAINER_PREFIX)) return true;
    }
  }
  return false;
}

/** The download control a click landed on, or null. */
export function downloadControl(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element)) return null;
  const button = target.closest<HTMLElement>(BUTTON_SELECTOR);
  if (button) return button;
  const link = target.closest<HTMLElement>("a");
  return link && insideDownloadLinkContainer(link) ? link : null;
}

function element<K extends keyof HTMLElementTagNameMap>(
  doc: Document,
  tag: K,
  className: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const el = doc.createElement(tag);
  el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

interface Dialog {
  root: HTMLDialogElement;
  link: HTMLAnchorElement;
  accept: HTMLButtonElement;
  decline: HTMLButtonElement;
}

function buildDialog(doc: Document, data: GateData): Dialog {
  const root = element(doc, "dialog", "gate");
  const title = element(doc, "h2", "title", data.title);
  title.id = "gate-title";
  root.setAttribute("aria-labelledby", title.id);
  const accept = element(doc, "button", "button primary", data.accept);
  const decline = element(doc, "button", "button", data.decline);
  accept.type = "button";
  decline.type = "button";
  const actions = element(doc, "div", "actions");
  actions.append(accept, decline);
  const statement = element(doc, "p", "statement");
  const link = element(doc, "a", "link", data.linkText);
  link.href = data.linkHref;
  statement.append(data.statementBefore, link, data.statementAfter);
  root.append(title, statement, actions);
  return { root, link, accept, decline };
}

/** A plain left click; a modified or middle click keeps the browser's own handling. */
function isPlainClick(event: MouseEvent): boolean {
  return event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;
}

/**
 * Puts the heading `id` in the URL and scrolls to it. A heading drawn after
 * this scrolls itself into view, as Streamlit does for the heading the URL names.
 */
function showSection(doc: Document, id: string): void {
  doc.defaultView?.history.replaceState(null, "", `#${id}`);
  doc.getElementById(id)?.scrollIntoView();
}

/** What the gate needs from the page, so its decisions run without a DOM. */
export interface GatePage {
  storage: GateStorage | null;
  openDialog: () => void;
  closeDialog: () => void;
  /** Clicks the control again, as the user would. */
  replay: (control: HTMLElement) => void;
  /** Asks Python to open the legal page in this session. */
  openLegal: () => void;
}

export interface Gate {
  /** True when the click was held back and the dialog opened. */
  intercept: (control: HTMLElement) => boolean;
  accept: () => void;
  /** Ablehnen, Escape or any other close: nothing downloads. */
  cancel: () => void;
  /** The dialog's link: nothing downloads, and the legal page opens. */
  openLegal: () => void;
}

export function createGate(page: GatePage): Gate {
  let pending: HTMLElement | null = null;
  // Set while the accepted click is replayed, so it passes even when storage
  // is unavailable and cannot remember the acceptance.
  let replaying = false;
  return {
    intercept(control) {
      if (replaying || isAccepted(page.storage)) return false;
      pending = control;
      page.openDialog();
      return true;
    },
    accept() {
      remember(page.storage);
      const control = pending;
      pending = null;
      page.closeDialog();
      if (!control) return;
      replaying = true;
      try {
        page.replay(control);
      } finally {
        replaying = false;
      }
    },
    cancel() {
      pending = null;
      page.closeDialog();
    },
    openLegal() {
      pending = null;
      page.closeDialog();
      page.openLegal();
    },
  };
}

type Registry = { [ACTIVE]: (() => void) | undefined };

/**
 * Installs the gate: the dialog goes into `host`, the listener onto `doc`.
 * A plain click on the dialog's link calls `openLegal` in place of following
 * it. Returns the teardown, which removes both.
 */
export function mountGate(
  host: ParentNode,
  data: GateData,
  openLegal: () => void,
  doc: Document = document,
  storage: GateStorage | null = tabStorage(),
): () => void {
  const registry = doc as unknown as Registry;
  registry[ACTIVE]?.();

  const style = doc.createElement("style");
  style.textContent = css;
  const dialog = buildDialog(doc, data);
  host.append(style, dialog.root);

  const gate = createGate({
    storage,
    openDialog: () => {
      if (!dialog.root.open) dialog.root.showModal();
    },
    closeDialog: () => {
      if (dialog.root.open) dialog.root.close();
    },
    replay: (control) => {
      control.click();
    },
    openLegal,
  });

  const onClick = (event: Event) => {
    const control = downloadControl(event.target);
    if (!control || !gate.intercept(control)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  };

  dialog.link.addEventListener("click", (event) => {
    if (!isPlainClick(event)) return;
    event.preventDefault();
    gate.openLegal();
  });
  dialog.accept.addEventListener("click", gate.accept);
  dialog.decline.addEventListener("click", gate.cancel);
  dialog.root.addEventListener("close", gate.cancel);

  doc.addEventListener("click", onClick, true);
  const teardown = () => {
    doc.removeEventListener("click", onClick, true);
    gate.cancel();
    style.remove();
    dialog.root.remove();
    if (registry[ACTIVE] === teardown) registry[ACTIVE] = undefined;
  };
  registry[ACTIVE] = teardown;
  if (data.showSection) showSection(doc, data.showSection);
  return teardown;
}
