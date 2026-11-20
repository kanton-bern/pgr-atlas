// Popovers of the map's control column: a trigger button opens a panel next
// to it. One panel of a group is open at a time. Escape closes it and returns
// focus to its trigger; a pointer press outside closes it and leaves focus
// where the press put it. The trigger states its panel with aria-expanded and
// aria-controls (the disclosure pattern).

/** The parts of an element a popover uses; an HTMLElement in the page, a fake in tests. */
export type PopoverElement = Pick<
  HTMLElement,
  "hidden" | "id" | "setAttribute" | "addEventListener" | "focus" | "contains"
>;

export interface PopoverParts {
  trigger: PopoverElement;
  panel: PopoverElement;
  /** Positions the panel; called on every open, once it is visible. */
  place?: () => void;
  /** The element that gets focus on open, e.g. the panel's first control. */
  initialFocus?: () => PopoverElement | null;
}

export interface Popover {
  readonly isOpen: boolean;
  open(): void;
  /** Closes; `returnFocus` moves focus back to the trigger. */
  close(returnFocus: boolean): void;
}

interface Entry {
  popover: Popover;
  parts: PopoverParts;
}

export class PopoverGroup {
  private readonly entries: Entry[] = [];

  /** Listens on `doc` for Escape and for pointer presses outside the open panel. */
  constructor(doc: Pick<Document, "addEventListener">) {
    doc.addEventListener("keydown", (e) => {
      if (e.key === "Escape") this.closeOpen(true);
    });
    doc.addEventListener("pointerdown", (e) => {
      const target = e.target as Node | null;
      for (const { popover, parts } of this.entries) {
        const inside = parts.trigger.contains(target) || parts.panel.contains(target);
        if (popover.isOpen && !inside) popover.close(false);
      }
    });
  }

  private closeOpen(returnFocus: boolean): void {
    for (const { popover } of this.entries) if (popover.isOpen) popover.close(returnFocus);
  }

  /** Wires `parts.trigger` to toggle `parts.panel`, which starts closed. */
  add(parts: PopoverParts): Popover {
    const { trigger, panel } = parts;
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", panel.id);
    panel.hidden = true;
    let isOpen = false;
    const popover: Popover = {
      get isOpen() {
        return isOpen;
      },
      open: () => {
        this.closeOpen(false);
        isOpen = true;
        panel.hidden = false;
        trigger.setAttribute("aria-expanded", "true");
        parts.place?.();
        parts.initialFocus?.()?.focus();
      },
      close(returnFocus) {
        isOpen = false;
        panel.hidden = true;
        trigger.setAttribute("aria-expanded", "false");
        if (returnFocus) trigger.focus();
      },
    };
    trigger.addEventListener("click", () => {
      if (isOpen) popover.close(false);
      else popover.open();
    });
    this.entries.push({ popover, parts });
    return popover;
  }
}
