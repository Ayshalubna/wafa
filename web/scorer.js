/* Wafa scorer: the trained XGBoost model, evaluated in JavaScript.
 *
 * - features(raw): the same feature rules as wafa/sql/features.sql
 * - margin / probability: walks the exported trees exactly like XGBoost (float32 comparisons)
 * - shap: exact TreeSHAP (Lundberg et al., 2018), per-customer contributions in log-odds
 * - reasons: the same plain-language rules as wafa/explain.py
 * Checked against XGBoost's own predictions and SHAP values in tests/test_scorer.py.
 * Works in the browser (window.WafaScorer) and in Node (module.exports).
 */
(function (root) {
  "use strict";
  const f32 = Math.fround;

  function features(r) {
    const yes = (v) => (v === "Yes" ? 1 : 0);
    const tenure = parseInt(r.tenure, 10) || 0;
    const monthly = parseFloat(r.MonthlyCharges) || 0;
    const tc = String(r.TotalCharges == null ? "" : r.TotalCharges).trim();
    const total = tc === "" ? 0 : parseFloat(tc);
    const noInternet = r.InternetService === "No" ? 1 : 0;
    const o = {
      tenure, monthly_charges: monthly, total_charges: total, senior: parseInt(r.SeniorCitizen, 10) || 0,
      partner: yes(r.Partner), dependents: yes(r.Dependents), phone: yes(r.PhoneService), multiple_lines: yes(r.MultipleLines),
      fiber: r.InternetService === "Fiber optic" ? 1 : 0, dsl: r.InternetService === "DSL" ? 1 : 0, no_internet: noInternet,
      online_security: yes(r.OnlineSecurity), online_backup: yes(r.OnlineBackup), device_protection: yes(r.DeviceProtection),
      tech_support: yes(r.TechSupport), streaming_tv: yes(r.StreamingTV), streaming_movies: yes(r.StreamingMovies),
      month_to_month: r.Contract === "Month-to-month" ? 1 : 0, two_year: r.Contract === "Two year" ? 1 : 0,
      paperless: yes(r.PaperlessBilling), electronic_check: r.PaymentMethod === "Electronic check" ? 1 : 0,
      auto_pay: /\(automatic\)$/.test(r.PaymentMethod || "") ? 1 : 0,
    };
    o.n_services = o.phone + o.multiple_lines + (1 - noInternet) + o.online_security + o.online_backup + o.device_protection +
      o.tech_support + o.streaming_tv + o.streaming_movies;
    o.n_protection = o.online_security + o.online_backup + o.device_protection + o.tech_support;
    o.avg_monthly_spend = tenure > 0 ? total / tenure : monthly;
    o.price_change = monthly - o.avg_monthly_spend;
    o.new_customer = tenure <= 6 ? 1 : 0;
    return o;
  }

  const vector = (model, feats) => model.features.map((k) => feats[k]);

  function leafOf(t, x) {
    let i = 0;
    while (t.l[i] !== -1) i = f32(x[t.f[i]]) < f32(t.t[i]) ? t.l[i] : t.r[i];
    return i;
  }

  function margin(model, x) {
    let s = model.base_margin;
    for (const t of model.trees) s += t.t[leafOf(t, x)];
    return s;
  }

  const sigmoid = (z) => 1 / (1 + Math.exp(-z));
  const probability = (model, x) => sigmoid(margin(model, x));

  // ------------------------------------------------------------------ exact TreeSHAP
  function extend(m, pz, po, pi) {
    const L = m.length;
    const r = m.map((e) => ({ d: e.d, z: e.z, o: e.o, w: e.w }));
    r.push({ d: pi, z: pz, o: po, w: L === 0 ? 1 : 0 });
    for (let i = L - 1; i >= 0; i--) {
      r[i + 1].w += po * r[i].w * ((i + 1) / (L + 1));
      r[i].w = pz * r[i].w * ((L - i) / (L + 1));
    }
    return r;
  }

  function unwind(m, i) {
    const L = m.length, oi = m[i].o, zi = m[i].z;
    let n = m[L - 1].w;
    const r = m.slice(0, L - 1).map((e) => ({ d: e.d, z: e.z, o: e.o, w: e.w }));
    for (let j = L - 2; j >= 0; j--) {
      if (oi !== 0) {
        const t = r[j].w;
        r[j].w = (n * L) / ((j + 1) * oi);
        n = t - r[j].w * zi * ((L - (j + 1)) / L);
      } else {
        r[j].w = (r[j].w * L) / (zi * (L - (j + 1)));
      }
    }
    for (let j = i; j < L - 1; j++) { r[j].d = m[j + 1].d; r[j].z = m[j + 1].z; r[j].o = m[j + 1].o; }
    return r;
  }

  function unwoundSum(m, i) {
    const D = m.length - 1, oi = m[i].o, zi = m[i].z;
    let total = 0;
    if (oi !== 0) {
      let next = m[D].w;
      for (let j = D - 1; j >= 0; j--) {
        const tmp = (next * (D + 1)) / ((j + 1) * oi);
        total += tmp;
        next = m[j].w - tmp * zi * ((D - j) / (D + 1));
      }
    } else {
      for (let j = D - 1; j >= 0; j--) total += m[j].w / zi / ((D - j) / (D + 1));
    }
    return total;
  }

  function treeShap(t, x, phi) {
    (function rec(j, m, pz, po, pi) {
      m = extend(m, pz, po, pi);
      if (t.l[j] === -1) {
        for (let i = 1; i < m.length; i++) phi[m[i].d] += unwoundSum(m, i) * (m[i].o - m[i].z) * t.t[j];
        return;
      }
      const goLeft = f32(x[t.f[j]]) < f32(t.t[j]);
      const hot = goLeft ? t.l[j] : t.r[j], cold = goLeft ? t.r[j] : t.l[j];
      let iz = 1, io = 1;
      const k = m.findIndex((e, idx) => idx > 0 && e.d === t.f[j]);
      if (k > 0) { iz = m[k].z; io = m[k].o; m = unwind(m, k); }
      rec(hot, m, (iz * t.c[hot]) / t.c[j], io, t.f[j]);
      rec(cold, m, (iz * t.c[cold]) / t.c[j], 0, t.f[j]);
    })(0, [], 1, 1, -1);
  }

  function expectation(t) {
    let s = 0;
    for (let i = 0; i < t.l.length; i++) if (t.l[i] === -1) s += t.c[i] * t.t[i];
    return s / t.c[0];
  }

  /** Per-feature contributions in log-odds; the last element is the expected value (bias), like XGBoost's pred_contribs. */
  function shap(model, x) {
    const phi = new Array(model.features.length + 1).fill(0);
    phi[model.features.length] = model.base_margin;
    for (const t of model.trees) {
      treeShap(t, x, phi);
      phi[model.features.length] += expectation(t);
    }
    return phi;
  }

  // ------------------------------------------------------------------ plain-language reasons
  function money(v) {
    const a = Math.abs(v);
    if (a >= 100) return "$" + Math.floor(a + 0.5).toLocaleString("en-US");
    const c = Math.floor(a * 100 + 0.5);
    return ("$" + Math.floor(c / 100) + "." + String(c % 100).padStart(2, "0")).replace(/0+$/, "").replace(/\.$/, "");
  }

  function phrase(spec, feature, value, contribution) {
    const s = spec[feature] || {};
    const binary = Object.keys(s).some((k) => /^(up|down)[01]$/.test(k));
    let key = contribution > 0 ? "up" : "down";
    if (binary) key += value >= 0.5 ? "1" : "0";
    const tpl = s[key];
    if (!tpl || (contribution > 0 && s.up_min !== undefined && value < s.up_min)) return null;
    const v = Number.isInteger(value) ? value : Math.floor(value * 10 + 0.5) / 10;
    return tpl.replace("{v}", String(v)).replace("{m}", money(value)).replace("{s}", v === 1 ? "" : "s");
  }

  function reasons(spec, featureNames, x, phi, k = 3) {
    const pairs = featureNames.map((f, i) => [f, x[i], phi[i]]);
    const pack = (items) => {
      const out = [];
      for (const [f, v, c] of items) {
        const t = phrase(spec, f, v, c);
        if (t) out.push({ feature: f, text: t, impact: Math.floor(c * 1000 + 0.5) / 1000 });
        if (out.length === k) break;
      }
      return out;
    };
    const risk = pack(pairs.filter((p) => p[2] > 0.02).sort((a, b) => b[2] - a[2]));
    const protective = pack(pairs.filter((p) => p[2] < -0.02).sort((a, b) => a[2] - b[2]));
    const actions = [];
    for (const r of risk) {
      const a = (spec[r.feature] || {}).action;
      if (a && !actions.includes(a)) actions.push(a);
    }
    return { risk, protective, actions: actions.slice(0, 2) };
  }

  const api = { features, vector, margin, probability, shap, reasons, phrase };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WafaScorer = api;
})(typeof window !== "undefined" ? window : globalThis);
