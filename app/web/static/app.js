const state = {
  projectId: null,
  latestArchitecture: null,
  latestResponse: null,
  latestPreview: null,
  applyInProgress: false,
};

const output = document.querySelector("#responseOutput");
const projectIdView = document.querySelector("#projectId");
const projectPhaseView = document.querySelector("#projectPhase");
const architectureMap = document.querySelector("#architectureMap");
const opsDashboard = document.querySelector("#opsDashboard");
const serverStatus = document.querySelector("#serverStatus");
const applyStatus = document.querySelector("#applyStatus");
const designDocs = document.querySelector("#designDocs");
const targetFiles = document.querySelector("#targetFiles");
const timelinePanel = document.querySelector("#timelinePanel");
const impactPanel = document.querySelector("#impactPanel");
const addonsPanel = document.querySelector("#addonsPanel");
const readinessPanel = document.querySelector("#readinessPanel");

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "content-type": "application/json",
    },
    ...options,
  });
  const body = await response.json();
  state.latestResponse = body;
  output.textContent = JSON.stringify(body, null, 2);
  if (!response.ok || body.error) {
    throw new Error(body.error ? body.error.message : `HTTP ${response.status}`);
  }
  return body.data;
}

async function refreshProject() {
  if (!state.projectId) {
    return;
  }
  const project = await api(`/api/projects/${state.projectId}`);
  projectIdView.textContent = project.id;
  projectPhaseView.textContent = project.phase;
}

async function createProject() {
  const data = await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({
      name: document.querySelector("#projectName").value,
      idea: document.querySelector("#projectIdea").value,
    }),
  });
  state.projectId = data.id;
  projectIdView.textContent = data.id;
  projectPhaseView.textContent = data.phase;
}

async function requireProject() {
  if (!state.projectId) {
    await createProject();
  }
  return state.projectId;
}

async function runStep(step) {
  const projectId = await requireProject();
  if (step === "follow-up") {
    await api(`/api/projects/${projectId}/follow-up`, { method: "POST", body: "{}" });
  } else if (step === "requirements") {
    await api(`/api/projects/${projectId}/requirements`, { method: "POST", body: "{}" });
  } else if (step === "approve-requirements") {
    await approveWithModal("requirements");
  } else if (step === "designs") {
    await api(`/api/projects/${projectId}/designs`, { method: "POST", body: "{}" });
    await loadDocuments();
  } else if (step === "approve-design") {
    await approveWithModal("design");
  } else if (step === "architecture") {
    await api(`/api/projects/${projectId}/architecture`, {
      method: "POST",
      body: JSON.stringify({ target_project_id: document.querySelector("#targetProjectId").value }),
    });
    await loadArchitecture();
  } else if (step === "security") {
    await api(`/api/projects/${projectId}/security`, { method: "POST", body: "{}" });
    await loadOps();
  } else if (step === "approve-architecture") {
    await approveWithModal("architecture");
  } else if (step === "target-app") {
    await generateTargetApp();
    await loadTargetApp();
  } else if (step === "apply") {
    await applyArchitecture();
  } else if (step === "ops") {
    await loadOps();
  } else if (step === "timeline") {
    await loadTimeline();
  }
  await refreshProject();
}

async function approveWithModal(gate) {
  const approved = await confirmAction(
    `Approve ${gate}`,
    [
      `This records an explicit approval for the ${gate} gate.`,
      "The next pipeline step will only run after this approval is saved.",
    ],
    "Approve",
  );
  if (!approved) {
    return;
  }
  await approve(gate);
}

async function approve(gate) {
  const projectId = await requireProject();
  await api(`/api/projects/${projectId}/approve`, {
    method: "POST",
    body: JSON.stringify({
      gate,
      decision: "approved",
      rationale: "Approved from demo UI",
      snapshot: state.latestResponse ? state.latestResponse.data : {},
    }),
  });
}

async function runDemoFlow() {
  await createProject();
  const projectId = await requireProject();
  await api(`/api/projects/${projectId}/follow-up`, { method: "POST", body: "{}" });
  await api(`/api/projects/${projectId}/requirements`, { method: "POST", body: "{}" });
  await approve("requirements");
  await api(`/api/projects/${projectId}/designs`, { method: "POST", body: "{}" });
  await loadDocuments();
  await approve("design");
  await api(`/api/projects/${projectId}/architecture`, {
    method: "POST",
    body: JSON.stringify({ target_project_id: document.querySelector("#targetProjectId").value }),
  });
  await loadArchitecture();
  await api(`/api/projects/${projectId}/security`, { method: "POST", body: "{}" });
  await approve("architecture");
  await generateTargetApp();
  await loadTargetApp();
  setApplyLock(true);
  try {
    await api(`/api/projects/${projectId}/apply`, { method: "POST", body: "{}" });
  } finally {
    setApplyLock(false);
  }
  await loadOps();
  await loadTimeline();
  await refreshProject();
}

async function loadArchitecture() {
  const projectId = await requireProject();
  const architecture = await api(`/api/projects/${projectId}/architecture/latest`);
  state.latestArchitecture = architecture;
  renderArchitecture(architecture);
}

function renderArchitecture(architecture) {
  const nodes = architecture.spec.nodes;
  architectureMap.classList.remove("empty");
  architectureMap.replaceChildren();
  for (const node of nodes) {
    const item = document.createElement("article");
    item.className = "node";
    appendText(item, "strong", node.name);
    appendText(item, "span", `ID: ${node.id}`);
    appendText(item, "span", `Type: ${node.type}`);
    appendText(item, "span", `Cost: ${node.cost_band}`);
    appendText(item, "span", `Params: ${JSON.stringify(node.parameters)}`);
    appendText(item, "span", `Reason: ${node.rationale}`);
    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "secondaryButton smallButton";
    selectButton.textContent = "Edit";
    selectButton.addEventListener("click", () => selectNode(node));
    item.appendChild(selectButton);
    architectureMap.appendChild(item);
  }
  for (const edge of architecture.spec.edges) {
    const item = document.createElement("article");
    item.className = "edge";
    appendText(item, "strong", edge.id);
    appendText(item, "span", `${edge.from_node} -> ${edge.to_node}`);
    appendText(item, "span", `Type: ${edge.type}`);
    appendText(item, "span", edge.description);
    architectureMap.appendChild(item);
  }
}

async function runSecurityLoop() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/security/loop`, {
    method: "POST",
    body: JSON.stringify({ rounds: 2 }),
  });
  renderAddonResult("Security Multi-round", result);
  await loadTimeline();
}

async function captureImageRequirement() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/requirements/image-artifact`, {
    method: "POST",
    body: JSON.stringify({
      file_name: document.querySelector("#imageArtifactName").value,
      description: document.querySelector("#imageArtifactNote").value,
    }),
  });
  renderAddonResult("Image Requirement Artifact", result);
}

function selectNode(node) {
  document.querySelector("#nodeId").value = node.id;
  if (node.parameters.memory) {
    document.querySelector("#nodeMemory").value = node.parameters.memory;
  }
  if (node.parameters.cpu) {
    document.querySelector("#nodeCpu").value = node.parameters.cpu;
  }
  document.querySelector("#allowUnauthenticated").checked = Boolean(node.parameters.allow_unauthenticated);
}

async function previewNodeEdit() {
  const projectId = await requireProject();
  const preview = await api(`/api/projects/${projectId}/architecture/preview-node`, {
    method: "POST",
    body: JSON.stringify(nodePatchPayload()),
  });
  state.latestPreview = preview;
  renderImpact(preview);
  await confirmAction(
    "Impact Review",
    impactLines(preview),
    "Close",
  );
}

async function saveNodeEdit(event) {
  event.preventDefault();
  const projectId = await requireProject();
  const preview = await api(`/api/projects/${projectId}/architecture/preview-node`, {
    method: "POST",
    body: JSON.stringify(nodePatchPayload()),
  });
  state.latestPreview = preview;
  renderImpact(preview);
  const accepted = await confirmAction("Save Draft After Impact Review", impactLines(preview), "Save Draft");
  if (!accepted) {
    return;
  }
  await api(`/api/projects/${projectId}/architecture/update-node`, {
    method: "POST",
    body: JSON.stringify({
      ...nodePatchPayload(),
      change_reason: "Adjusted Cloud Run parameters from demo UI",
    }),
  });
  await loadArchitecture();
  await loadTimeline();
}

async function deleteNode() {
  const projectId = await requireProject();
  const nodeId = document.querySelector("#nodeId").value.trim();
  const node = (state.latestArchitecture?.spec.nodes || []).find((item) => item.id === nodeId);
  const firstConfirm = await confirmAction(
    "Delete Node",
    [
      `Node: ${nodeId}`,
      node ? `This removes ${node.name} and every connected edge from the draft architecture.` : "This removes the selected node if it exists.",
      "This is a destructive architecture edit and requires a second confirmation.",
    ],
    "Continue",
  );
  if (!firstConfirm) {
    return;
  }
  const secondConfirm = await confirmAction(
    "Confirm Node Deletion",
    [
      "Second confirmation required.",
      "The operation creates a new architecture draft version. It does not apply cloud changes until the architecture is approved and applied.",
    ],
    "Delete Node",
  );
  if (!secondConfirm) {
    return;
  }
  await api(`/api/projects/${projectId}/architecture/delete-node`, {
    method: "POST",
    body: JSON.stringify({
      node_id: nodeId,
      confirmed: true,
      change_reason: "Deleted node from demo UI after two-step confirmation",
    }),
  });
  await loadArchitecture();
}

async function reviseFromChat(event) {
  event.preventDefault();
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/architecture/chat-revise`, {
    method: "POST",
    body: JSON.stringify({
      message: document.querySelector("#changeRequest").value,
    }),
  });
  renderImpact({
    impact: result.impact,
    requires_reapply: result.requires_reapply,
    requires_confirmation: Boolean(result.changes.allow_unauthenticated),
  });
  await confirmAction(
    "Chat Re-proposal Created",
    [
      `Draft version: ${result.version}`,
      `Changes: ${JSON.stringify(result.changes)}`,
      "Review and approve the architecture again before apply.",
    ],
    "Close",
  );
  await loadArchitecture();
}

async function addNode(event) {
  event.preventDefault();
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/architecture/add-node`, {
    method: "POST",
    body: JSON.stringify({
      node_id: document.querySelector("#newNodeId").value,
      node_type: document.querySelector("#newNodeType").value,
      name: document.querySelector("#newNodeName").value,
      parameters: parseJsonObject(document.querySelector("#newNodeParameters").value),
      change_reason: "Added node from architecture palette",
    }),
  });
  await confirmAction(
    "Node Draft Added",
    [
      `Draft version: ${result.version}`,
      `Node: ${result.node_id}`,
      "Approve the architecture before applying this resource change.",
    ],
    "Close",
  );
  await loadArchitecture();
}

async function addEdge(event) {
  event.preventDefault();
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/architecture/add-edge`, {
    method: "POST",
    body: JSON.stringify({
      edge_id: document.querySelector("#edgeId").value,
      from_node: document.querySelector("#edgeFrom").value,
      to_node: document.querySelector("#edgeTo").value,
      edge_type: document.querySelector("#edgeType").value,
      description: document.querySelector("#edgeDescription").value,
      change_reason: "Added edge from architecture editor",
    }),
  });
  await confirmAction(
    "Edge Draft Added",
    [
      `Draft version: ${result.version}`,
      `Edge: ${result.edge_id}`,
      "This relationship is now part of the draft architecture map.",
    ],
    "Close",
  );
  await loadArchitecture();
}

async function deleteEdge() {
  const projectId = await requireProject();
  const edgeId = document.querySelector("#edgeId").value.trim();
  const confirmed = await confirmAction(
    "Delete Edge",
    [
      `Edge: ${edgeId}`,
      "This removes the relationship from a new architecture draft version.",
    ],
    "Delete Edge",
  );
  if (!confirmed) {
    return;
  }
  await api(`/api/projects/${projectId}/architecture/delete-edge`, {
    method: "POST",
    body: JSON.stringify({
      edge_id: edgeId,
      change_reason: "Deleted edge from architecture editor",
    }),
  });
  await loadArchitecture();
}

function nodePatchPayload() {
  return {
    node_id: document.querySelector("#nodeId").value,
    parameter_patch: {
      memory: document.querySelector("#nodeMemory").value,
      cpu: document.querySelector("#nodeCpu").value,
      allow_unauthenticated: document.querySelector("#allowUnauthenticated").checked,
    },
  };
}

function parseJsonObject(value) {
  const parsed = JSON.parse(value || "{}");
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Parameters JSON must be an object");
  }
  return parsed;
}

function commaList(value) {
  return String(value)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function renderImpact(preview) {
  impactPanel.classList.remove("empty");
  impactPanel.replaceChildren();
  appendText(impactPanel, "strong", "Impact explanation");
  for (const line of impactLines(preview)) {
    appendText(impactPanel, "span", line);
  }
}

function impactLines(preview) {
  const impact = preview.impact || {};
  return [
    impact.summary || "No summary returned.",
    `Cost: ${impact.cost || "-"}`,
    `Security: ${impact.security || "-"}`,
    `Performance: ${impact.performance || "-"}`,
    `Requires reapply: ${preview.requires_reapply ? "yes" : "no"}`,
    `Extra confirmation: ${preview.requires_confirmation ? "yes" : "no"}`,
  ];
}

async function applyArchitecture() {
  const projectId = await requireProject();
  const approved = await confirmAction(
    "Apply Architecture",
    [
      "The editing UI will be locked while apply is running.",
      "Demo mode uses the local Cloud Build adapter and records the deployment result for Ops Dashboard.",
    ],
    "Apply",
  );
  if (!approved) {
    return;
  }
  setApplyLock(true);
  try {
    await api(`/api/projects/${projectId}/apply`, { method: "POST", body: "{}" });
    await loadOps();
    await loadTimeline();
  } finally {
    setApplyLock(false);
  }
}

function setApplyLock(locked) {
  state.applyInProgress = locked;
  document.body.classList.toggle("applying", locked);
  applyStatus.textContent = locked ? "Edit lock: apply running" : "Edit lock: open";
  for (const element of document.querySelectorAll("#nodeEditForm input, #nodeEditForm select, #nodeEditForm button")) {
    element.disabled = locked;
  }
  for (const element of document.querySelectorAll("#chatChangeForm textarea, #chatChangeForm button")) {
    element.disabled = locked;
  }
  for (const element of document.querySelectorAll("#nodeAddForm input, #nodeAddForm select, #nodeAddForm textarea, #nodeAddForm button, #edgeEditForm input, #edgeEditForm select, #edgeEditForm button")) {
    element.disabled = locked;
  }
}

async function loadTerraformPreview() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/terraform/preview`);
  renderAddonResult("Terraform Preview", result);
}

async function runGithubDemo() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/github/demo`, {
    method: "POST",
    body: JSON.stringify({
      repo_url: document.querySelector("#githubRepoUrl").value,
    }),
  });
  renderAddonResult("GitHub Demo Flow", result);
}

async function loadSubmissionBrief() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/submission/brief`);
  renderReadinessResult("Submission Brief", result);
}

async function loadCloudRunEvidence() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/runtime/cloud-run`);
  renderReadinessResult("Cloud Run Evidence", result);
}

async function loadAdapterInventory() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/adapters`);
  renderReadinessResult("Adapter Inventory", result);
}

async function runFailureDemo() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/apply/failure-demo`, {
    method: "POST",
    body: JSON.stringify({
      error_text: document.querySelector("#failureText").value,
    }),
  });
  renderReadinessResult("Failure Recovery Demo", result);
}

async function loadFailureGuidance() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/apply/failure-guidance`, {
    method: "POST",
    body: JSON.stringify({
      error_text: document.querySelector("#failureText").value,
    }),
  });
  renderAddonResult("Apply Failure Guidance", result);
}

function renderAddonResult(title, result) {
  addonsPanel.classList.remove("empty");
  addonsPanel.replaceChildren();
  addonsPanel.appendChild(renderDocument(title, JSON.stringify(result, null, 2)));
}

function renderReadinessResult(title, result) {
  readinessPanel.classList.remove("empty");
  readinessPanel.replaceChildren();
  readinessPanel.appendChild(renderDocument(title, JSON.stringify(result, null, 2)));
}

async function loadDocuments() {
  const projectId = await requireProject();
  const documents = await api(`/api/projects/${projectId}/documents`);
  designDocs.classList.remove("empty");
  designDocs.replaceChildren();
  if (!documents.length) {
    designDocs.classList.add("empty");
    designDocs.textContent = "No documents generated yet.";
    return;
  }
  for (const documentPayload of documents) {
    designDocs.appendChild(renderDocument(
      `${documentPayload.doc_type} v${documentPayload.version}`,
      documentPayload.content_md,
    ));
  }
}

async function loadTargetApp() {
  const projectId = await requireProject();
  const appPackage = await api(`/api/projects/${projectId}/target-app/latest`);
  targetFiles.classList.remove("empty");
  targetFiles.replaceChildren();
  appendText(targetFiles, "strong", appPackage.app_name);
  for (const file of appPackage.files) {
    targetFiles.appendChild(renderDocument(file.path, file.content));
  }
}

async function generateTargetApp(event) {
  if (event) {
    event.preventDefault();
  }
  const projectId = await requireProject();
  await api(`/api/projects/${projectId}/target-app`, {
    method: "POST",
    body: JSON.stringify({
      app_name: "Support Desk API",
      collection_name: "support_tickets",
      fields: commaList(document.querySelector("#targetFields").value),
      env_vars: commaList(document.querySelector("#targetEnvVars").value),
    }),
  });
  await loadTargetApp();
}

async function reviewTargetApp() {
  const projectId = await requireProject();
  const review = await api(`/api/projects/${projectId}/target-app/review`, {
    method: "POST",
    body: "{}",
  });
  await confirmAction(
    "AI Code Review",
    review.findings.map((finding) => `${finding.severity}: ${finding.message} ${finding.suggestion}`),
    "Close",
  );
}

async function loadOps() {
  const projectId = await requireProject();
  const ops = await api(`/api/projects/${projectId}/ops`);
  opsDashboard.classList.remove("empty");
  opsDashboard.replaceChildren();
  const orderedKeys = [
    "system_overview",
    "architecture_map",
    "deployment_status",
    "logs_errors",
    "cost_overview",
    "security_overview",
    "agent_actions",
    "recommended_next_actions",
  ];
  for (const key of orderedKeys) {
    const item = document.createElement("article");
    item.className = "metric";
    appendText(item, "strong", titleize(key));
    appendText(item, "span", summary(ops[key]));
    item.appendChild(renderMiniJson(ops[key]));
    opsDashboard.appendChild(item);
  }
}

async function loadTimeline() {
  const projectId = await requireProject();
  const events = await api(`/api/projects/${projectId}/timeline`);
  timelinePanel.classList.remove("empty");
  timelinePanel.replaceChildren();
  if (!events.length) {
    timelinePanel.classList.add("empty");
    timelinePanel.textContent = "No events recorded yet.";
    return;
  }
  for (const event of events) {
    const details = document.createElement("details");
    details.className = "timelineItem";
    const summaryElement = document.createElement("summary");
    summaryElement.textContent = `${event.result.toUpperCase()} - ${event.action}`;
    details.appendChild(summaryElement);
    appendText(details, "span", `Agent: ${event.agent_name || "-"}`);
    appendText(details, "span", `When: ${event.occurred_at}`);
    appendText(details, "span", `Reason: ${event.rationale_md || "No rationale recorded."}`);
    appendText(details, "span", `Decision: ${event.metadata?.decision || "-"}`);
    appendText(details, "span", `Tool: ${event.metadata?.tool_boundary || "-"}`);
    appendText(details, "span", `Adapter: ${event.metadata?.adapter_mode || "-"}`);
    appendText(details, "span", `Next: ${event.metadata?.next_expected_action || "-"}`);
    details.appendChild(renderMiniJson(event.metadata || {}));
    timelinePanel.appendChild(details);
  }
}

function renderDocument(title, content) {
  const details = document.createElement("details");
  details.className = "documentItem";
  const summaryElement = document.createElement("summary");
  summaryElement.textContent = title;
  details.appendChild(summaryElement);
  const pre = document.createElement("pre");
  pre.textContent = content;
  details.appendChild(pre);
  return details;
}

function renderMiniJson(value) {
  const pre = document.createElement("pre");
  pre.className = "miniJson";
  pre.textContent = JSON.stringify(value ?? null, null, 2);
  return pre;
}

function titleize(value) {
  return String(value)
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function summary(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `${value.length} item(s)`;
  }
  return Object.keys(value).slice(0, 6).join(", ");
}

function appendText(parent, tagName, value) {
  const element = document.createElement(tagName);
  element.textContent = String(value);
  parent.appendChild(element);
}

async function checkHealth() {
  try {
    await api("/api/health");
    serverStatus.textContent = "Server ready";
  } catch (error) {
    serverStatus.textContent = "Server unavailable";
  }
}

function confirmAction(title, lines, confirmText) {
  const backdrop = document.querySelector("#modalBackdrop");
  const modalTitle = document.querySelector("#modalTitle");
  const modalBody = document.querySelector("#modalBody");
  const confirmButton = document.querySelector("#modalConfirmButton");
  const cancelButton = document.querySelector("#modalCancelButton");
  modalTitle.textContent = title;
  modalBody.replaceChildren();
  for (const line of lines) {
    appendText(modalBody, "p", line);
  }
  confirmButton.textContent = confirmText;
  backdrop.classList.remove("hidden");
  return new Promise((resolve) => {
    const close = (answer) => {
      backdrop.classList.add("hidden");
      confirmButton.removeEventListener("click", onConfirm);
      cancelButton.removeEventListener("click", onCancel);
      resolve(answer);
    };
    const onConfirm = () => close(true);
    const onCancel = () => close(false);
    confirmButton.addEventListener("click", onConfirm);
    cancelButton.addEventListener("click", onCancel);
  });
}

document.querySelector("#createProjectButton").addEventListener("click", () => withBusy(createProject));
document.querySelector("#runDemoButton").addEventListener("click", () => withBusy(runDemoFlow));
document.querySelector("#previewNodeButton").addEventListener("click", () => withBusy(previewNodeEdit));
document.querySelector("#deleteNodeButton").addEventListener("click", () => withBusy(deleteNode));
document.querySelector("#nodeEditForm").addEventListener("submit", (event) => withBusy(() => saveNodeEdit(event)));
document.querySelector("#chatChangeForm").addEventListener("submit", (event) => withBusy(() => reviseFromChat(event)));
document.querySelector("#nodeAddForm").addEventListener("submit", (event) => withBusy(() => addNode(event)));
document.querySelector("#edgeEditForm").addEventListener("submit", (event) => withBusy(() => addEdge(event)));
document.querySelector("#deleteEdgeButton").addEventListener("click", () => withBusy(deleteEdge));
document.querySelector("#targetAppForm").addEventListener("submit", (event) => withBusy(() => generateTargetApp(event)));
document.querySelector("#reviewTargetAppButton").addEventListener("click", () => withBusy(reviewTargetApp));
document.querySelector("#imageRequirementButton").addEventListener("click", () => withBusy(captureImageRequirement));
document.querySelector("#submissionBriefButton").addEventListener("click", () => withBusy(loadSubmissionBrief));
document.querySelector("#cloudRunEvidenceButton").addEventListener("click", () => withBusy(loadCloudRunEvidence));
document.querySelector("#adapterInventoryButton").addEventListener("click", () => withBusy(loadAdapterInventory));
document.querySelector("#failureDemoButton").addEventListener("click", () => withBusy(runFailureDemo));
document.querySelector("#securityLoopButton").addEventListener("click", () => withBusy(runSecurityLoop));
document.querySelector("#terraformPreviewButton").addEventListener("click", () => withBusy(loadTerraformPreview));
document.querySelector("#githubDemoButton").addEventListener("click", () => withBusy(runGithubDemo));
document.querySelector("#failureGuidanceButton").addEventListener("click", () => withBusy(loadFailureGuidance));
for (const button of document.querySelectorAll("[data-step]")) {
  button.addEventListener("click", () => withBusy(() => runStep(button.dataset.step)));
}

async function withBusy(operation) {
  const buttons = Array.from(document.querySelectorAll("button:not(.modalButton)"));
  buttons.forEach((button) => {
    button.disabled = true;
  });
  try {
    await operation();
  } catch (error) {
    output.textContent = JSON.stringify({ error: error.message }, null, 2);
  } finally {
    if (!state.applyInProgress) {
      buttons.forEach((button) => {
        button.disabled = false;
      });
    }
  }
}

checkHealth();
