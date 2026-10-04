import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";
import assert from "node:assert/strict";
import {createHash} from "node:crypto";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(root, "docs", "architecture");
fs.mkdirSync(output, {recursive: true});
const palette = {
  neutral: {stroke: "#475569", fill: "#E4EDF8"},
  fabric: {stroke: "#0078D4", fill: "#CFE7FC"},
  foundry: {stroke: "#6D28D9", fill: "#E7D5FB"},
  work: {stroke: "#C47700", fill: "#FFE1A6"},
  success: {stroke: "#15803D", fill: "#D1F1C6"},
};
const iconNames = {
  fabric: "fabric_48_color.svg",
  lakehouse: "lakehouse_64_item.svg",
  notebook: "notebook_64_item.svg",
  eventhouse: "event_house_64_item.svg",
  kql: "kql_database_64_item.svg",
  graph: "graph_model_instance_64_item.svg",
  agent: "data_agent_64_item.svg",
  ontology: "ontology-symbol.svg",
  sqlEndpoint: "sql-endpoint-symbol.svg",
  policy: "policy-knowledge-symbol.svg",
  work: "synthetic-work-symbol.svg",
};
const imageFiles = {};
const icons = new Map();
for (const [key, filename] of Object.entries(iconNames)) {
  const bytes = fs.readFileSync(path.join(output, "icons", filename));
  const markup = bytes.toString("utf8");
  assert(!/<script\b|<foreignObject\b|(?:href|src)\s*=\s*["']https?:/i.test(markup), `Unsafe icon: ${filename}`);
  const svgTag = markup.match(/<svg\b[^>]*>/)?.[0];
  assert(svgTag, `Missing SVG root: ${filename}`);
  const viewBox = svgTag.match(/viewBox=["']([\d.\s-]+)["']/);
  const width = viewBox
    ? Number(viewBox[1].trim().split(/\s+/)[2])
    : Number(svgTag.match(/\bwidth=["']([\d.]+)(?:px)?["']/)?.[1]);
  const height = viewBox
    ? Number(viewBox[1].trim().split(/\s+/)[3])
    : Number(svgTag.match(/\bheight=["']([\d.]+)(?:px)?["']/)?.[1]);
  assert(width === height && width > 0, `Expected square icon: ${filename}`);
  const fileId = createHash("sha256").update(bytes).digest("hex").slice(0, 40);
  icons.set(key, fileId);
  imageFiles[fileId] = {
    id: fileId, mimeType: "image/svg+xml",
    dataURL: `data:image/svg+xml;base64,${bytes.toString("base64")}`,
    created: 1791066943000, lastRetrieved: 1791066943000,
  };
}
let sequence = 0;

function scene(name, width, height) {
  const elements = [];
  const base = (type, id, x, y, w, h, color = "neutral") => ({
    type, id: `${name}-${id}`, x, y, width: w, height: h,
    angle: 0, strokeColor: palette[color].stroke, backgroundColor: "transparent",
    fillStyle: "solid", strokeWidth: 2, strokeStyle: "solid", roughness: 0,
    opacity: 100, groupIds: [], frameId: null, roundness: {type: 3},
    seed: 17000 + sequence++, version: 1, versionNonce: 27000 + sequence++,
    isDeleted: false, boundElements: [], updated: 1791046800000, link: null, locked: false,
  });
  function text(id, x, y, w, value, size = 20, align = "left") {
    const element = {
      ...base("text", id, x, y, w, size * 2.5 * value.split("\n").length),
      strokeColor: "#000000", roundness: null, text: value, originalText: value,
      fontSize: size, fontFamily: 2, textAlign: align, verticalAlign: "top",
      containerId: null, autoResize: false, lineHeight: 1.35,
    };
    elements.push(element);
    return element;
  }
  function rect(id, x, y, w, h, color = "neutral", container = false, dashed = false) {
    const element = {
      ...base("rectangle", id, x, y, w, h, color),
      backgroundColor: container ? "transparent" : palette[color].fill,
      strokeStyle: dashed ? "dashed" : "solid", strokeWidth: container ? 3 : 2,
      customData: {container},
    };
    elements.push(element);
    return element;
  }
  function icon(id, key, x, y, size = 48, groupId = null) {
    const fileId = icons.get(key);
    assert(fileId, `Unknown icon ${key}`);
    const element = {
      ...base("image", id, x, y, size, size),
      strokeColor: "transparent", roundness: null, fileId, status: "saved",
      scale: [1, 1], crop: null, customData: {icon: key},
    };
    if (groupId) element.groupIds = [groupId];
    elements.push(element);
    return element;
  }
  function box(id, x, y, w, h, title, lines, color = "neutral", dashed = false, titleSize = 25, iconKey = null) {
    const shape = rect(id, x, y, w, h, color, false, dashed);
    const titleInset = iconKey ? 88 : 24;
    const heading = text(`${id}-title`, x + titleInset, y + 22, w - titleInset - 24, title, titleSize);
    const body = text(`${id}-body`, x + 24, y + 76, w - 48, lines.join("\n"), 20);
    for (const element of [shape, heading, body]) element.groupIds = [`${name}-${id}-group`];
    if (iconKey) icon(`${id}-icon`, iconKey, x + 24, y + 16, 48, `${name}-${id}-group`);
    return shape;
  }
  function note(id, x, y, w, h, lines, color = "neutral", dashed = false, size = 20) {
    const shape = rect(id, x, y, w, h, color, false, dashed);
    const label = text(`${id}-text`, x + 20, y + 18, w - 40, lines.join("\n"), size);
    shape.groupIds = label.groupIds = [`${name}-${id}-group`];
    return shape;
  }
  function arrow(id, points, color = "neutral", {both = false, dashed = false, head = true} = {}) {
    const x = points[0][0], y = points[0][1];
    const xs = points.map(p => p[0]), ys = points.map(p => p[1]);
    const element = {
      ...base("arrow", id, x, y, Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), color),
      points: points.map(([px, py]) => [px - x, py - y]),
      startBinding: null, endBinding: null, startArrowhead: both ? "arrow" : null,
      endArrowhead: head ? "arrow" : null, roundness: null,
      strokeStyle: dashed ? "dashed" : "solid",
    };
    elements.push(element);
    return element;
  }
  function heading(title, subtitle, number) {
    text("eyebrow", 70, 34, width - 140, `CONSTRUCTION 3IQ   /   ${number}`, 19);
    text("title", 70, 74, width - 140, title, 48);
    text("subtitle", 70, 142, width - 140, subtitle, 22);
    arrow("header-rule", [[70, 188], [width - 70, 188]], "neutral", {head: false});
  }
  return {name, width, height, elements, text, rect, box, note, arrow, heading, icon};
}

const overview = scene("overview", 2200, 1640);
overview.heading(
  "From constrained stock to a grounded decision",
  "The live presenter experience: structured facts + written rules + people context. Every action remains a proposal.",
  "01  LIVE EXPERIENCE",
);
overview.box("ui", 70, 230, 500, 180, "01  Local presenter app",
  ["Browser + Python API | localhost:8095", "Direct GQL queue / 200 commitments"]);
overview.box("orchestrator", 760, 230, 680, 180, "02  Agent Framework orchestrator",
  ["Prepare -> parallel specialists -> shape response", "Final synthesis calls Foundry gpt-5.4"]);
overview.box("output", 1640, 230, 490, 180, "04  Human review", [
  "Evidence, proposed quantities and owners", "Customer-safe drafts; no actions executed",
], "success");
overview.arrow("question", [[570, 318], [760, 318]]);
overview.text("question-label", 580, 264, 170, "Question +\nrecord ID", 17, "center");
overview.arrow("answer", [[1440, 318], [1640, 318]], "success");
overview.text("answer-label", 1450, 264, 180, "Cited answer +\naction package", 17, "center");
overview.text("lane-heading", 70, 458, 900, "03  Parallel evidence lanes", 29);
overview.text("lane-return-note", 1460, 460, 670, "Grounded replies return to the local orchestrator.", 21);
overview.arrow("request-trunk", [[1100, 410], [1100, 540]], "neutral", {head: false});
overview.arrow("request-bus", [[380, 540], [1820, 540]], "neutral", {head: false});
overview.arrow("fabric-route", [[380, 540], [380, 582]], "fabric", {both: true});
overview.arrow("policy-route", [[1100, 540], [1100, 582]], "foundry", {both: true});
overview.arrow("work-route", [[1820, 540], [1820, 582]], "work", {both: true});

const lanes = [
  {
    x: 70, id: "fabric", color: "fabric", title: "FABRIC IQ  /  Connected facts",
    agentTitle: "Fabric IQ specialist", agent: ["Foundry prompt agent v1 | East US 2", "Find exposure, peers and stock constraints"],
    toolTitle: "Read-only local graph tool", tool: ["Runs in the local Python process", "Fresh Fabric user token; explicit GQL"],
    sourceTitle: "Fabric GraphModel", source: ["Live GQL over shared-stock relationships", "31 entity types / 52 relationship types"], sourceIcon: "graph",
    toolLabel: "Function request / result", sourceLabel: "GQL / cited records",
  },
  {
    x: 790, id: "policy", color: "foundry", title: "FOUNDRY IQ  /  Written rules",
    agentTitle: "Foundry IQ specialist", agent: ["Foundry prompt agent v1 | East US 2", "Retrieve policy, limits and approval rules"],
    toolTitle: "Read-only local retrieval tool", tool: ["Calls Azure AI Search knowledge-base REST", "Fresh Search token; snippets + citations"],
    sourceTitle: "Policy knowledge base", source: ["Azure AI Search file knowledge source", "8 synthetic documents | West US 3"], sourceIcon: "policy",
    toolLabel: "Function request / result", sourceLabel: "Retrieve / cited snippets",
  },
  {
    x: 1510, id: "work", color: "work", title: "WORK IQ  /  Simulated context",
    agentTitle: "Work IQ specialist", agent: ["Foundry prompt agent v1 | East US 2", "Identify owners and informal commitments"],
    toolTitle: "Read-only local Search tool", tool: ["Filters by the selected stock-pool records", "Requires sourceType = synthetic"],
    sourceTitle: "Synthetic collaboration index", source: ["600 owner, meeting and message records", "Not connected to live Microsoft 365"], sourceIcon: "work",
    toolLabel: "Function request / result", sourceLabel: "Scoped query / context",
  },
];
for (const lane of lanes) {
  overview.rect(`${lane.id}-container`, lane.x, 585, 620, 875, lane.color, true);
  overview.text(`${lane.id}-heading`, lane.x + 26, 610, 568, lane.title, 26);
  overview.box(`${lane.id}-agent`, lane.x + 30, 695, 560, 180, lane.agentTitle, lane.agent, lane.color, false, 25);
  overview.box(`${lane.id}-tool`, lane.x + 30, 955, 560, 180, lane.toolTitle, lane.tool, lane.color, false, 24);
  overview.box(`${lane.id}-source`, lane.x + 30, 1215, 560, 190, lane.sourceTitle, lane.source, lane.color, false, 24, lane.sourceIcon);
  const mid = lane.x + 310;
  overview.arrow(`${lane.id}-tool-call`, [[mid, 875], [mid, 955]], lane.color, {both: true});
  overview.text(`${lane.id}-tool-label`, mid + 18, 898, 260, lane.toolLabel, 16);
  overview.arrow(`${lane.id}-source-call`, [[mid, 1135], [mid, 1215]], lane.color, {both: true});
  overview.text(`${lane.id}-source-label`, mid + 18, 1158, 260, lane.sourceLabel, 16);
}
overview.note("golden", 70, 1490, 1330, 108, [
  "GOLDEN CASE   1,800 m\u00b2 committed | 1,200 available | 600 short | EUR 12,000 unfilled",
  "All three grounded replies return to the orchestrator before final synthesis.",
], "success", false, 20);
overview.note("guardrails", 1440, 1490, 690, 108, [
  "All data synthetic. No silent offline fallback.",
  "Native NL KB not verified; direct GQL is live.",
], "neutral", false, 19);

const technical = scene("technical", 2200, 1660);
technical.heading(
  "Where the data, models and controls live",
  "Resource and data map. The local app is not Azure-hosted; the Fabric capacity is shared outside the new Azure resource group.",
  "02  TECHNICAL MAP",
);
technical.rect("local-boundary", 70, 275, 430, 1025, "neutral", true);
technical.text("local-heading", 94, 300, 380, "LOCAL PREPARATION", 24);
technical.box("assets", 94, 395, 382, 280, "Synthetic demo assets", [
  "100 customers / 12 materials",
  "200 commitments / 31 tables",
  "8 policies / 600 work records",
  "Snapshot: 02 October 2026",
], "neutral", false, 24);
technical.box("deploy", 94, 805, 382, 220, "Deploy + seed scripts", [
  "Bicep + Azure CLI",
  "Fabric REST + OneLake upload",
  "Owned IDs saved in a manifest",
], "neutral", false, 25);
technical.arrow("assets-to-deploy", [[285, 675], [285, 805]]);
technical.text("build-label", 102, 720, 365, "Deterministic, repeatable inputs", 19, "center");
technical.note("local-scope", 94, 1105, 382, 140, [
  "Separate Construction_3IQ project",
  "Original demo remains unchanged",
  "Local jobs are ephemeral",
], "neutral", false, 18);

technical.rect("fabric-boundary", 560, 275, 840, 1025, "fabric", true);
technical.icon("fabric-brand", "fabric", 590, 296, 40);
technical.text("fabric-heading", 646, 300, 724, "FABRIC WORKSPACE  /  West US 3", 26);
technical.text("fabric-capacity", 590, 350, 780, "Construction 3IQ Demo | existing F32 capacity, outside the demo resource group", 19);
technical.box("notebook", 590, 425, 780, 160, "ConstructionSupplyIngest notebook", [
  "Loads 31 Delta tables from OneLake files",
  "Includes Lakehouse mirrors of the four event tables",
], "fabric", false, 25, "notebook");
technical.box("lakehouse", 590, 675, 330, 190, "Lakehouse", [
  "31 Delta tables",
  "SQL analytics endpoint",
], "fabric", false, 26, "lakehouse");
technical.icon("lakehouse-sql-icon", "sqlEndpoint", 860, 809, 40, "technical-lakehouse-group");
technical.text("lakehouse-sql-label", 614, 816, 210, "SQL endpoint", 16).groupIds = ["technical-lakehouse-group"];
technical.box("events", 1040, 675, 330, 190, "Eventhouse", [
  "ConstructionSupplyEvents",
  "4 populated event tables",
], "fabric", false, 24, "eventhouse");
technical.icon("events-kql-icon", "kql", 1310, 809, 40, "technical-events-group");
technical.text("events-kql-label", 1064, 816, 210, "KQL database", 16).groupIds = ["technical-events-group"];
technical.box("ontology", 590, 1020, 330, 190, "Ontology", [
  "31 entities / 52 relations",
  "Bound to Lakehouse tables",
], "fabric", false, 24, "ontology");
technical.box("graph", 1040, 1020, 330, 190, "GraphModel", [
  "Ontology-generated graph",
  "Live GQL for the 3IQ app",
], "fabric", false, 25, "graph");
technical.arrow("seed-notebook", [[476, 915], [530, 915], [530, 500], [590, 500]], "neutral", {dashed: true});
technical.text("seed-notebook-label", 70, 1035, 420, "Provisioning only; not a runtime tool", 17, "center");
technical.arrow("notebook-delta", [[755, 585], [755, 675]], "fabric");
technical.text("delta-label", 780, 616, 190, "Typed Delta load", 17);
technical.arrow("kql-load", [[476, 935], [1205, 935], [1205, 865]], "neutral", {dashed: true});
technical.text("kql-load-label", 840, 892, 355, "Separate KQL table ingestion", 17, "center");
technical.arrow("bindings", [[755, 865], [755, 1020]], "fabric");
technical.text("bindings-label", 588, 963, 155, "Table bindings", 17);
technical.arrow("generated", [[920, 1115], [1040, 1115]], "fabric");
technical.text("generated-label", 925, 1066, 110, "Generates", 16, "center");
technical.text("fabric-helpers", 590, 1230, 780,
  "Also present: ontology helper Lakehouse + SQL endpoint;\ndefault empty KQL database (not the selected event source).", 17);

technical.rect("azure-boundary", 1460, 275, 670, 1025, "foundry", true);
technical.text("azure-heading", 1490, 300, 610, "AZURE RESOURCE GROUP", 26);
technical.text("azure-rg", 1490, 350, 610, "rg-construction-3iq-demo", 22);
technical.box("search", 1490, 425, 610, 280, "Azure AI Search  /  Basic  /  West US 3", [
  "Policy KB: authenticated file source + citations",
  "Work index: 600 explicitly synthetic records",
  "Native Fabric KB: unused (NL query limitation)",
  "1 replica / 1 partition / managed identity",
], "foundry", false, 24);
technical.box("foundry", 1490, 930, 610, 300, "Foundry account + project  /  East US 2", [
  "S0 | three prompt specialists, version 1",
  "gpt-5.4: GlobalStandard, capacity 50",
  "text-embedding-3-large: Standard, capacity 10",
  "Specialist reasoning + final answer synthesis",
], "foundry", false, 23);
technical.arrow("search-models", [[1795, 705], [1795, 930]], "foundry", {both: true});
technical.text("search-model-label", 1495, 763, 285,
  "Search managed identity\nModel planning + embeddings\nScoped OpenAI User role", 18);
technical.arrow("seed-search", [[476, 510], [516, 510], [516, 235], [1795, 235], [1795, 275]], "neutral", {dashed: true});
technical.text("seed-search-label", 850, 204, 690, "Authenticated file + index seeding into Search (not public Blob access)", 17, "center");

technical.note("identity", 70, 1370, 430, 210, [
  "ACCESS & SAFETY",
  "User tokens for Fabric / Search / Foundry",
  "TLS + narrowly scoped resource RBAC",
  "No keys in the browser or diagrams",
  "Human approval; no automatic writes",
], "neutral", false, 18);
technical.box("prepared-agent", 560, 1370, 840, 210, "PREPARED ONLY  /  Fabric data agent", [
  "Demand Readiness Investigator: graph + Lakehouse SQL + KQL",
  "12 source queries validated; instructions and demo story ready",
  "No DataAgent item created. No app-to-agent integration.",
], "work", true, 25, "agent");
technical.arrow("future-sources", [[980, 1370], [980, 1300]], "work", {dashed: true});
technical.box("ancillary", 1460, 1370, 670, 210, "OPTIONAL  /  Tenant-managed ancillary", [
  "Storage LRS: public network + shared keys disabled",
  "Not the active policy source; private policies container",
  "Storage events -> antimalware, if tenant-configured",
], "neutral", true, 23);
technical.text("technical-legend", 70, 1610, 2060,
  "Solid = active dependency. Dashed = provisioning, prepared-only or ancillary context. Resource IDs and full inventory are in the companion architecture note.", 18);

function xml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}
function renderSvg(view) {
  const defs = [];
  const elements = view.elements.map(element => {
    const dash = element.strokeStyle === "dashed" ? ' stroke-dasharray="10 7"' : "";
    if (element.type === "rectangle") {
      return `<rect x="${element.x}" y="${element.y}" width="${element.width}" height="${element.height}" rx="16" fill="${element.backgroundColor === "transparent" ? "none" : element.backgroundColor}" stroke="${element.strokeColor}" stroke-width="${element.strokeWidth}"${dash}/>`;
    }
    if (element.type === "text") {
      const x = element.textAlign === "center" ? element.x + element.width / 2 : element.x;
      const anchor = element.textAlign === "center" ? "middle" : "start";
      const spans = element.text.split("\n").map((line, index) =>
        `<tspan x="${x}" y="${element.y + element.fontSize + index * element.fontSize * element.lineHeight}">${xml(line)}</tspan>`
      ).join("");
      return `<text data-element-id="${element.id}" fill="#000000" font-family="Arial, Helvetica, sans-serif" font-size="${element.fontSize}" text-anchor="${anchor}">${spans}</text>`;
    }
    if (element.type === "arrow") {
      const marker = `${element.id}-head`;
      defs.push(`<marker id="${marker}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M1 1 L8 5 L1 9" fill="none" stroke="${element.strokeColor}" stroke-width="1.5" stroke-linejoin="round"/></marker>`);
      const points = element.points.map(([x, y]) => `${element.x + x},${element.y + y}`).join(" ");
      return `<polyline points="${points}" fill="none" stroke="${element.strokeColor}" stroke-width="2.2" stroke-linejoin="round"${dash}${element.startArrowhead ? ` marker-start="url(#${marker})"` : ""}${element.endArrowhead ? ` marker-end="url(#${marker})"` : ""}/>`;
    }
    if (element.type === "image") {
      const file = imageFiles[element.fileId];
      assert(file, `Missing embedded icon: ${element.id}`);
      return `<image data-element-id="${element.id}" x="${element.x}" y="${element.y}" width="${element.width}" height="${element.height}" preserveAspectRatio="xMidYMid meet" href="${file.dataURL}"/>`;
    }
    throw new Error(`Unsupported shape: ${element.type}`);
  });
  return `<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="${view.width}" height="${view.height}" viewBox="0 0 ${view.width} ${view.height}" role="img" aria-labelledby="diagram-title diagram-description"><title id="diagram-title">${xml(view.name === "overview" ? "Construction 3IQ live architecture" : "Construction 3IQ resource and data map")}</title><desc id="diagram-description">Verified construction demo architecture. All business data is synthetic. Native ontology natural-language KB is not used. The complementary Fabric data agent is prepared only, not deployed.</desc><defs>${defs.join("")}</defs><rect width="100%" height="100%" fill="#FFFFFF"/>${elements.join("\n")}</svg>\n`;
}

const views = [overview, technical];
const combined = [];
for (const [index, view] of views.entries()) {
  const offset = index * 2380;
  const frameId = `frame-${view.name}`;
  combined.push({
    type: "frame", id: frameId, name: index === 0 ? "01 - Live experience" : "02 - Resource and data map",
    x: offset, y: 0, width: view.width, height: view.height, angle: 0,
    strokeColor: "#64748B", backgroundColor: "transparent", fillStyle: "solid", strokeWidth: 1,
    strokeStyle: "solid", roughness: 0, opacity: 100, groupIds: [], frameId: null, roundness: null,
    seed: 80000 + index, version: 1, versionNonce: 81000 + index, isDeleted: false,
    boundElements: [], updated: 1791046800000, link: null, locked: false,
  });
  for (const element of view.elements) {
    assert(Number.isFinite(element.width) && Number.isFinite(element.height));
    if (element.type === "text") {
      assert(element.width > 0 && element.height > 0);
      assert.equal(element.strokeColor, "#000000");
      assert(element.y + element.fontSize * element.lineHeight * element.text.split("\n").length <= view.height, element.id);
    }
    if (element.customData?.container) assert.equal(element.backgroundColor, "transparent");
    if (element.type === "image") assert(imageFiles[element.fileId]);
    combined.push({...element, x: element.x + offset, frameId});
  }
  fs.writeFileSync(path.join(output, `construction-3iq-${view.name}.svg`), renderSvg(view));
}
assert.equal(new Set(combined.map(element => element.id)).size, combined.length);
const document = {
  type: "excalidraw", version: 2, source: "https://github.com/Krevetor6962/construction-3iq-demo",
  elements: combined,
  appState: {
    viewBackgroundColor: "#FFFFFF", gridSize: null, gridModeEnabled: false,
    theme: "light", currentItemFontFamily: 2, currentItemRoughness: 0,
    frameRendering: {enabled: true, name: true, outline: true, clip: false},
  },
  files: imageFiles,
};
fs.writeFileSync(path.join(output, "construction-3iq-architecture.excalidraw"), JSON.stringify(document, null, 2) + "\n");
console.log(`Generated ${combined.length} editable elements across two architecture views in ${output}`);
