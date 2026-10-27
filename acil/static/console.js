(() => {
  const $ = (id) => document.getElementById(id);
  const state = { project: null, projects: [], events: [], failures: [], evaluations: [], strategies: [], negativeCases: [] };
  const key = () => $("api-key").value.trim();
  const base = () => $("base-url").value.trim().replace(/\/$/, "");
  const headers = () => ({ "Content-Type": "application/json", Authorization: `Bearer ${key()}` });
  const escape = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[c]);
  $("base-url").value = localStorage.getItem("acil.baseUrl") || window.location.origin;
  localStorage.removeItem("acil.apiKey");
  $("api-key").value = sessionStorage.getItem("acil.apiKey") || "";

  async function request(path, options = {}) {
    const response = await fetch(`${base()}${path}`, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `${response.status} ${response.statusText}`);
    return body;
  }
  function notice(message, error = false) {
    const el = $("notice"); el.textContent = message; el.classList.remove("hidden");
    el.style.borderColor = error ? "var(--red)" : "var(--amber)";
    el.style.color = error ? "#ffafaf" : "#fbd37a";
  }
  function connected(value) {
    $("connection-dot").className = `dot ${value ? "online" : "offline"}`;
    $("connection-label").textContent = value ? "API connected" : "not connected";
  }
  function statusClass(status) { return String(status || "").toLowerCase().replace(/[^a-z]/g, "") || "candidate"; }
  function renderProjects() {
    $("projects").innerHTML = state.projects.length ? state.projects.map(p => `<button class="project ${state.project?.id === p.id ? "active" : ""}" data-project="${p.id}">${escape(p.name)}<span class="slug">${escape(p.slug)}</span></button>`).join("") : `<p class="empty">No projects in this tenant.</p>`;
    document.querySelectorAll("[data-project]").forEach(el => el.onclick = () => selectProject(el.dataset.project));
  }
  function render() {
    const failureById = new Map(state.failures.map(f => [f.id, f]));
    const safeStrategies = state.strategies.filter(s => {
      if (!["ACTIVE", "VALIDATED"].includes(s.status)) return false;
      const failure = failureById.get(s.failure_pattern_id);
      const testTemplate = JSON.stringify(s.actions) === JSON.stringify(["CHECK_DEPENDENCIES", "PREPARE_ENVIRONMENT", "RUN_TESTS"]);
      return !(testTemplate && failure?.canonical_action !== "RUN_TESTS");
    });
    const activeStrategies = safeStrategies.length;
    $("metric-events").textContent = state.events.length;
    $("metric-failures").textContent = state.failures.length;
    $("metric-strategies").textContent = activeStrategies;
    $("metric-evaluations").textContent = state.evaluations.length;
    $("logs").innerHTML = state.events.length ? state.events.map(e => `<div class="log"><time>${new Date(e.timestamp).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"})}</time><span class="tag">${escape(e.agent_type)}</span><span>${escape(e.canonical_action)} <small>${escape(e.native_tool_name || "")}</small></span><span class="badge ${statusClass(e.status)}">${escape(e.status)}</span></div>`).join("") : `<div class="empty">No observed events for this project.</div>`;
    $("failures").innerHTML = state.failures.length ? state.failures.map(f => `<div class="card failure"><div class="card-title"><span>${escape(f.error_type)}</span><span class="badge failed">× ${f.occurrence_count}</span></div><p>${escape(f.canonical_action)} · ${escape(f.native_tool_name || "unknown tool")}</p><p>fingerprint ${escape(f.fingerprint.slice(0, 16))}…</p></div>`).join("") : `<div class="empty">No failure patterns. Evidence will appear here after a failed event.</div>`;
    $("strategies").innerHTML = safeStrategies.length ? safeStrategies.map(s => {
      const activate = s.status === "VALIDATED" ? `<button class="primary activate" data-strategy="${s.id}">Activate strategy</button>` : "";
      const applicability = s.applicability || {};
      return `<div class="card strategy"><div class="card-title"><span>${escape(s.name)}</span><span class="badge ${statusClass(s.status)}">${escape(s.status)}</span></div><p>${escape(applicability.error_type || "general")} · ${escape(applicability.canonical_action || "any action")}</p><div class="actions">${s.actions.map(escape).join(" → ")}</div>${activate}</div>`;
    }).join("") : `<div class="empty">No validated strategy is currently safe to display for this project.</div>`;
    document.querySelectorAll(".activate").forEach(el => el.onclick = () => activate(el.dataset.strategy));
  }
  function renderJudge(status) {
    const ready = status.ready === true;
    $("judge-light").className = `status-light ${ready ? "" : "muted-light"}`;
    $("judge-state").textContent = ready ? "configured · live call not yet run" : "configuration incomplete";
    const value = (label, content) => `<div class="judge-cell"><span>${label}</span><strong>${escape(content)}</strong></div>`;
    $("judge-runtime").innerHTML = [
      value("PROVIDER", status.provider || "Amazon Bedrock"),
      value("AUTH MODE", status.auth_mode || "iam"),
      value("MODEL", status.model || "not configured"),
      value("AWS REGION", status.region || "not configured"),
      value("MAX OUTPUT TOKENS", status.max_output_tokens || "not configured"),
      value("CREDENTIAL SOURCE", status.credential_source || "default AWS chain"),
      value("LIVE VERIFICATION", status.live_verification === "not_run" ? "not run — no billable call" : status.live_verification),
      value("ISOLATED RUNNER", status.isolated_runner_enabled ? "enabled" : "disabled"),
      value("EVALUATION IMAGE", status.evaluation_image_configured ? "configured" : "not configured"),
    ].join("");
  }
  function renderNegativeCases() {
    const target = $("negative-cases");
    if (!state.negativeCases.length) {
      target.innerHTML = `<div class="empty">No tenant-private model findings yet. Run a Bedrock evaluation to generate bounded, evidence-backed negative-case analysis.</div>`;
      return;
    }
    target.innerHTML = state.negativeCases.flatMap(run => {
      const score = run.reliability_score == null ? "pending" : `reliability ${run.reliability_score}`;
      const runHeader = `<div class="judge-run"><div class="card-title"><span>${escape(run.judge_provider || "judge")} · ${escape(run.status)}</span><span class="badge ${statusClass(run.status)}">${escape(score)}</span></div><p>Run ${escape(run.run_id.slice(0, 12))}… · Blockers: ${escape((run.blockers || []).join(" · ") || "none")}</p></div>`;
      const findings = (run.analysis || []).map(item => {
      const facts = (item.observed_facts || []).map(escape).join(" · ") || "No observed facts returned";
      const actions = (item.recommended_next_actions || []).map(escape).join(" → ") || "No next action returned";
      return `<div class="card failure"><div class="card-title"><span>${escape(item.failure_case)}</span><span class="badge failed">confidence ${escape(item.confidence)}%</span></div><p><strong>Likely cause:</strong> ${escape(item.likely_cause)}</p><p><strong>Observed:</strong> ${facts}</p><p><strong>Impact:</strong> ${escape(item.impact)}</p><p><strong>Next:</strong> ${actions}</p></div>`;
      });
      return [runHeader, ...findings];
    }).join("");
  }
  async function loadJudgeData() {
    const [judge, negativeCases] = await Promise.all([request("/v1/judge/status"), request("/v1/judge/runs")]);
    state.negativeCases = negativeCases;
    renderJudge(judge);
    renderNegativeCases();
  }
  async function loadProjectData() {
    if (!state.project) return;
    const id = state.project.id;
    [state.events, state.failures, state.evaluations, state.strategies] = await Promise.all([
      request(`/v1/projects/${id}/events?limit=100`), request(`/v1/failures?project_id=${id}`), request(`/v1/evaluations?project_id=${id}`), request(`/v1/strategies?project_id=${id}`)
    ]);
    render();
  }
  async function selectProject(id) {
    state.project = state.projects.find(p => p.id === id);
    $("project-title").textContent = state.project.name;
    $("project-description").textContent = state.project.description || "No description — observe agent execution, validate recoveries, then compile safe context.";
    renderProjects();
    try { await loadProjectData(); } catch (err) { notice(err.message, true); }
  }
  async function connect() {
    try {
      await fetch(`${base()}/health`).then(r => { if (!r.ok) throw new Error("Health check failed"); return r.json(); });
      const [projects, judge, negativeCases] = await Promise.all([request("/v1/projects"), request("/v1/judge/status"), request("/v1/judge/runs")]);
      state.projects = projects;
      state.negativeCases = negativeCases;
      renderJudge(judge);
      renderNegativeCases();
      localStorage.setItem("acil.baseUrl", base()); sessionStorage.setItem("acil.apiKey", key());
      connected(true); $("notice").classList.add("hidden"); renderProjects();
      if (state.projects.length) await selectProject(state.projects[0].id);
      else notice("Connected. Create a project, then inject the controlled demo trace or send events from your test agent.");
    } catch (err) { connected(false); notice(`Connection failed: ${err.message}`, true); }
  }
  async function createProject() {
    const name = $("project-name").value.trim(), slug = $("project-slug").value.trim(), description = $("project-description-input").value.trim();
    if (!name || !slug) return;
    try { const project = await request("/v1/projects", {method:"POST", body:JSON.stringify({name, slug, description: description || null})}); state.projects.push(project); $("project-dialog").close(); await selectProject(project.id); }
    catch(err) { notice(`Could not create project: ${err.message}`, true); }
  }
  async function activate(id) {
    try { await request(`/v1/strategies/${id}/activate`, {method:"POST"}); notice("Strategy activated. It is now eligible for context compilation."); await loadProjectData(); }
    catch(err) { notice(`Activation blocked: ${err.message}. Run the linked evaluation successfully first.`, true); }
  }
  $("connect").onclick = connect; $("refresh").onclick = () => state.project ? loadProjectData() : connect();
  $("new-project").onclick = () => $("project-dialog").showModal(); $("project-form").onsubmit = (e) => {e.preventDefault(); createProject();};
  $("refresh-judge").onclick = async () => {
    try { await loadJudgeData(); notice("LLM judge runtime and findings refreshed."); }
    catch (err) { notice(`Judge refresh failed: ${err.message}`, true); }
  };
  document.querySelectorAll("[data-tab]").forEach((tab) => tab.onclick = () => {
    document.querySelectorAll("[data-tab]").forEach((item) => item.classList.toggle("active", item === tab));
    document.querySelectorAll("[data-tab-panel]").forEach((panel) => panel.classList.toggle("tab-hidden", panel.dataset.tabPanel !== tab.dataset.tab));
  });
  window.setInterval(() => {
    const activeTab = document.querySelector("[data-tab].active")?.dataset.tab;
    if (activeTab === "judge" && key()) loadJudgeData().catch(() => {});
  }, 3000);
})();
