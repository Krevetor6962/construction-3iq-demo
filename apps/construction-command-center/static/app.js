"use strict";
const $ = (id) => document.getElementById(id);
let selected = null;
let currentJob = null;
let queueGeneration = 0;
let runGeneration = 0;
let queryHideTimer = null;

function positionQueueQuery() {
  const tooltip = $("queue-query-tooltip");
  if (tooltip.hidden) return;
  const button = $("queue-query-button").getBoundingClientRect();
  const margin = 16;
  const left = Math.max(margin, Math.min(button.left, window.innerWidth - tooltip.offsetWidth - margin));
  const top = Math.max(margin, Math.min(button.bottom + 8, window.innerHeight - tooltip.offsetHeight - margin));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}
function showQueueQuery() {
  clearTimeout(queryHideTimer);
  $("queue-query-tooltip").hidden = false;
  $("queue-query-button").setAttribute("aria-expanded", "true");
  positionQueueQuery();
}
function hideQueueQuery() {
  clearTimeout(queryHideTimer);
  $("queue-query-tooltip").hidden = true;
  $("queue-query-button").setAttribute("aria-expanded", "false");
}
function scheduleQueryHide() {
  clearTimeout(queryHideTimer);
  queryHideTimer = setTimeout(() => {
    const info = $("queue-query-info");
    if (!info.matches(":hover") && !info.contains(document.activeElement)) hideQueueQuery();
  }, 150);
}
function setQueueQueryInfo(title, description, query = "") {
  hideQueueQuery();
  $("queue-query-title").textContent = title;
  $("queue-query-description").textContent = description;
  $("queue-query-text").textContent = query;
  $("queue-query-text").hidden = !query;
  $("queue-query-text").scrollTop = 0;
}

function text(tag, value, className = "") {
  const element = document.createElement(tag);
  element.textContent = value;
  element.className = className;
  return element;
}
function error(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}
async function api(url, payload) {
  const options = payload === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)
  };
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
const number = (value) => new Intl.NumberFormat("en", {maximumFractionDigits: 2}).format(value);
function select(record, button) {
  ++runGeneration;
  currentJob = null;
  $("result").hidden = true;
  $("progress").replaceChildren();
  selected = record;
  $("queue").querySelectorAll("button").forEach((item) => item.classList.remove("selected"));
  button.classList.add("selected");
  $("selected-title").textContent = `${record.accountName} - ${record.projectName}`;
  $("run").disabled = false;
}
async function refresh() {
  const generation = ++queueGeneration;
  ++runGeneration;
  selected = null;
  currentJob = null;
  $("run").disabled = true;
  $("result").hidden = true;
  $("queue").replaceChildren();
  $("queue-source").textContent = "Loading customer commitments...";
  $("progress").replaceChildren();
  setQueueQueryInfo("Loading customer commitments", "Waiting for this request to finish. No previous query is shown.");
  error("");
  try {
    const data = await api(`/api/scenarios?mode=${encodeURIComponent($("mode").value)}`);
    if (generation !== queueGeneration) return;
    if (data.source === "fabric_graphmodel") {
      if (typeof data.query === "string" && data.query.trim()) {
        setQueueQueryInfo(
          "Executed Fabric GQL query",
          "GQL (Graph Query Language), not GraphQL. GET /api/scenarios?mode=live calls the Fabric GraphModel executeQuery endpoint. This is the exact query returned with the loaded list.",
          data.query
        );
      } else {
        setQueueQueryInfo("GQL query unavailable", "The live list loaded, but its response did not include the executed query.");
      }
    } else {
      setQueueQueryInfo("Offline data - no graph query", "This list is loaded from local synthetic scenario records. No Fabric, GQL, or GraphQL query ran.");
    }
    $("queue-source").textContent = `${data.records.length} commitments | ${data.source}`;
    const ordered = [...data.records].sort((a, b) => Number(b.anchor) - Number(a.anchor) || a.recordId.localeCompare(b.recordId));
    for (const record of ordered) {
      const button = document.createElement("button");
      button.append(text("strong", record.accountName), text("span", record.projectName),
        text("small", `${record.productName} | ${number(record.orderedQty)} ${record.unit}`),
        text("small", `${record.currency} ${number(record.unfilledValue)} unfilled | ${record.recordId}`));
      button.addEventListener("click", () => select(record, button));
      $("queue").append(button);
    }
    if (ordered.length) select(ordered[0], $("queue").firstElementChild);
  } catch (exc) {
    if (generation === queueGeneration) {
      $("queue-source").textContent = "Customer commitments unavailable";
      setQueueQueryInfo("Customer commitments could not be loaded", "No successful query result is available for this request. See the error message for details.");
      error(`${exc.message}. Live mode never falls back silently. Select Offline synthetic demo only if you intend to use local fixtures.`);
    }
  }
}
function render(result) {
  $("result").hidden = false;
  $("chat").replaceChildren();
  const totals = result.context.totals;
  $("metrics").replaceChildren();
  for (const [label, value] of [
    ["Committed", `${number(totals.orderedQty)} ${totals.unit}`],
    ["Available stock", `${number(totals.availableQty)} ${totals.unit}`],
    ["Shortage", `${number(totals.shortageQty)} ${totals.unit}`],
    ["Unfilled order value", `${totals.currency} ${number(totals.unfilledValue)}`]
  ]) {
    const tile = text("div", "", "metric");
    tile.append(text("span", label), text("strong", value));
    $("metrics").append(tile);
  }
  const pack = result.actionPackage;
  $("recommendation").textContent = pack
    ? `${result.mode === "offline" ? "OFFLINE SYNTHETIC DEMO\n\n" : ""}${pack.groundedAnswer || pack.summary}`
    : "Recommendation withheld. At least one evidence lane failed; inspect the error below.";
  $("allocation").replaceChildren();
  $("next-steps").replaceChildren();
  $("draft").textContent = pack ? pack.customerDraft : "No draft: incomplete evidence.";
  $("ask").disabled = !pack;
  if (pack) {
    const table = document.createElement("table");
    const head = document.createElement("tr");
    for (const label of ["Customer / project", "Proposed quantity", "Unfilled"]) head.append(text("th", label));
    table.append(head);
    for (const row of pack.proposedAllocations) {
      const tr = document.createElement("tr");
      tr.append(text("td", `${row.accountName} / ${row.projectName}`),
        text("td", `${number(row.quantity)} ${row.unit}`), text("td", `${number(row.unfilledQty)} ${row.unit}`));
      table.append(tr);
    }
    $("allocation").append(text("p", "Proposal only - human allocation approval required.", "notice"), table);
    const list = document.createElement("ul");
    for (const step of pack.nextSteps) list.append(text("li", step));
    $("next-steps").append(list);
  }
  $("lanes").replaceChildren();
  for (const lane of result.evidenceLanes) {
    const card = text("article", "", "lane");
    card.append(text("h3", lane.label),
      text("span", `${lane.status} | ${lane.sourceMode}${lane.synthetic ? " | synthetic data" : ""}`, `badge ${lane.status}`),
      text("p", lane.summary));
    const details = document.createElement("details");
    details.append(text("summary", "Inspect cited source evidence"), text("pre", JSON.stringify(lane.evidence, null, 2)));
    card.append(details);
    $("lanes").append(card);
  }
  $("trace").textContent = JSON.stringify({
    mode: result.mode, fabricEvidenceMode: result.fabricEvidenceMode, queueSource: result.context.queueSource, toolCalls: result.toolCalls,
    agentFramework: result.agentFramework, approvalRequired: result.approvalRequired
  }, null, 2);
}
async function execute() {
  if (!selected) return;
  const generation = ++runGeneration;
  $("run").disabled = true;
  $("result").hidden = true;
  currentJob = null;
  error("");
  try {
    let job = await api("/api/orchestrate/start", {
      question: $("question").value, recordId: selected.recordId, mode: $("mode").value
    });
    while (generation === runGeneration) {
      $("progress").replaceChildren(...Object.entries(job.stages).map(([name, value]) =>
        text("span", `${name}: ${value.status}`, `badge ${value.status}`)));
      if (job.status !== "running") {
        if (job.status === "failed") throw new Error(job.error);
        currentJob = job.jobId;
        render(job.result);
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
      job = await api(`/api/jobs/${job.jobId}`);
    }
  } catch (exc) {
    if (generation === runGeneration) error(exc.message);
  } finally {
    if (generation === runGeneration) $("run").disabled = !selected;
  }
}
async function ask() {
  if (!currentJob || !$("followup").value.trim()) return;
  const jobId = currentJob;
  const question = $("followup").value;
  $("ask").disabled = true;
  error("");
  try {
    const reply = await api("/api/orchestrate/chat", {jobId, question});
    if (jobId !== currentJob) return;
    $("chat").append(text("div", question, "chat-message"), text("div", reply.answer, "chat-message"));
    $("followup").value = "";
  } catch (exc) { if (jobId === currentJob) error(exc.message); }
  finally { if (jobId === currentJob) $("ask").disabled = false; }
}
$("refresh").addEventListener("click", refresh);
$("queue-query-info").addEventListener("pointerenter", showQueueQuery);
$("queue-query-info").addEventListener("pointerleave", scheduleQueryHide);
$("queue-query-info").addEventListener("focusin", showQueueQuery);
$("queue-query-info").addEventListener("focusout", scheduleQueryHide);
$("queue-query-button").addEventListener("click", showQueueQuery);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("queue-query-tooltip").hidden) {
    if ($("queue-query-tooltip").contains(document.activeElement)) $("queue-query-button").focus();
    hideQueueQuery();
  }
});
document.addEventListener("pointerdown", (event) => {
  if (!$("queue-query-info").contains(event.target)) hideQueueQuery();
});
window.addEventListener("resize", positionQueueQuery);
window.addEventListener("scroll", positionQueueQuery, true);
$("mode").addEventListener("change", refresh);
$("run").addEventListener("click", execute);
$("ask").addEventListener("click", ask);
$("followup").addEventListener("keydown", (event) => { if (event.key === "Enter") ask(); });
api("/api/health").then((status) => {
  $("title").textContent = status.displayName;
  document.title = status.displayName;
  $("supplier").textContent = status.supplierName;
  $("asof").textContent = `Scenario as of ${status.asOfDate}`;
  $("fabric-mode").textContent = status.fabricEvidenceMode === "ontology_graph"
    ? "Fabric IQ: live ontology graph (not native NL)"
    : "Fabric IQ: native ontology knowledge base";
  $("health").textContent = status.cloud.configured ? "Cloud configured - test with a live run" : "Cloud not deployed/configured";
  return refresh();
}).catch((exc) => error(exc.message));
