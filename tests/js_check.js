// Reads {model, reasons, fixtures, raws, customers} on stdin; prints what web/scorer.js computes.
const S = require("../web/scorer.js");
let buf = "";
process.stdin.on("data", (d) => (buf += d));
process.stdin.on("end", () => {
  const { model, reasons, fixtures, raws } = JSON.parse(buf);
  const out = {
    margins: fixtures.map((f) => S.margin(model, f.x)),
    shap: fixtures.map((f) => S.shap(model, f.x)),
    features: raws.map((r) => S.vector(model, S.features(r))),
    rowShap: raws.map((r) => S.shap(model, S.vector(model, S.features(r)))),
    reasons: raws.map((r) => {
      const x = S.vector(model, S.features(r));
      return S.reasons(reasons, model.features, x, S.shap(model, x));
    }),
    probability: raws.map((r) => S.probability(model, S.vector(model, S.features(r)))),
  };
  process.stdout.write(JSON.stringify(out));
});
