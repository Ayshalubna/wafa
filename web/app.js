/* Wafa dashboard: plain JavaScript, no build step, no third-party code. Works as a static site. */
(function () {
  "use strict";
  const S = window.WafaScorer;
  const DATA = window.WAFA_DATA || "data/";
  const $ = (s, el = document) => el.querySelector(s);
  const main = $("#main");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (x, d = 0) => (x == null ? "–" : (100 * x).toFixed(d) + "%");
  const usd = (x) => (x < 0 ? "−$" : "$") + Math.round(Math.abs(x)).toLocaleString("en-US");
  const band = (p) => (p >= 0.5 ? "hi" : p >= 0.25 ? "md" : "lo");
  const bandName = (p) => (p >= 0.5 ? "high" : p >= 0.25 ? "medium" : "low");

  let M, C, MODEL, R;
  const plan = { cost: 60, save: 0.3, months: 12 };
  const ui = { shown: 25, contract: "all", risk: "all", sort: "risk", reveal: false };

  const ev = (c) => c.p * plan.save * parseFloat(c.raw.MonthlyCharges) * plan.months - plan.cost;
  const label = (f) => (R[f] && R[f].label) || f;

  function meter(p) {
    return `<div class="meter ${band(p)}"><div class="bar"><i style="width:${(100 * p).toFixed(1)}%"></i></div><b>${pct(p)}</b></div>`;
  }

  // ------------------------------------------------------------------ router
  const PAGES = { "": pageList, plan: pagePlan, score: pageScore, drivers: pageDrivers, model: pageModel };
  function route() {
    const name = location.hash.replace(/^#\/?/, "");
    const page = PAGES[name] ? name : "";
    document.querySelectorAll(".nav a, .mnav a").forEach((a) => {
      if (a.getAttribute("href").replace(/^#\/?/, "") === page) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    $("#mnav").hidden = true;
    closeDrawer();
    PAGES[page]();
  }
  window.addEventListener("hashchange", () => { route(); window.scrollTo(0, 0); main.focus({ preventScroll: true }); });
  $("#menu").addEventListener("click", () => { const m = $("#mnav"); m.hidden = !m.hidden; $("#menu").setAttribute("aria-expanded", String(!m.hidden)); });

  // ------------------------------------------------------------------ priority list
  function figures() {
    const t = M.test.xgboost, c = M.campaign;
    const gain = c.model.net - c.rule_month_to_month.net;
    return `<div class="figs">
      <div class="fig accent"><div class="v">${pct(t.recall_top20)}</div><p>of customers who left were in the top 20% of this list</p></div>
      <div class="fig"><div class="v">${t.auc.toFixed(3)}<small>AUC</small></div><p>ranking quality on ${t.n.toLocaleString()} held-out customers</p></div>
      <div class="fig"><div class="v">${usd(c.model.net)}</div><p>net value of model-targeted offers, ${usd(gain)} more than "call every month-to-month customer"</p></div>
      <div class="fig"><div class="v">${t.ece.toFixed(3)}<small>ECE</small></div><p>calibration error: a 40% score means about 40% leave</p></div>
    </div>`;
  }

  function filtered() {
    let rows = C.slice();
    if (ui.contract !== "all") rows = rows.filter((c) => c.raw.Contract === ui.contract);
    if (ui.risk !== "all") rows = rows.filter((c) => bandName(c.p) === ui.risk);
    if (ui.sort === "value") rows.sort((a, b) => ev(b) - ev(a));
    return rows;
  }

  function pageList() {
    main.innerHTML = `
      <h1>Who is about to leave, why, and is a call worth it?</h1>
      <p class="lede">Every customer below was held out from training. Wafa scores their risk of leaving, explains the score in plain words, and says whether a retention offer pays for itself under your campaign assumptions.</p>
      ${figures()}
      <div class="toolbar">
        <label>Contract <select id="f-contract"><option value="all">All</option><option>Month-to-month</option><option>One year</option><option>Two year</option></select></label>
        <label>Risk <select id="f-risk"><option value="all">All</option><option value="high">High (50%+)</option><option value="medium">Medium (25–50%)</option><option value="low">Low (&lt;25%)</option></select></label>
        <label>Sort by <select id="f-sort"><option value="risk">Risk of leaving</option><option value="value">Value of an offer</option></select></label>
        <label class="switch"><input type="checkbox" id="f-reveal"> Show what actually happened</label>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>#</th><th>Customer</th><th>Risk of leaving</th><th>Monthly bill</th><th>Contract</th><th>Tenure</th><th>Main reasons</th><th>Offer?</th><th class="out" hidden>Outcome</th></tr></thead>
        <tbody id="rows"></tbody>
      </table></div>
      <button class="btn ghost more" id="more" type="button">Show 25 more</button>
      <p class="note">Offer value uses the planner's assumptions (offer ${usd(plan.cost)}, ${pct(plan.save)} of would-be leavers kept, ${plan.months} months of revenue). Change them in the <a href="#/plan">campaign planner</a>.</p>`;
    $("#f-contract").value = ui.contract; $("#f-risk").value = ui.risk; $("#f-sort").value = ui.sort; $("#f-reveal").checked = ui.reveal;
    $("#f-contract").onchange = (e) => { ui.contract = e.target.value; ui.shown = 25; renderRows(); };
    $("#f-risk").onchange = (e) => { ui.risk = e.target.value; ui.shown = 25; renderRows(); };
    $("#f-sort").onchange = (e) => { ui.sort = e.target.value; renderRows(); };
    $("#f-reveal").onchange = (e) => { ui.reveal = e.target.checked; renderRows(); };
    $("#more").onclick = () => { ui.shown += 25; renderRows(); };
    renderRows();
  }

  function renderRows() {
    const rows = filtered();
    document.querySelectorAll(".out").forEach((th) => (th.hidden = !ui.reveal));
    $("#rows").innerHTML = rows.slice(0, ui.shown).map((c, i) => {
      const v = ev(c);
      return `<tr class="row" data-id="${esc(c.id)}" tabindex="0">
        <td class="muted num">${i + 1}</td><td class="id">${esc(c.id)}</td><td>${meter(c.p)}</td>
        <td class="num">${usd(parseFloat(c.raw.MonthlyCharges))}</td><td class="nw">${esc(c.raw.Contract)}</td><td class="num nw">${esc(c.raw.tenure)} mo</td>
        <td class="reasons">${c.risk.slice(0, 2).map((r) => `<span class="tag up">${esc(r.text)}</span>`).join("") || '<span class="muted small">No strong risk signals</span>'}</td>
        <td>${v > 0 ? `<span class="pill yes">Yes · ${usd(v)}</span>` : `<span class="pill no">No</span>`}</td>
        <td ${ui.reveal ? "" : "hidden"}>${c.churned ? '<span class="pill left">Left</span>' : '<span class="pill stayed">Stayed</span>'}</td>
      </tr>`;
    }).join("") || `<tr><td colspan="9" class="muted">No customers match.</td></tr>`;
    $("#more").hidden = rows.length <= ui.shown;
    document.querySelectorAll("tr.row").forEach((tr) => {
      const open = () => openCustomer(C.find((c) => c.id === tr.dataset.id));
      tr.onclick = open;
      tr.onkeydown = (e) => { if (e.key === "Enter") open(); };
    });
  }

  // ------------------------------------------------------------------ customer drawer
  function waterfall(x, phi, n = 8) {
    const idx = MODEL.features.map((f, i) => i).sort((a, b) => Math.abs(phi[b]) - Math.abs(phi[a]));
    const top = idx.slice(0, n);
    const rest = idx.slice(n).reduce((s, i) => s + phi[i], 0);
    const items = top.map((i) => ({ name: label(MODEL.features[i]), val: x[i], c: phi[i], f: MODEL.features[i] }));
    items.push({ name: `${idx.length - n} other factors`, c: rest });
    const max = Math.max(...items.map((d) => Math.abs(d.c)), 0.1);
    const W = 560, rowH = 26, lab = 220, mid = lab + (W - lab) / 2, half = (W - lab) / 2 - 46;
    const BIN = new Set(["senior", "partner", "dependents", "phone", "multiple_lines", "fiber", "dsl", "no_internet", "online_security",
      "online_backup", "device_protection", "tech_support", "streaming_tv", "streaming_movies", "month_to_month", "two_year", "paperless",
      "electronic_check", "auto_pay", "new_customer"]);
    const fmt = (d) => (d.val === undefined ? "" : BIN.has(d.f) ? (d.val ? ": yes" : ": no")
      : ` (${/charges|spend|price/.test(d.f) ? usd(d.val) : Number.isInteger(d.val) ? d.val : d.val.toFixed(1)})`);
    const bars = items.map((d, k) => {
      const w = (Math.abs(d.c) / max) * half, y = k * rowH + 4;
      const x0 = d.c >= 0 ? mid : mid - w;
      const tx = d.c >= 0 ? mid + w + 4 : mid - w - 4;
      return `<text x="0" y="${y + 13}">${esc(d.name + fmt(d))}</text>
        <rect class="${d.c >= 0 ? "up" : "down"}" x="${x0}" y="${y}" width="${Math.max(w, 1)}" height="16" rx="2"></rect>
        <text x="${tx}" y="${y + 13}" text-anchor="${d.c >= 0 ? "start" : "end"}">${d.c >= 0 ? "+" : "−"}${Math.abs(d.c).toFixed(2)}</text>`;
    }).join("");
    return `<svg class="wf" viewBox="0 0 ${W} ${items.length * rowH + 10}" role="img" aria-label="What pushes this customer's risk up (red) or down (green)">
      <line x1="${mid}" x2="${mid}" y1="0" y2="${items.length * rowH + 4}" stroke="#C9C4BA"></line>${bars}</svg>`;
  }

  function profile(raw) {
    const keys = [["Contract", "Contract"], ["tenure", "Tenure (months)"], ["MonthlyCharges", "Monthly bill"], ["TotalCharges", "Total billed"],
      ["InternetService", "Internet"], ["PaymentMethod", "Payment"], ["PaperlessBilling", "Paperless billing"], ["OnlineSecurity", "Online security"],
      ["TechSupport", "Tech support"], ["StreamingTV", "Streaming TV"], ["Partner", "Partner"], ["Dependents", "Dependents"], ["SeniorCitizen", "Senior"]];
    return `<div class="kv">${keys.map(([k, l]) => `<div><span>${l}</span><b>${esc(k === "SeniorCitizen" ? (raw[k] === "1" ? "Yes" : "No") : raw[k] || "–")}</b></div>`).join("")}</div>`;
  }

  function explainBlock(r) {
    return `<div class="grid2" style="margin-top:12px">
      <div><h3>Pushing risk up</h3>${r.risk.map((x) => `<span class="tag up">${esc(x.text)}</span>`).join("") || '<p class="muted small">Nothing notable</p>'}</div>
      <div><h3>Keeping them</h3>${r.protective.map((x) => `<span class="tag down">${esc(x.text)}</span>`).join("") || '<p class="muted small">Nothing notable</p>'}</div>
    </div>
    ${r.actions.length ? `<h3 style="margin-top:14px">Suggested action</h3><ul class="list">${r.actions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}`;
  }

  let lastFocus = null;
  function closeDrawer() {
    const d = $(".drawer-bg");
    if (d) { d.remove(); document.removeEventListener("keydown", escClose); if (lastFocus) lastFocus.focus(); }
  }
  function escClose(e) { if (e.key === "Escape") closeDrawer(); }

  function openCustomer(c) {
    if (!c) return;
    closeDrawer();
    lastFocus = document.activeElement;
    const x = S.vector(MODEL, S.features(c.raw));
    const phi = S.shap(MODEL, x);
    const base = 1 / (1 + Math.exp(-phi[phi.length - 1]));
    const v = ev(c);
    const bg = document.createElement("div");
    bg.className = "drawer-bg";
    bg.innerHTML = `<div class="drawer" role="dialog" aria-modal="true" aria-labelledby="dt">
      <button class="btn ghost close" type="button">Close</button>
      <p class="small muted" style="margin:0">Customer</p>
      <h2 id="dt">${esc(c.id)}</h2>
      ${meter(c.p)}
      <p class="small muted">An average customer has a ${pct(base)} risk. Red bars push this customer's risk up, green bars pull it down (SHAP values, log-odds).</p>
      ${waterfall(x, phi)}
      ${explainBlock(c)}
      <h3 style="margin-top:16px">Retention offer</h3>
      <p>${v > 0 ? `<span class="pill yes">Worth it</span> expected value ${usd(v)}` : `<span class="pill no">Not worth it</span> expected value ${usd(v)}`}
        <span class="small muted">= ${pct(c.p)} × ${pct(plan.save)} kept × ${plan.months} × ${usd(parseFloat(c.raw.MonthlyCharges))} − ${usd(plan.cost)}</span></p>
      <h3 style="margin-top:16px">Profile</h3>${profile(c.raw)}
      ${ui.reveal ? `<p>What actually happened: ${c.churned ? '<span class="pill left">Left</span>' : '<span class="pill stayed">Stayed</span>'}</p>` : ""}
    </div>`;
    bg.addEventListener("click", (e) => { if (e.target === bg) closeDrawer(); });
    $(".close", bg).onclick = closeDrawer;
    document.body.appendChild(bg);
    document.addEventListener("keydown", escClose);
    $(".close", bg).focus();
  }

  // ------------------------------------------------------------------ campaign planner
  function outcome(targeted) {
    let n = 0, reached = 0, kept = 0;
    C.forEach((c, i) => {
      if (!targeted[i]) return;
      n += 1;
      if (c.churned) { reached += 1; kept += plan.save * parseFloat(c.raw.MonthlyCharges) * plan.months; }
    });
    return { n, reached, net: kept - plan.cost * n };
  }

  function pagePlan() {
    main.innerHTML = `
      <h1>Plan a retention campaign</h1>
      <p class="lede">An offer is worth sending when the chance the customer leaves × the chance the offer keeps them × the revenue kept is more than the offer costs. Set your numbers; the plan and its result on the held-out customers update instantly.</p>
      <div class="grid-plan section" style="margin-top:22px">
        <div class="card">
          <div class="slider"><label for="s-cost">Cost of one offer <output id="o-cost"></output></label><input id="s-cost" type="range" min="10" max="200" step="5"><p>Discount, device credit or call-centre time.</p></div>
          <div class="slider"><label for="s-save">Leavers an offer keeps <output id="o-save"></output></label><input id="s-save" type="range" min="0.05" max="0.6" step="0.05"><p>An assumption: measure it with a holdout group.</p></div>
          <div class="slider"><label for="s-months">Months of revenue a kept customer is worth <output id="o-months"></output></label><input id="s-months" type="range" min="3" max="24" step="1"></div>
          <p class="note" style="margin-top:0">"Expected" uses the model's probabilities; "on held-out customers" judges the same plan against who really left.</p>
        </div>
        <div>
          <div class="figs three">
            <div class="fig accent"><div class="v num" id="k-n"></div><p>customers to contact</p></div>
            <div class="fig"><div class="v num" id="k-exp"></div><p>expected net value</p></div>
            <div class="fig"><div class="v num" id="k-real"></div><p>net value on held-out customers</p></div>
          </div>
          <div class="card" style="margin-top:12px"><h2>Compared with simple rules</h2><div class="scroll"><table class="cmp"><thead><tr><th>Strategy</th><th class="n">Contacted</th><th class="n">Leavers reached</th><th class="n">Net value</th></tr></thead><tbody id="cmp"></tbody></table></div></div>
          <div class="card" style="margin-top:12px"><h2>Net value by how far down the list you go</h2><div id="curve"></div></div>
        </div>
      </div>`;
    const bind = (id, key, fmt) => {
      const el = $("#s-" + id), out = $("#o-" + id);
      el.value = plan[key]; out.textContent = fmt(plan[key]);
      el.oninput = () => { plan[key] = parseFloat(el.value); out.textContent = fmt(plan[key]); updatePlan(); };
    };
    bind("cost", "cost", (v) => usd(v)); bind("save", "save", (v) => pct(v)); bind("months", "months", (v) => v + " months");
    updatePlan();
  }

  function updatePlan() {
    const evs = C.map(ev);
    const model = evs.map((v) => v > 0);
    const mm = outcome(model);
    const expected = evs.reduce((s, v) => s + Math.max(v, 0), 0);
    const strategies = [
      ["Model: expected value > 0", mm],
      ["Rule: every month-to-month customer", outcome(C.map((c) => c.raw.Contract === "Month-to-month"))],
      ["Rule: every fiber customer", outcome(C.map((c) => c.raw.InternetService === "Fiber optic"))],
      ["Everyone", outcome(C.map(() => true))],
      ["Nobody", { n: 0, reached: 0, net: 0 }],
    ];
    $("#k-n").textContent = mm.n.toLocaleString();
    $("#k-exp").textContent = usd(expected);
    $("#k-real").textContent = usd(mm.net);
    const best = Math.max(...strategies.map((s) => s[1].net));
    $("#cmp").innerHTML = strategies.map(([n, o]) => `<tr class="${o.net === best ? "best" : ""}"><td>${n}</td><td class="n num">${o.n.toLocaleString()}</td><td class="n num">${o.reached.toLocaleString()}</td><td class="n num">${usd(o.net)}</td></tr>`).join("");
    // cumulative realised value along the list ordered by expected value
    const order = evs.map((v, i) => i).sort((a, b) => evs[b] - evs[a]);
    let run = 0;
    const pts = [[0, 0]];
    order.forEach((i, k) => {
      const c = C[i];
      run += (c.churned ? plan.save * parseFloat(c.raw.MonthlyCharges) * plan.months : 0) - plan.cost;
      pts.push([k + 1, run]);
    });
    $("#curve").innerHTML = curve(pts, mm.n);
  }

  function curve(pts, cut) {
    const W = 640, H = 240, L = 64, B = 30, T = 12, Rr = 12;
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const xmax = Math.max(...xs), ymin = Math.min(0, ...ys), ymax = Math.max(...ys, 1);
    const X = (v) => L + (v / xmax) * (W - L - Rr), Y = (v) => T + (1 - (v - ymin) / (ymax - ymin)) * (H - T - B);
    const d = pts.filter((p, i) => i % 3 === 0 || i === pts.length - 1).map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    const ticks = [ymin, (ymin + ymax) / 2, ymax].map((v) => `<text x="${L - 8}" y="${Y(v) + 4}" text-anchor="end">${usd(v)}</text>`).join("");
    const peak = pts.reduce((a, b) => (b[1] > a[1] ? b : a));
    return `<svg class="curve" viewBox="0 0 ${W} ${H}" role="img" aria-label="Net value against number of customers contacted">
      <line class="axis" x1="${L}" x2="${W - Rr}" y1="${H - B}" y2="${H - B}"></line>
      <line class="zero" x1="${L}" x2="${W - Rr}" y1="${Y(0)}" y2="${Y(0)}"></line>${ticks}
      <text x="${L}" y="${H - 8}">0</text><text x="${W - Rr}" y="${H - 8}" text-anchor="end">${xmax.toLocaleString()} customers</text>
      <path class="line" d="${d}"></path>
      <line x1="${X(cut)}" x2="${X(cut)}" y1="${T}" y2="${H - B}" stroke="#E39B2D" stroke-width="1.5"></line>
      <text x="${X(cut) + 6}" y="${H - B - 8}" style="fill:#8A5A0E">plan: contact ${cut}</text>
      <circle cx="${X(peak[0])}" cy="${Y(peak[1])}" r="4" fill="#2E2650"></circle>
      <text x="${Math.min(X(peak[0]) + 10, W - 240)}" y="${((Y(peak[1]) + H - B) / 2).toFixed(0)}">best in hindsight: ${peak[0]} (${usd(peak[1])})</text>
    </svg>`;
  }

  // ------------------------------------------------------------------ score a customer
  const FIELDS = [
    ["tenure", "Months as a customer", "number", [0, 72]], ["MonthlyCharges", "Monthly bill ($)", "number", [18, 120]],
    ["Contract", "Contract", ["Month-to-month", "One year", "Two year"]],
    ["InternetService", "Internet", ["Fiber optic", "DSL", "No"]],
    ["PaymentMethod", "Payment method", ["Electronic check", "Mailed check", "Bank transfer (automatic)", "Credit card (automatic)"]],
    ["PaperlessBilling", "Paperless billing", ["Yes", "No"]],
    ["OnlineSecurity", "Online security", ["No", "Yes", "No internet service"]], ["TechSupport", "Tech support", ["No", "Yes", "No internet service"]],
    ["OnlineBackup", "Online backup", ["No", "Yes", "No internet service"]], ["DeviceProtection", "Device protection", ["No", "Yes", "No internet service"]],
    ["StreamingTV", "Streaming TV", ["No", "Yes", "No internet service"]], ["StreamingMovies", "Streaming movies", ["No", "Yes", "No internet service"]],
    ["PhoneService", "Phone service", ["Yes", "No"]], ["MultipleLines", "Multiple lines", ["No", "Yes", "No phone service"]],
    ["Partner", "Partner", ["No", "Yes"]], ["Dependents", "Dependents", ["No", "Yes"]], ["SeniorCitizen", "Senior citizen", [["0", "No"], ["1", "Yes"]]],
  ];
  const EXAMPLE = { tenure: "3", MonthlyCharges: "89.5", Contract: "Month-to-month", InternetService: "Fiber optic", PaymentMethod: "Electronic check",
    PaperlessBilling: "Yes", OnlineSecurity: "No", TechSupport: "No", OnlineBackup: "No", DeviceProtection: "Yes", StreamingTV: "Yes",
    StreamingMovies: "No", PhoneService: "Yes", MultipleLines: "Yes", Partner: "No", Dependents: "No", SeniorCitizen: "0" };
  let draft = Object.assign({}, EXAMPLE);

  function pageScore() {
    main.innerHTML = `
      <h1>Score a customer</h1>
      <p class="lede">Change any detail and the score, the reasons and the offer decision update instantly. The model runs in this page; nothing is sent anywhere.</p>
      <div class="grid2 section" style="margin-top:22px">
        <div class="card">
          <form class="form" id="sf">${FIELDS.map(([k, l, type, opts]) => type === "number"
            ? `<label>${l}<input type="number" name="${k}" min="${opts[0]}" max="${opts[1]}" step="${k === "tenure" ? 1 : 0.05}"></label>`
            : `<label>${l}<select name="${k}">${type.map((o) => (Array.isArray(o) ? `<option value="${o[0]}">${o[1]}</option>` : `<option>${esc(o)}</option>`)).join("")}</select></label>`).join("")}</form>
          <div style="display:flex;gap:10px;margin-top:14px;flex-wrap:wrap"><button class="btn ghost" type="button" id="rand">Load a held-out customer</button><button class="btn ghost" type="button" id="reset">Reset example</button></div>
        </div>
        <div class="card" id="sres" aria-live="polite"></div>
      </div>`;
    const form = $("#sf");
    const fill = () => FIELDS.forEach(([k]) => { form.elements[k].value = draft[k]; });
    fill();
    form.addEventListener("input", () => { FIELDS.forEach(([k]) => { draft[k] = form.elements[k].value; }); scoreDraft(); });
    $("#rand").onclick = () => { const c = C[Math.floor(Math.random() * C.length)]; draft = Object.assign({}, c.raw); fill(); scoreDraft(c.id); };
    $("#reset").onclick = () => { draft = Object.assign({}, EXAMPLE); fill(); scoreDraft(); };
    scoreDraft();
  }

  function scoreDraft(id) {
    const raw = Object.assign({}, draft);
    const t = parseInt(raw.tenure, 10) || 0;
    if (!id) raw.TotalCharges = t === 0 ? "" : String((parseFloat(raw.MonthlyCharges) || 0) * t);   // a new form assumes a steady bill
    const x = S.vector(MODEL, S.features(raw));
    const phi = S.shap(MODEL, x);
    const p = S.probability(MODEL, x);
    const r = S.reasons(R, MODEL.features, x, phi);
    const v = ev({ p, raw });
    $("#sres").innerHTML = `
      <p class="small muted" style="margin:0">${id ? "Held-out customer " + esc(id) : "Risk of leaving"}</p>
      <div style="display:flex;align-items:baseline;gap:14px"><span class="gauge">${pct(p)}</span><span class="band ${bandName(p)}">${bandName(p)} risk</span></div>
      ${meter(p)}
      ${explainBlock(r)}
      <h3 style="margin-top:16px">Retention offer</h3>
      <p>${v > 0 ? `<span class="pill yes">Send an offer</span>` : `<span class="pill no">Don't send</span>`} expected value ${usd(v)}</p>
      <details><summary class="small">Why: all ${MODEL.features.length} factors</summary>${waterfall(x, phi, 12)}</details>`;
  }

  // ------------------------------------------------------------------ drivers
  function pageDrivers() {
    const imp = M.importance.slice(0, 12), max = imp[0][1];
    main.innerHTML = `
      <h1>What drives churn here</h1>
      <p class="lede">Churn rates across all ${M.data.customers.toLocaleString()} customers, and which factors move the model's scores most. These are associations in historical data, not proof that changing a factor changes behaviour; test retention actions before rolling them out.</p>
      <div class="grid2 section" style="margin-top:22px">
        ${M.segments.map((s) => {
          const smax = Math.max(...s.groups.map((g) => g.churn_rate));
          return `<div class="card"><h2>Churn rate by ${esc(s.name.toLowerCase())}</h2><div class="hbars">${s.groups.map((g) => `
            <div class="hbar"><span>${esc(g.label)} <span class="muted small">(${g.n.toLocaleString()})</span></span><div class="track"><i class="risk" style="width:${(100 * g.churn_rate / Math.max(smax, 0.01)).toFixed(1)}%"></i></div><b>${pct(g.churn_rate)}</b></div>`).join("")}</div></div>`;
        }).join("")}
        <div class="card"><h2>Factors the model relies on most</h2><p class="small muted" style="margin-top:-6px">Mean absolute SHAP value on held-out customers</p><div class="hbars">${imp.map(([f, v]) => `
          <div class="hbar"><span>${esc(label(f))}</span><div class="track"><i style="width:${(100 * v / max).toFixed(1)}%"></i></div><b>${v.toFixed(2)}</b></div>`).join("")}</div></div>
      </div>`;
  }

  // ------------------------------------------------------------------ model card
  function pageModel() {
    const t = M.test.xgboost, lr = M.test.logistic, cv = M.cv, p = M.params;
    const row = (n, m) => `<tr><td>${n}</td><td class="num">${m.auc.toFixed(3)} <span class="muted small">(${m.auc_ci[0].toFixed(3)}–${m.auc_ci[1].toFixed(3)})</span></td><td class="num">${m.pr_auc.toFixed(3)}</td><td class="num">${pct(m.recall_top20)}</td><td class="num">${m.lift_top10.toFixed(1)}×</td><td class="num">${m.brier.toFixed(3)}</td><td class="num">${m.ece.toFixed(3)}</td></tr>`;
    const fair = Object.entries(M.fairness).map(([, gs]) => Object.entries(gs).map(([g, v]) => `<tr><td>${esc(g)}</td><td class="num">${v.n}</td><td class="num">${pct(v.churn_rate)}</td><td class="num">${v.auc.toFixed(3)}</td><td class="num">${pct(v.targeted_rate)}</td></tr>`).join("")).join("");
    main.innerHTML = `
      <h1>Model card</h1>
      <p class="lede">Gradient-boosted trees (XGBoost, depth ${p.max_depth}, ${M.rounds} trees, learning rate ${p.learning_rate}) on ${MODEL.features.length} features built in SQL. Tuned by 30-trial random search with 5-fold cross-validation inside the training data; evaluated once on ${t.n.toLocaleString()} held-out customers.</p>
      <div class="section card"><h2>Held-out results</h2><div class="table-wrap" style="border:0">
        <table><thead><tr><th>Model</th><th>ROC-AUC (95% CI)</th><th>PR-AUC</th><th>Leavers in top 20%</th><th>Lift top 10%</th><th>Brier</th><th>ECE</th></tr></thead>
        <tbody>${row("<b>XGBoost</b>", t)}${row("Logistic regression (baseline)", lr)}</tbody></table></div>
        <p class="note">Cross-validated AUC: XGBoost ${cv.xgboost.mean.toFixed(3)} ± ${cv.xgboost.std.toFixed(3)}, logistic regression ${cv.logistic.mean.toFixed(3)} ± ${cv.logistic.std.toFixed(3)}. On this dataset they are statistically tied: a few strong, mostly additive signals drive churn. XGBoost is kept because it is never worse, can capture interactions and gives exact per-customer SHAP reasons; the baseline is shown so the choice can be challenged.</p>
      </div>
      <div class="section card"><h2>Fairness check</h2><p class="small muted">Gender is not a model input. Results by group on held-out customers.</p>
        <div class="table-wrap" style="border:0"><table><thead><tr><th>Group</th><th>Customers</th><th>Churn rate</th><th>AUC</th><th>Share offered</th></tr></thead><tbody>${fair}</tbody></table></div>
        <p class="note">Seniors are offered more often because they leave more often (and the model ranks them a little less well). Whether that is acceptable is a business decision; the table makes it visible.</p>
      </div>
      <div class="section prose">
        <h2>How it works</h2>
        <ul>
          <li><b>Features in SQL.</b> <code>wafa/sql/features.sql</code> turns the raw CRM columns into ${MODEL.features.length} numeric features (contract, payment, add-ons, service count, price change versus the customer's own average…).</li>
          <li><b>Exact explanations.</b> Each score is broken down with TreeSHAP; reasons are worded by rules shared between Python and this page.</li>
          <li><b>Decision, not just a score.</b> An offer is recommended when its expected value is positive, and the plan is judged against what actually happened.</li>
          <li><b>Same model everywhere.</b> The FastAPI service scores with XGBoost; this page re-implements the trees and TreeSHAP in JavaScript, and tests check both agree to 1e-4.</li>
        </ul>
        <h2>Limits</h2>
        <ul>
          <li>One public, US sample dataset; a real operator would retrain on its own data and check drift monthly.</li>
          <li>The offer's save rate is an assumption. Measure it with a randomised holdout before trusting the money figures.</li>
          <li>Predicting who leaves is not the same as predicting who an offer will change (uplift); that needs experiment data.</li>
        </ul>
      </div>`;
  }

  // ------------------------------------------------------------------ boot
  Promise.all(["metrics", "customers", "model", "reasons"].map((n) => fetch(DATA + n + ".json").then((r) => { if (!r.ok) throw new Error(n); return r.json(); })))
    .then(([m, c, model, reasons]) => {
      M = m; C = c; MODEL = model; R = reasons;
      plan.cost = M.campaign.assumptions.offer_cost; plan.save = M.campaign.assumptions.save_rate; plan.months = M.campaign.assumptions.value_months;
      route();
    })
    .catch(() => { main.innerHTML = '<p class="loading">Could not load the data. Refresh the page.</p>'; });
})();
