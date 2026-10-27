// 갤러리 화면 — 결과 카드 그리드(썸네일 자동 생성) + 상세 3D 뷰어(회전·확대·부위 보기) + 텍스처 확대 보기
import { createViewer, PART_COLORS } from "/viewer.js";

const MODEL_LABEL = {
  "hunyuan3d-2.1": "Hunyuan3D 2.1 · 텍스처 메시",
  triposplat: "TripoSplat · Gaussian splat",
  partllm: "PartLLM · 부위 분할",
  "worldmirror-2.0": "WorldMirror 2.0 · 장면 복원",
};
const $ = (s) => document.querySelector(s);
const fmtSize = (b) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`);
const fmtTime = (t) => new Date(t * 1000).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
const dataUrl = (job, f) => `/data/${encodeURIComponent(job)}/${encodeURIComponent(f)}`;

let all = [], shown = [], filter = "all", cur = -1, viewer = null, curFile = null;

async function init() {
  all = await (await fetch("/api/items")).json();
  const models = [...new Set(all.map((i) => i.model))];
  $("#summary").textContent = `결과 ${all.length}건 · 모델 ${models.length}종`;
  const chips = ["all", ...models].map((m) => {
    const b = document.createElement("button");
    b.textContent = m === "all" ? "전체" : MODEL_LABEL[m]?.split(" · ")[0] || m;
    b.setAttribute("aria-pressed", String(m === filter));
    b.onclick = () => { filter = m; chips.forEach((c) => c.setAttribute("aria-pressed", String(c === b))); render(); };
    return b;
  });
  $("#filters").replaceChildren(...chips);
  render();
  makeThumbs();
}

function render() {
  shown = all.filter((i) => filter === "all" || i.model === filter);
  $("#empty").hidden = shown.length > 0;
  $("#grid").replaceChildren(...shown.map((it, idx) => {
    const li = document.createElement("li");
    li.className = "card";
    const parts = it.parts.length ? `<span class="badge">부위 ${it.parts.length}</span>` : "";
    li.innerHTML = `<button aria-label="${MODEL_LABEL[it.model] || it.model} ${it.id} 3D로 보기">
      <div class="thumb" data-job="${it.job}">${it.thumb ? `<img alt="" loading="lazy" src="${dataUrl(it.job, ".thumb.png")}?v=${it.mtime}">` : "썸네일 만드는 중…"}</div>
      <div class="info"><div class="model">${MODEL_LABEL[it.model] || it.model}</div>
      <div class="desc">${parts}<span class="badge">${it.files.length + it.parts.length} 파일</span>${fmtTime(it.mtime)}</div></div></button>`;
    li.querySelector("button").onclick = () => open(idx);
    return li;
  }));
}

// 썸네일이 없는 결과는 화면 밖 캔버스로 한 장씩 렌더해 서버에 저장한다
async function makeThumbs() {
  const todo = all.filter((i) => !i.thumb && i.primary);
  if (!todo.length) return;
  const canvas = document.createElement("canvas");
  canvas.width = 640; canvas.height = 480;
  canvas.style.cssText = "position:fixed;left:-9999px;top:0;width:640px;height:480px";
  document.body.append(canvas);
  const v = createViewer(canvas, { thumbnail: true });
  for (const it of todo) {
    try {
      const kind = it.files.find((f) => f.file === it.primary)?.kind || "mesh";
      await v.load(dataUrl(it.job, it.primary), kind);
      // 스플랫은 정렬이 몇 프레임 걸린다
      for (let k = 0; k < 30; k++) { v.renderOnce(); await new Promise(requestAnimationFrame); }
      const blob = await new Promise((r) => canvas.toBlob(r, "image/png"));
      await fetch(`/api/thumb/${encodeURIComponent(it.job)}`, { method: "POST", body: blob });
      it.thumb = true;
      const box = document.querySelector(`.thumb[data-job="${it.job}"]`);
      if (box) box.innerHTML = `<img alt="" src="${URL.createObjectURL(blob)}">`;
    } catch (e) {
      console.warn("thumb failed", it.job, e);
      const box = document.querySelector(`.thumb[data-job="${it.job}"]`);
      if (box) box.textContent = "미리보기를 만들 수 없음";
    }
  }
  v.dispose(); canvas.remove();
}

function open(idx) {
  cur = idx;
  const it = shown[idx];
  const dlg = $("#detail");
  if (!dlg.open) dlg.showModal();
  if (!viewer) { viewer = createViewer($("#view")); viewer.setAutoRotate(true); viewer.start(); }
  $("#d-title").textContent = MODEL_LABEL[it.model] || it.model;
  $("#d-meta").textContent = `잡 ${it.id} · ${fmtTime(it.mtime)}`;

  $("#d-files").replaceChildren(...it.files.map((f) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.innerHTML = `${f.file}<small>${f.kind === "splat" ? "Gaussian splat" : "메시"} · ${fmtSize(f.size)}</small>`;
    b.onclick = () => show(it, f);
    b.dataset.file = f.file;
    li.append(b);
    return li;
  }));

  $("#d-parts-sec").hidden = !it.parts.length;
  // 이전 결과에서 켠 부위 보기를 끄고 원본 메시를 다시 보이게
  if ($("#d-parts-on").checked) { $("#d-parts-on").checked = false; viewer.showMesh(true); viewer.loadParts([]); }
  $("#d-parts").replaceChildren(...it.parts.map((p, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<label><input type="checkbox" checked data-file="${p.file}"><span class="swatch" style="background:${PART_COLORS[i % PART_COLORS.length]}"></span>${p.label}</label>`;
    li.querySelector("input").onchange = (e) => viewer.setPartVisible(p.file, e.target.checked);
    return li;
  }));

  $("#d-images-sec").hidden = !it.images.length;
  $("#d-images").replaceChildren(...it.images.map((f) => {
    const li = document.createElement("li");
    li.innerHTML = `<button aria-label="${f} 확대 보기"><img alt="${f}" loading="lazy" src="${dataUrl(it.job, f)}"></button>`;
    li.querySelector("button").onclick = () => lightbox(dataUrl(it.job, f), f);
    return li;
  }));

  show(it, it.files.find((f) => f.file === it.primary) || it.files[0]);
}

async function show(it, f) {
  curFile = f.file;
  document.querySelectorAll("#d-files button").forEach((b) => b.setAttribute("aria-current", String(b.dataset.file === f.file)));
  $("#loading").hidden = false;
  $("#loading").textContent = `불러오는 중… (${fmtSize(f.size)})`;
  try {
    await viewer.load(dataUrl(it.job, f.file), f.kind);
    if (curFile !== f.file) return;
    $("#loading").hidden = true;
    if ($("#d-parts-on").checked) togglePartsView(true);
  } catch (e) {
    $("#loading").textContent = `불러오지 못했습니다: ${e.message || e}`;
  }
  $("#view").focus();
}

// 부위 보기 — 원본 메시를 숨기고 부위 점군을 색으로 겹친다
async function togglePartsView(on) {
  const it = shown[cur];
  if (on) {
    $("#loading").hidden = false; $("#loading").textContent = "부위 불러오는 중…";
    await viewer.loadParts(it.parts.map((p) => ({ ...p, url: dataUrl(it.job, p.file) })));
    document.querySelectorAll("#d-parts input").forEach((c) => viewer.setPartVisible(c.dataset.file, c.checked));
    $("#loading").hidden = true;
  }
  viewer.showMesh(!on);
  if (!on) viewer.loadParts([]);
}
$("#d-parts-on").onchange = (e) => togglePartsView(e.target.checked);

let dark = matchMedia("(prefers-color-scheme: dark)").matches;
const actions = {
  "zoom-in": () => viewer.zoom(0.8),
  "zoom-out": () => viewer.zoom(1.25),
  rotate: (b) => { const on = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", String(on)); viewer.setAutoRotate(on); },
  reset: () => viewer.reset(),
  wire: (b) => { const on = b.getAttribute("aria-pressed") !== "true"; b.setAttribute("aria-pressed", String(on)); viewer.setWire(on); },
  bg: () => { dark = !dark; viewer.setBackground(dark ? "#101014" : "#f2f2f4"); },
  full: () => (document.fullscreenElement ? document.exitFullscreen() : $("#detail").requestFullscreen()),
  close: () => $("#detail").close(),
  prev: () => open((cur - 1 + shown.length) % shown.length),
  next: () => open((cur + 1) % shown.length),
};
document.querySelectorAll("#detail [data-act]").forEach((b) => { b.onclick = () => actions[b.dataset.act](b); });
$("#detail").addEventListener("keydown", (e) => {
  if (e.target.matches("input")) return;
  const btn = (a) => document.querySelector(`#detail [data-act="${a}"]`);
  const map = { "+": "zoom-in", "=": "zoom-in", "-": "zoom-out", r: "reset", w: "wire", b: "bg", f: "full", " ": "rotate",
    ArrowLeft: "prev", ArrowRight: "next" };
  const a = map[e.key];
  if (a) { e.preventDefault(); actions[a](btn(a)); }
});

// 텍스처 이미지 확대 보기 — 휠/핀치 확대, 드래그 이동, 더블클릭 원래 크기
function lightbox(src, alt) {
  const dlg = $("#lightbox"), img = $("#lb-img");
  let s = 1, x = 0, y = 0;
  const apply = () => { img.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px)) scale(${s})`; };
  img.src = src; img.alt = alt; apply();
  dlg.showModal();
  dlg.onwheel = (e) => { e.preventDefault(); s = Math.min(12, Math.max(0.5, s * (e.deltaY < 0 ? 1.15 : 1 / 1.15))); apply(); };
  img.ondblclick = () => { s = 1; x = y = 0; apply(); };
  const pts = new Map();
  let pinch = 0;
  img.onpointerdown = (e) => { img.setPointerCapture(e.pointerId); pts.set(e.pointerId, [e.clientX, e.clientY]); };
  img.onpointermove = (e) => {
    if (!pts.has(e.pointerId)) return;
    const [px, py] = pts.get(e.pointerId);
    pts.set(e.pointerId, [e.clientX, e.clientY]);
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (pinch) s = Math.min(12, Math.max(0.5, s * (d / pinch)));
      pinch = d;
    } else { x += e.clientX - px; y += e.clientY - py; }
    apply();
  };
  img.onpointerup = img.onpointercancel = (e) => { pts.delete(e.pointerId); pinch = 0; };
  dlg.onclick = (e) => { if (e.target === dlg) dlg.close(); };
}

init();
