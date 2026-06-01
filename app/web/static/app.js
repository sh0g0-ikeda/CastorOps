const state = {
  projectId: null,
  latestArchitecture: null,
  latestResponse: null,
  latestPreview: null,
  applyInProgress: false,
};
const STORAGE_KEY = "castorops.projectId";

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
    const error = new Error(body.error ? body.error.message : `HTTP ${response.status}`);
    error.apiError = body.error || { code: `HTTP_${response.status}`, details: {} };
    error.status = response.status;
    throw error;
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

function persistProjectId(projectId) {
  try {
    window.localStorage.setItem(STORAGE_KEY, projectId);
  } catch (error) {
    // Browser storage can be unavailable in some embedded review contexts.
  }
}

function clearPersistedProjectId() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    // Best-effort cleanup only.
  }
}

function restoreProjectId() {
  try {
    const projectId = window.localStorage.getItem(STORAGE_KEY);
    if (projectId) {
      state.projectId = projectId;
      projectIdView.textContent = projectId;
      projectPhaseView.textContent = "復元中";
    }
  } catch (error) {
    state.projectId = null;
  }
}

async function restoreWorkspace() {
  restoreProjectId();
  if (!state.projectId) {
    return;
  }
  try {
    await refreshProject();
    await refreshWorkspacePanels();
    serverStatus.textContent = "サーバ準備完了 - ワークスペース復元済み";
  } catch (error) {
    if (error.apiError?.code === "NOT_FOUND") {
      clearPersistedProjectId();
      state.projectId = null;
      projectIdView.textContent = "-";
      projectPhaseView.textContent = "-";
      serverStatus.textContent = "サーバ準備完了 - デモ一括実行で状態を再作成できます";
      return;
    }
    throw error;
  }
}

async function refreshWorkspacePanels() {
  await safeLoad(loadArchitecture);
  await safeLoad(loadDocuments);
  await safeLoad(loadTargetApp);
  await safeLoad(loadOps);
  await safeLoad(loadTimeline);
  await safeLoad(loadSubmissionBrief);
  await safeLoad(loadCloudRunEvidence);
}

async function safeLoad(loader) {
  try {
    await loader();
  } catch (error) {
    if (error.apiError?.code !== "NOT_FOUND" && error.apiError?.code !== "PHASE_CONFLICT") {
      throw error;
    }
  }
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
  persistProjectId(data.id);
  projectIdView.textContent = data.id;
  projectPhaseView.textContent = data.phase;
}

async function requireProject() {
  if (!state.projectId) {
    restoreProjectId();
  }
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
    `${gateLabel(gate)}を承認`,
    [
      `${gateLabel(gate)}ゲートの明示的な承認を記録します。`,
      "この承認が保存されるまで次のパイプライン処理は実行されません。",
    ],
    "承認する",
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
      rationale: "デモUIから承認",
      snapshot: state.latestResponse ? state.latestResponse.data : {},
    }),
  });
}

async function runDemoFlow() {
  setApplyLock(true);
  try {
    const result = await api("/api/demo/run", {
      method: "POST",
      body: JSON.stringify({
        name: document.querySelector("#projectName").value,
        idea: document.querySelector("#projectIdea").value,
        target_project_id: document.querySelector("#targetProjectId").value,
        repo_url: document.querySelector("#githubRepoUrl").value,
        failure_text: document.querySelector("#failureText").value,
      }),
    });
    state.projectId = result.project_id;
    persistProjectId(result.project_id);
    renderFullWorkspace(result);
  } finally {
    setApplyLock(false);
  }
}

function renderFullWorkspace(result) {
  const project = result.project || {};
  projectIdView.textContent = result.project_id || project.id || "-";
  projectPhaseView.textContent = project.phase || "-";
  if (result.architecture) {
    state.latestArchitecture = result.architecture;
    renderArchitecture(result.architecture);
  }
  if (Array.isArray(result.design_documents)) {
    renderDocuments(result.design_documents);
  }
  if (result.target_app) {
    renderTargetApp(result.target_app);
  }
  if (result.ops) {
    renderOps(result.ops);
  }
  if (Array.isArray(result.timeline)) {
    renderTimeline(result.timeline);
  }
  if (result.readiness) {
    renderReadinessBundle(result.readiness);
  }
  if (result.optional_delivery) {
    renderAddonResult("追加デモ証跡", result.optional_delivery);
  }
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
    appendText(item, "span", `種別: ${node.type}`);
    appendText(item, "span", `コスト帯: ${node.cost_band}`);
    appendText(item, "span", `パラメータ: ${JSON.stringify(node.parameters)}`);
    appendText(item, "span", `理由: ${node.rationale}`);
    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "secondaryButton smallButton";
    selectButton.textContent = "編集";
    selectButton.addEventListener("click", () => selectNode(node));
    item.appendChild(selectButton);
    architectureMap.appendChild(item);
  }
  for (const edge of architecture.spec.edges) {
    const item = document.createElement("article");
    item.className = "edge";
    appendText(item, "strong", edge.id);
    appendText(item, "span", `${edge.from_node} -> ${edge.to_node}`);
    appendText(item, "span", `種別: ${edge.type}`);
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
  renderAddonResult("複数回セキュリティ評価", result);
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
  renderAddonResult("画像要件メモ", result);
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
    "影響レビュー",
    impactLines(preview),
    "閉じる",
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
  const accepted = await confirmAction("影響確認後にドラフト保存", impactLines(preview), "ドラフト保存");
  if (!accepted) {
    return;
  }
  await api(`/api/projects/${projectId}/architecture/update-node`, {
    method: "POST",
    body: JSON.stringify({
      ...nodePatchPayload(),
      change_reason: "デモUIからCloud Runパラメータを調整",
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
    "ノード削除",
    [
      `ノード: ${nodeId}`,
      node ? `${node.name} と接続中のすべてのエッジをドラフト構成から削除します。` : "対象ノードが存在する場合、そのノードを削除します。",
      "破壊的な構成編集のため、次にもう一度確認します。",
    ],
    "続行",
  );
  if (!firstConfirm) {
    return;
  }
  const secondConfirm = await confirmAction(
    "ノード削除の最終確認",
    [
      "2回目の確認です。",
      "この操作は新しい構成ドラフトを作成します。構成を承認してApplyするまでクラウド変更は反映されません。",
    ],
    "ノード削除",
  );
  if (!secondConfirm) {
    return;
  }
  await api(`/api/projects/${projectId}/architecture/delete-node`, {
    method: "POST",
    body: JSON.stringify({
      node_id: nodeId,
      confirmed: true,
      change_reason: "デモUIから2段階確認後にノードを削除",
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
    "チャット再提案を作成しました",
    [
      `ドラフトバージョン: ${result.version}`,
      `変更内容: ${JSON.stringify(result.changes)}`,
      "Apply前に構成を再確認し、承認してください。",
    ],
    "閉じる",
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
      change_reason: "構成パレットからノードを追加",
    }),
  });
  await confirmAction(
    "ノード追加ドラフトを作成しました",
    [
      `ドラフトバージョン: ${result.version}`,
      `ノード: ${result.node_id}`,
      "このリソース変更をApplyする前に構成を承認してください。",
    ],
    "閉じる",
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
      change_reason: "構成エディタから接続を追加",
    }),
  });
  await confirmAction(
    "接続追加ドラフトを作成しました",
    [
      `ドラフトバージョン: ${result.version}`,
      `接続: ${result.edge_id}`,
      "この関係は構成マップのドラフトに追加されました。",
    ],
    "閉じる",
  );
  await loadArchitecture();
}

async function deleteEdge() {
  const projectId = await requireProject();
  const edgeId = document.querySelector("#edgeId").value.trim();
  const confirmed = await confirmAction(
    "接続削除",
    [
      `接続: ${edgeId}`,
      "新しい構成ドラフトからこの関係を削除します。",
    ],
    "接続削除",
  );
  if (!confirmed) {
    return;
  }
  await api(`/api/projects/${projectId}/architecture/delete-edge`, {
    method: "POST",
    body: JSON.stringify({
      edge_id: edgeId,
      change_reason: "構成エディタから接続を削除",
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
    throw new Error("パラメータJSONはオブジェクトである必要があります");
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
  appendText(impactPanel, "strong", "影響説明");
  for (const line of impactLines(preview)) {
    appendText(impactPanel, "span", line);
  }
}

function impactLines(preview) {
  const impact = preview.impact || {};
  return [
    impact.summary || "要約は返されていません。",
    `コスト: ${impact.cost || "-"}`,
    `セキュリティ: ${impact.security || "-"}`,
    `性能: ${impact.performance || "-"}`,
    `再Applyが必要: ${preview.requires_reapply ? "はい" : "いいえ"}`,
    `追加確認が必要: ${preview.requires_confirmation ? "はい" : "いいえ"}`,
  ];
}

async function applyArchitecture() {
  const projectId = await requireProject();
  const approved = await confirmAction(
    "構成をApply",
    [
      "Apply実行中は編集UIがロックされます。",
      "デモモードではローカルCloud Buildアダプタを使い、デプロイ結果を運用ダッシュボードに記録します。",
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
  applyStatus.textContent = locked ? "編集ロック: Apply実行中" : "編集ロック: 開放中";
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
  renderAddonResult("Terraformプレビュー", result);
}

async function runGithubDemo() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/github/demo`, {
    method: "POST",
    body: JSON.stringify({
      repo_url: document.querySelector("#githubRepoUrl").value,
    }),
  });
  renderAddonResult("GitHubデモ", result);
}

async function loadSubmissionBrief() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/submission/brief`);
  renderReadinessResult("提出説明", result);
}

async function loadCloudRunEvidence() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/runtime/cloud-run`);
  renderReadinessResult("Cloud Run証跡", result);
}

async function loadAdapterInventory() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/adapters`);
  renderReadinessResult("アダプタ一覧", result);
}

async function runFailureDemo() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/apply/failure-demo`, {
    method: "POST",
    body: JSON.stringify({
      error_text: document.querySelector("#failureText").value,
    }),
  });
  renderReadinessResult("障害復旧デモ", result);
}

async function loadFailureGuidance() {
  const projectId = await requireProject();
  const result = await api(`/api/projects/${projectId}/apply/failure-guidance`, {
    method: "POST",
    body: JSON.stringify({
      error_text: document.querySelector("#failureText").value,
    }),
  });
  renderAddonResult("Apply失敗時ガイド", result);
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

function renderReadinessBundle(readiness) {
  readinessPanel.classList.remove("empty");
  readinessPanel.replaceChildren();
  const titles = {
    submission_brief: "提出説明",
    cloud_run_evidence: "Cloud Run証跡",
    adapter_inventory: "アダプタ一覧",
    failure_recovery_demo: "障害復旧デモ",
  };
  for (const [key, title] of Object.entries(titles)) {
    if (readiness[key]) {
      readinessPanel.appendChild(renderDocument(title, JSON.stringify(readiness[key], null, 2)));
    }
  }
}

async function loadDocuments() {
  const projectId = await requireProject();
  const documents = await api(`/api/projects/${projectId}/documents`);
  renderDocuments(documents);
}

function renderDocuments(documents) {
  designDocs.classList.remove("empty");
  designDocs.replaceChildren();
  if (!documents.length) {
    designDocs.classList.add("empty");
    designDocs.textContent = "まだ設計書は生成されていません。";
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
  renderTargetApp(appPackage);
}

function renderTargetApp(appPackage) {
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
    "AIコードレビュー",
    review.findings.map((finding) => `${finding.severity}: ${finding.message} ${finding.suggestion}`),
    "閉じる",
  );
}

async function loadOps() {
  const projectId = await requireProject();
  const ops = await api(`/api/projects/${projectId}/ops`);
  renderOps(ops);
}

function renderOps(ops) {
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
    appendText(item, "strong", opsLabel(key));
    appendText(item, "span", summary(ops[key]));
    item.appendChild(renderMiniJson(ops[key]));
    opsDashboard.appendChild(item);
  }
}

async function loadTimeline() {
  const projectId = await requireProject();
  const events = await api(`/api/projects/${projectId}/timeline`);
  renderTimeline(events);
}

function renderTimeline(events) {
  timelinePanel.classList.remove("empty");
  timelinePanel.replaceChildren();
  if (!events.length) {
    timelinePanel.classList.add("empty");
    timelinePanel.textContent = "まだイベントは記録されていません。";
    return;
  }
  for (const event of events) {
    const details = document.createElement("details");
    details.className = "timelineItem";
    const summaryElement = document.createElement("summary");
    summaryElement.textContent = `${event.result.toUpperCase()} - ${event.action}`;
    details.appendChild(summaryElement);
    appendText(details, "span", `エージェント: ${event.agent_name || "-"}`);
    appendText(details, "span", `時刻: ${event.occurred_at}`);
    appendText(details, "span", `理由: ${event.rationale_md || "理由は記録されていません。"}`);
    appendText(details, "span", `判断: ${event.metadata?.decision || "-"}`);
    appendText(details, "span", `ツール境界: ${event.metadata?.tool_boundary || "-"}`);
    appendText(details, "span", `アダプタ: ${event.metadata?.adapter_mode || "-"}`);
    appendText(details, "span", `次の想定アクション: ${event.metadata?.next_expected_action || "-"}`);
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

function opsLabel(key) {
  return {
    system_overview: "システム概要",
    architecture_map: "構成マップ",
    deployment_status: "デプロイ状況",
    logs_errors: "ログ・エラー",
    cost_overview: "コスト概要",
    security_overview: "セキュリティ概要",
    agent_actions: "エージェント操作",
    recommended_next_actions: "推奨次アクション",
  }[key] || titleize(key);
}

function gateLabel(gate) {
  return {
    requirements: "要件",
    design: "設計",
    architecture: "構成",
  }[gate] || gate;
}

function summary(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return `${value.length} 件`;
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
    serverStatus.textContent = "サーバ準備完了";
    await restoreWorkspace();
  } catch (error) {
    serverStatus.textContent = "サーバに接続できません";
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
    renderError(error);
  } finally {
    if (!state.applyInProgress) {
      buttons.forEach((button) => {
        button.disabled = false;
      });
    }
  }
}

function renderError(error) {
  const apiError = error.apiError || {};
  const details = apiError.details || {};
  const guidance = [];
  if (apiError.code === "PHASE_CONFLICT") {
    guidance.push("パイプラインを順番に実行するか、デモ一括実行で完全なワークスペースを再作成してください。");
    if (details.current_phase && details.requested_phase) {
      guidance.push(`現在フェーズ: ${details.current_phase}; 要求フェーズ: ${details.requested_phase}.`);
    }
  }
  if (apiError.code === "NOT_FOUND") {
    guidance.push("サーバ状態がリセットされた可能性があります。デモ一括実行で審査用ワークスペースを再作成してください。");
  }
  serverStatus.textContent = guidance[0] || "操作に失敗しました";
  output.textContent = JSON.stringify(
    {
      error: {
        message: error.message,
        code: apiError.code || "CLIENT_ERROR",
        details,
        guidance,
      },
    },
    null,
    2,
  );
}

checkHealth();
