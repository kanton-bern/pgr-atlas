// A click popup whose HTML is built from the labels: a language switch while
// it is open rewrites its content in place. One popup at a time per instance.

import * as maplibregl from "maplibre-gl";
import type { LngLatLike, Map as MapLibreMap, PopupOptions } from "maplibre-gl";

import type { TextSource } from "@/shared/texts";

export class TextPopup {
  private popup: maplibregl.Popup | null = null;
  // MapLibre's own content element holds this one, so a rewrite keeps the
  // close button and the focus where they are (setHTML would rebuild both).
  private readonly body = document.createElement("div");
  private html: () => string = () => "";

  constructor(
    private readonly map: MapLibreMap,
    texts: TextSource<string>,
    private readonly options: PopupOptions,
  ) {
    texts.bind(() => {
      if (this.popup?.isOpen()) this.body.innerHTML = this.html();
    });
  }

  /** Opens the popup at `at`, closing the one before; `html` is escaped by the caller. */
  show(at: LngLatLike, html: () => string): void {
    this.close();
    this.html = html;
    this.body.innerHTML = html();
    this.popup = new maplibregl.Popup(this.options)
      .setLngLat(at)
      .setDOMContent(this.body)
      .addTo(this.map);
  }

  /** True while the popup opened with `html` is open. */
  showing(html: () => string): boolean {
    return this.html === html && Boolean(this.popup?.isOpen());
  }

  /** Rewrites the open popup's content: what `html` reads has changed. */
  refresh(): void {
    if (this.popup?.isOpen()) this.body.innerHTML = this.html();
  }

  close(): void {
    this.popup?.remove();
    this.popup = null;
  }
}
