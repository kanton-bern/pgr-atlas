// Entry of the inline Components v2 build (see frontend/build.js): Streamlit
// calls the default export on mount and again when the data changes, after
// running the cleanup it returned the time before.
import { mountGate } from "./gate";
import type { GateData } from "./gate";

interface ComponentArgs {
  parentElement: ParentNode;
  data: GateData;
  setTriggerValue: (name: string, value: unknown) => void;
}

export default function ({ parentElement, data, setTriggerValue }: ComponentArgs): () => void {
  return mountGate(parentElement, data, () => {
    setTriggerValue("open_legal", true);
  });
}
