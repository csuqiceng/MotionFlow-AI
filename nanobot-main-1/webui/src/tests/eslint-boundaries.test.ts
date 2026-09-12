import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import eslintConfig from "../../eslint.config.js";

const transportBoundary = eslintConfig.find(
  (entry) => entry.files?.includes("src/transport/**/*.{ts,tsx}"),
);

function lintTransportImport(specifier: string) {
  const linter = new Linter({ configType: "flat" });
  return linter.verify(
    `import value from ${JSON.stringify(specifier)}; void value;`,
    {
      languageOptions: { ecmaVersion: 2020, sourceType: "module" },
      rules: transportBoundary?.rules ?? {},
    },
    "src/transport/boundary-probe.js",
  );
}

describe("transport dependency boundary", () => {
  it.each(["@/robot/types", "../robot/types"])(
    "rejects feature import %s",
    (specifier) => {
      expect(lintTransportImport(specifier)).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ ruleId: "no-restricted-imports", severity: 2 }),
        ]),
      );
    },
  );

  it("allows transport-owned contracts", () => {
    expect(lintTransportImport("./contracts/robot")).toEqual([]);
  });
});
