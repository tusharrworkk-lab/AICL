(() => {
  const $ = (id) => document.getElementById(id);
  const state = { project: null, projects: [], events: [], failures: [], evaluations: [], strategies: [], negativeCases: [] };
  const key = () => $("api-key").value.trim();
  const base = () => $("base-url").value.trim().replace(/\/$/, "");
  const headers = () => ({ "Content-Type": "application/json", Authorization: `Bearer ${key()}` });
  const escape = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" })[c]);
  const uuid = () => crypto.randomUUID();

  $("base-url").value = localStorage.getItem("acil.baseUrl") || window.location.origin;
  $("api-key").value = localStorage.getItem("acil.apiKey") || "";

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
    const activeStrategies = state.strategies.filter(s => ["ACTIVE", "VALIDATED"].includes(s.status)).length;
    $("metric-events").textContent = state.events.length;
    $("metric-failures").textContent = state.failures.length;
    $("metric-strategies").textContent = activeStrategies;
    $("metric-evaluations").textContent = state.evaluations.length;
    $("logs").innerHTML = state.events.length ? state.events.map(e => `<div class="log"><time>${new Date(e.timestamp).toLocaleTimeString([], {hour:"2-digit",minute:"2-digit",second:"2-digit"})}</time><span class="tag">${escape(e.agent_type)}</span><span>${escape(e.canonical_action)} <small>${escape(e.native_tool_name || "")}</small></span><span class="badge ${statusClass(e.status)}">${escape(e.status)}</span></div>`).join("") : `<div class="empty">No observed events for this project.</div>`;
    $("failures").innerHTML = state.failures.length ? state.failures.map(f => `<div class="card failure"><div class="card-title"><span>${escape(f.error_type)}</span><span class="badge failed">× ${f.occurrence_count}</span></div><p>${escape(f.canonical_action)} · ${escape(f.native_tool_name || "unknown tool")}</p><p>fingerprint ${escape(f.fingerprint.slice(0, 16))}…</p></div>`).join("") : `<div class="empty">No failure patterns. Evidence will appear here after a failed event.</div>`;
    $("strategies").innerHTML = state.strategies.length ? state.strategies.map(s => {
      const evaluation = state.evaluations.find(e => e.failure_pattern_id === s.failure_pattern_id);
      const validate = s.status === "CANDIDATE" && evaluation ? `<button class="secondary validate" data-evaluation="${evaluation.id}">Run controlled validation</button>` : "";
      const activate = s.status === "VALIDATED" ? `<button class="primary activate" data-strategy="${s.id}">Activate strategy</button>` : "";
      return `<div class="card strategy"><div class="card-title"><span>${escape(s.name)}</span><span class="badge ${statusClass(s.status)}">${escape(s.status)}</span></div><div class="actions">${s.actions.map(escape).join(" → ")}</div>${validate}${activate}</div>`;
    }).join("") : `<div class="empty">A failed trace creates a candidate strategy. Validation evidence is required before activation.</div>`;
    document.querySelectorAll(".activate").forEach(el => el.onclick = () => activate(el.dataset.strategy));
    document.querySelectorAll(".validate").forEach(el => el.onclick = () => validate(el.dataset.evaluation));
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
    target.innerHTML = state.negativeCases.flatMap(run => (run.analysis || []).map(item => {
      const facts = (item.observed_facts || []).map(escape).join(" · ") || "No observed facts returned";
      const actions = (item.recommended_next_actions || []).map(escape).join(" → ") || "No next action returned";
      return `<div class="card failure"><div class="card-title"><span>${escape(item.failure_case)}</span><span class="badge failed">confidence ${escape(item.confidence)}%</span></div><p><strong>Likely cause:</strong> ${escape(item.likely_cause)}</p><p><strong>Observed:</strong> ${facts}</p><p><strong>Impact:</strong> ${escape(item.impact)}</p><p><strong>Next:</strong> ${actions}</p></div>`;
    })).join("");
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
    $("inject-demo").disabled = $("compile-context").disabled = false;
    renderProjects();
    try { await loadProjectData(); } catch (err) { notice(err.message, true); }
  }
  async function connect() {
    try {
      await fetch(`${base()}/health`).then(r => { if (!r.ok) throw new Error("Health check failed"); return r.json(); });
      const [projects, judge, negativeCases] = await Promise.all([request("/v1/projects"), request("/v1/judge/status"), request("/v1/negative-cases")]);
      state.projects = projects;
      state.negativeCases = negativeCases;
      renderJudge(judge);
      renderNegativeCases();
      localStorage.setItem("acil.baseUrl", base()); localStorage.setItem("acil.apiKey", key());
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
  async function injectDemo() {
    if (!state.project) return;
    const session = uuid(), now = new Date().toISOString(), trace = `console-demo-${Date.now()}`;
    const common = {project_id:state.project.id, session_id:session, trace_id:trace, agent_type:"test_agent", native_tool_name:"shell", timestamp:now, duration_ms:24, attributes:{environment_fingerprint:"python-3.12", tool_capabilities:["shell","filesystem"], source:"acil-console-demo"}};
    try {
      await request("/v1/events/batch", {method:"POST", body:JSON.stringify({events:[
        {...common,event_id:uuid(),span_id:"read",event_type:"tool.completed",canonical_action:"READ_RESOURCE",status:"ok",error_type:null},
        {...common,event_id:uuid(),span_id:"tests",parent_span_id:"read",event_type:"tool.failed",canonical_action:"RUN_TESTS",status:"failed",error_type:"missing_dependency",duration_ms:410}
      ]})});
      notice("Controlled demo inserted: RUN_TESTS failed with missing_dependency. ACIL created a failure pattern, evaluation, and candidate recovery strategy. This is simulated evidence, not a real agent run."); await loadProjectData();
    } catch(err) { notice(`Demo injection failed: ${err.message}`, true); }
  }
  async function activate(id) {
    try { await request(`/v1/strategies/${id}/activate`, {method:"POST"}); notice("Strategy activated. It is now eligible for context compilation."); await loadProjectData(); }
    catch(err) { notice(`Activation blocked: ${err.message}. Run the linked evaluation successfully first.`, true); }
  }
  async function validate(id) {
    try {
      await request(`/v1/evaluations/${id}/run`, {method:"POST", body:JSON.stringify({observed_actions:["CHECK_DEPENDENCIES","PREPARE_ENVIRONMENT","RUN_TESTS"],outcome:"success",evidence:{source:"acil-console-controlled-demo",simulated:true}})});
      notice("Controlled evaluation passed. The strategy is now VALIDATED; activate it to make it retrievable. This is simulated validation evidence."); await loadProjectData();
    } catch(err) { notice(`Validation failed: ${err.message}`, true); }
  }
  async function compile() {
    if (!state.project) return;
    try { const pkg = await request("/v1/context/compile", {method:"POST", body:JSON.stringify({project_id:state.project.id,task_type:"fix_tests",agent_type:"test_agent",failure_type:"missing_dependency",canonical_action:"RUN_TESTS",environment_fingerprint:"python-3.12",render_markdown:true})}); $("context-output").textContent = pkg.markdown || JSON.stringify(pkg,null,2); notice(`Context package compiled with ${pkg.recommended_strategies.length} recommended strategy(s).`); }
    catch(err) { notice(`Context compilation failed: ${err.message}`, true); }
  }
  $("connect").onclick = connect; $("refresh").onclick = () => state.project ? loadProjectData() : connect();
  $("new-project").onclick = () => $("project-dialog").showModal(); $("project-form").onsubmit = (e) => {e.preventDefault(); createProject();};
  $("inject-demo").onclick = injectDemo; $("compile-context").onclick = compile;
})();
