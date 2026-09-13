"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => (t.className = "toast"), 2600);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json()).detail || ""; } catch (e) {}
    throw new Error(detail || ("HTTP " + res.status));
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res;
}

// ---------------- 标签页 ----------------
$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    ["sources", "search", "output", "local"].forEach((t) => {
      $("#tab-" + t).style.display = t === tab ? "" : "none";
    });
    if (tab === "sources") loadSources();
    if (tab === "output") loadFiles();
  });
});

// ---------------- 书源管理 ----------------
async function loadSources() {
  const box = $("#sourceList");
  try {
    const data = await api("/api/sources");
    if (!data.sources.length) {
      box.innerHTML = '<div class="empty">暂无书源（内置源需在代码中注册，用户源可在此批量添加）</div>';
      return;
    }
    box.innerHTML = "";
    data.sources.forEach((s) => {
      const el = document.createElement("div");
      el.className = "item";
      const badges =
        (s.user ? '<span class="badge user">用户</span>' : '<span class="badge">内置</span>') +
        (s.public ? '<span class="badge pub">公版</span>' : '<span class="badge nonpub">非公版</span>');
      el.innerHTML =
        '<div class="meta"><div class="title">' +
        esc(s.display_name || s.name) + " " + badges +
        '</div><div class="sub">' + esc(s.name) + " · " + esc((s.domains || []).join(", ")) + "</div></div>";
      const acts = document.createElement("div");
      acts.className = "acts";
      if (s.user) {
        const del = document.createElement("button");
        del.className = "danger";
        del.textContent = "删除";
        del.onclick = () => delSource(s.name);
        acts.appendChild(del);
      } else {
        const tip = document.createElement("span");
        tip.className = "muted";
        tip.textContent = "内置";
        acts.appendChild(tip);
      }
      el.appendChild(acts);
      box.appendChild(el);
    });
  } catch (e) {
    box.innerHTML = '<div class="empty">加载失败：' + esc(e.message) + "</div>";
  }
}

async function delSource(name) {
  if (!confirm("确定删除书源 " + name + "？")) return;
  try {
    await api("/api/sources/" + encodeURIComponent(name), { method: "DELETE" });
    toast("已删除 " + name);
    loadSources();
  } catch (e) {
    toast("删除失败：" + e.message, true);
  }
}

$("#addRuleBtn").addEventListener("click", async () => {
  const text = $("#ruleText").value.trim();
  if (!text) { toast("请先粘贴书源 JSON", true); return; }
  const btn = $("#addRuleBtn"); btn.disabled = true;
  try {
    const data = await api("/api/sources", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: text,
    });
    showAddResult(data);
    $("#ruleText").value = "";
    loadSources();
  } catch (e) {
    $("#addResult").textContent = "失败：" + e.message;
    toast("添加失败：" + e.message, true);
  } finally { btn.disabled = false; }
});

$("#uploadRuleBtn").addEventListener("click", async () => {
  const f = $("#ruleFile").files[0];
  if (!f) { toast("请先选择文件", true); return; }
  const fd = new FormData();
  fd.append("file", f);
  try {
    const data = await api("/api/sources/upload", { method: "POST", body: fd });
    showAddResult(data);
    loadSources();
  } catch (e) {
    toast("上传失败：" + e.message, true);
  }
});

function showAddResult(data) {
  const ok = (data.added || []).length ? "已添加：" + data.added.join(", ") : "";
  const err = (data.errors || []).length
    ? "；失败：" + data.errors.map((e) => e.name + "(" + e.error + ")").join("；")
    : "";
  $("#addResult").textContent = ok + err;
  if (data.errors && data.errors.length) toast("部分书源添加失败", true);
  else if (ok) toast("添加成功");
}

// ---------------- 搜索 ----------------
$("#searchBtn").addEventListener("click", doSearch);
$("#searchTitle").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

async function doSearch() {
  const title = $("#searchTitle").value.trim();
  if (!title) { toast("请输入书名", true); return; }
  const btn = $("#searchBtn"); btn.disabled = true;
  $("#searchStatus").textContent = "搜索中…";
  const box = $("#searchResults");
  box.innerHTML = '<div class="empty">搜索中…</div>';
  try {
    const data = await api("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    $("#searchStatus").textContent = "共找到 " + data.count + " 条结果";
    if (!data.results.length) { box.innerHTML = '<div class="empty">无结果，可尝试换书名或添加对应书源</div>'; return; }
    box.innerHTML = "";
    data.results.forEach((r) => box.appendChild(renderResult(r)));
  } catch (e) {
    $("#searchStatus").textContent = "搜索失败";
    box.innerHTML = '<div class="empty">失败：' + esc(e.message) + "</div>";
  } finally { btn.disabled = false; }
}

function renderResult(r) {
  const el = document.createElement("div");
  el.className = "result";
  const title = r.title || r.url || "(无名)";
  const author = r.author ? "作者：" + r.author : "";
  const src = r.source_name || r._source || "";
  el.innerHTML =
    '<div class="rt">' + esc(title) + '</div>' +
    '<div class="ra">' + esc(author) + (src ? " · 来源：" + esc(src) : "") + "</div>";
  const acts = document.createElement("div");
  acts.className = "acts";
  const prev = document.createElement("button");
  prev.textContent = "预览";
  prev.onclick = () => previewBook(r);
  const dl = document.createElement("button");
  dl.className = "primary";
  dl.textContent = "下载并转 EPUB";
  dl.onclick = () => downloadBook(r, dl);
  acts.appendChild(prev);
  acts.appendChild(dl);
  const st = document.createElement("span");
  st.className = "status";
  st.textContent = "";
  acts.appendChild(st);
  el.appendChild(acts);
  return el;
}

async function previewBook(r) {
  try {
    const data = await api("/api/preview?source=" + encodeURIComponent(r._source) + "&url=" + encodeURIComponent(r.url));
    $("#modalTitle").textContent = "预览：" + (r.title || r.url);
    const toc = (data.toc || []).map((t) => "<li>" + esc(t) + "</li>").join("");
    $("#modalToc").innerHTML = toc || '<li class="empty">（无目录信息）</li>';
    $("#modalSample").textContent = (data.sample || "").slice(0, 4000) || "（无样本）";
    $("#modal").classList.add("show");
  } catch (e) {
    toast("预览失败：" + e.message, true);
  }
}
$("#modalClose").addEventListener("click", () => $("#modal").classList.remove("show"));
$("#modal").addEventListener("click", (e) => { if (e.target === $("#modal")) $("#modal").classList.remove("show"); });

async function downloadBook(r, btn) {
  const st = btn.parentElement.querySelector(".status");
  btn.disabled = true;
  st.className = "status";
  st.textContent = "已提交，下载中…";
  try {
    const data = await api("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(r),
    });
    pollTask(data.task_id, st, btn);
  } catch (e) {
    st.className = "status failed";
    st.textContent = "提交失败：" + e.message;
    btn.disabled = false;
  }
}

async function pollTask(tid, st, btn) {
  for (let i = 0; i < 600; i++) {
    try {
      const t = await api("/api/tasks/" + tid);
      if (t.status === "done") {
        st.className = "status done";
        st.innerHTML = '完成 · <a href="' + t.result + '">下载 EPUB</a>';
        btn.disabled = false;
        toast("转换完成：" + (t.name || ""));
        return;
      }
      if (t.status === "failed") {
        st.className = "status failed";
        st.textContent = "失败：" + t.error;
        btn.disabled = false;
        toast("转换失败：" + t.error, true);
        return;
      }
      st.textContent = "下载/转换中…（" + (i + 1) + "s）";
    } catch (e) {}
    await new Promise((r) => setTimeout(r, 1000));
  }
  st.className = "status failed";
  st.textContent = "超时未响应";
  btn.disabled = false;
}

// ---------------- 文件列表 ----------------
async function loadFiles() {
  try {
    const data = await api("/api/files");
    const out = $("#outputList");
    if (!data.output.length) out.innerHTML = '<div class="empty">导出目录为空</div>';
    else {
      out.innerHTML = "";
      data.output.forEach((n) => {
        const el = document.createElement("div");
        el.className = "item";
        el.innerHTML =
          '<div class="meta"><div class="title">' + esc(n) + '</div></div>' +
          '<div class="acts"><a class="primary" style="padding:8px 14px;border:1px solid var(--accent);border-radius:8px;" href="/download/' +
          encodeURIComponent(n) + '">下载</a></div>';
        out.appendChild(el);
      });
    }
    const inp = $("#inputList");
    inp.innerHTML = data.input.length
      ? data.input.map((n) => '<div class="item"><div class="meta"><div class="title">' + esc(n) + "</div></div></div>").join("")
      : '<div class="empty">输入目录为空</div>';
  } catch (e) {
    $("#outputList").innerHTML = '<div class="empty">加载失败：' + esc(e.message) + "</div>";
  }
}

// ---------------- 本地转换 ----------------
$("#localBtn").addEventListener("click", async () => {
  const f = $("#localFile").files[0];
  if (!f) { toast("请选择 txt 文件", true); return; }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("traditionalize", $("#localTrad").checked ? "true" : "false");
  const btn = $("#localBtn"); btn.disabled = true;
  $("#localStatus").textContent = "转换中…";
  try {
    const res = await fetch("/convert", { method: "POST", body: fd });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = (res.headers.get("content-disposition") || "").match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)/i)?.[1] || (f.name.replace(/\.txt$/i, "") + ".epub");
    a.click();
    URL.revokeObjectURL(a.href);
    $("#localStatus").textContent = "已完成，已开始下载";
    toast("转换完成");
    loadFiles();
  } catch (e) {
    $("#localStatus").textContent = "失败：" + e.message;
    toast("转换失败：" + e.message, true);
  } finally { btn.disabled = false; }
});

// ---------------- 工具 ----------------
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------- 初始化 ----------------
loadSources();
