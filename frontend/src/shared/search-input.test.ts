import { describe, expect, it } from "vitest";

import { searchInputError } from "./search-input";

describe("searchInputError", () => {
  it("accepts a point in Kanton Bern, with decimals", () => {
    expect(searchInputError("2616000", "1149000.5")).toBeNull();
  });

  it("asks for numbers when a field is empty or not a number", () => {
    expect(searchInputError("2616000", "")).toBe("search_error_format");
    expect(searchInputError("abc", "1149000")).toBe("search_error_format");
  });

  it("rejects a point outside Switzerland, such as swapped X and Y or small numbers", () => {
    expect(searchInputError("1149000", "2616000")).toBe("search_error_outside");
    expect(searchInputError("1", "2")).toBe("search_error_outside");
  });
});
