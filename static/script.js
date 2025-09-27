// ===== 다크모드 / 발표모드 =====
const htmlEl = document.documentElement;
const bodyEl = document.body;
// 현재 테마에 맞춰 구성요소들 외관 동기화
function syncThemeForComponents() {
  const isDark = document.documentElement.getAttribute('data-bs-theme') === 'dark';

  // 테이블 헤더(필요 시 라이트/다크 헤더 클래스를 토글)
  const thead = document.getElementById('thead-main');
  if (thead) {
    thead.classList.toggle('table-dark', isDark);
    thead.classList.toggle('table-light', !isDark);
  }

  // body 배경은 항상 테마 연동 유지
  document.body.classList.remove('bg-light');
  document.body.classList.add('bg-body');
}
function applyDarkMode(on) {
  document.documentElement.setAttribute("data-bs-theme", on ? "dark" : "light");
  $("#btn-darkmode").textContent = on ? "☀️ 라이트모드" : "🌙 다크모드";
  localStorage.setItem("draw.dark", on ? "1" : "0");
  syncThemeForComponents();      // ✅ 테마 반영
}
function toggleDarkMode() {
  const cur = htmlEl.getAttribute("data-bs-theme") === "dark";
  applyDarkMode(!cur);
}

async function enterFullscreen() {
  if (document.fullscreenElement) return;
  try {
    await document.documentElement.requestFullscreen();
  } catch (_) { /* 무시 */ }
}

async function exitFullscreen() {
  if (!document.fullscreenElement) return;
  try {
    await document.exitFullscreen();
  } catch (_) { /* 무시 */ }
}

function applyPresentation(on) {
  bodyEl.classList.toggle("presentation", on);
  // 발표모드일 때 전체화면 진입 시도
  if (on) enterFullscreen(); else exitFullscreen();

  // 발표모드에서 숨길 컨트롤들 처리
  // (controls.presentation-hide 클래스가 붙은 요소 숨김)
  document.querySelectorAll(".controls.presentation-hide").forEach(el => {
    if (on) el.classList.add("d-none");
    else el.classList.remove("d-none");
  });

  $("#btn-present").textContent = on ? "⛶ 발표모드 종료" : "⛶ 발표모드";
  localStorage.setItem("draw.presentation", on ? "1" : "0");
}

function togglePresentation() {
  const on = !bodyEl.classList.contains("presentation");
  applyPresentation(on);
}

// 초기화 시 저장된 상태 복원
document.addEventListener("DOMContentLoaded", () => {
  // 다크모드
  const dark = localStorage.getItem("draw.dark") === "1";
  applyDarkMode(dark);

  // 발표모드
  const pres = localStorage.getItem("draw.presentation") === "1";
  applyPresentation(pres);
  syncThemeForComponents();
});

// 버튼 바인딩
document.addEventListener("DOMContentLoaded", () => {
  $("#btn-darkmode")?.addEventListener("click", toggleDarkMode);
  $("#btn-present")?.addEventListener("click", togglePresentation);
  document.getElementById("logout-form")?.addEventListener("submit", (e) => {
    if (!confirm("로그아웃 하시겠습니까?")) e.preventDefault();
  });
});

// 단축키: D=다크모드, P=발표모드, Esc=발표모드 종료
document.addEventListener("keydown", (ev) => {
  // 입력 폼 포커스 중엔 단축키 무시
  const tag = (ev.target.tagName || "").toLowerCase();
  if (["input", "textarea", "select"].includes(tag)) return;

  if (ev.key === "d" || ev.key === "D") {
    ev.preventDefault();
    toggleDarkMode();
  } else if (ev.key === "p" || ev.key === "P") {
    ev.preventDefault();
    togglePresentation();
  } else if (ev.key === "Escape") {
    if (bodyEl.classList.contains("presentation")) {
      ev.preventDefault();
      applyPresentation(false);
    }
  }
});

// 전체화면에서 사용자가 수동으로 빠져나간 경우 버튼/상태 동기화
document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement && bodyEl.classList.contains("presentation")) {
    // 전체화면만 빠졌더라도 발표모드 유지할지 여부는 선택사항.
    // 여기서는 전체화면 이탈 시 발표모드도 종료하도록 처리.
    applyPresentation(false);
  }
});


// ===== 안전 유틸 =====
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// 안전한 DOM 생성
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (typeof c === "string") node.appendChild(document.createTextNode(c));
    else if (c instanceof Node) node.appendChild(c);
  }
  return node;
}

// 에러 박스 헬퍼
const errorBox = $("#error");
function showError(msg) {
  errorBox.textContent = msg ?? "알 수 없는 오류가 발생했습니다.";
  errorBox.classList.remove("d-none");
}
function hideError() {
  errorBox.classList.add("d-none");
}

// ===== 전역 상태 =====
const allDrawn = new Set();
let giftLimits = {};
let busy = false; // 이중 요청 방지

// ===== 서버 통신 =====
async function api(url, opts = {}) {
  try {
    const res = await fetch(url, {
      credentials: "same-origin",
      ...opts,
    });
    // JSON 응답 일관 처리
    const ct = res.headers.get("content-type") || "";
    if (!res.ok) {
      const body = ct.includes("application/json") ? await res.json() : await res.text();
      const msg = typeof body === "object" && body?.error ? body.error : (body || res.statusText);
      throw new Error(msg);
    }
    return ct.includes("application/json") ? res.json() : res.text();
  } catch (e) {
    throw new Error(e.message || "네트워크 오류");
  }
}

// ===== 상태/제한값 =====
async function loadGiftLimits() {
  const data = await api("/limits");
  giftLimits = data || {};
  const giftSelect = $("#gift");
  giftSelect.innerHTML = ""; // 최신 목록 반영

  for (const [giftName] of Object.entries(giftLimits)) {
    giftSelect.appendChild(el("option", { value: giftName, text: giftName }));
  }
  // 첫 항목 기준으로 제한값 표시
  $("#gift-limit").value = giftLimits[giftSelect.value] ?? "";
}

async function updateState() {
  const data = await api("/state");

  // 최근 추첨 결과 테이블 렌더
  const recentTbody = $("#recent-table-body");
  recentTbody.replaceChildren(); // 안전 초기화
  for (const entry of data.result) {
    const tr = el("tr");
    tr.appendChild(el("td", { text: entry["면허번호"] }));
    tr.appendChild(el("td", { text: entry["이름"] }));
    tr.appendChild(el("td", { text: entry["소속기관"] }));
    tr.appendChild(el("td", { text: entry["경품"] }));
    // 재추첨 버튼(이벤트 위임용 data-* 부여)
    const btn = el("button", {
      class: "btn btn-sm btn-outline-warning",
      type: "button",
      text: "재추첨",
      dataset: { action: "redraw", payload: JSON.stringify(entry) },
    });
    tr.appendChild(el("td", {}, [btn]));
    recentTbody.appendChild(tr);
  }

  // 전체 누적 리스트 렌더
  const list = $("#result");
  list.replaceChildren();
  allDrawn.clear();
  for (const entry of data.all) {
    const key = `${entry["면허번호"]}_${entry["이름"]}_${entry["소속기관"]}_${entry["경품"]}`;
    if (allDrawn.has(key)) continue;
    allDrawn.add(key);

    const li = el("li", { class: "list-group-item d-flex justify-content-between align-items-center" });
    li.appendChild(
      el("span", {
        text: `${entry["면허번호"]} - ${entry["이름"]} - ${entry["소속기관"]} - [${entry["경품"]}]`,
      })
    );
    const delBtn = el("button", {
      class: "btn btn-sm btn-outline-danger",
      type: "button",
      text: "🗑",
      title: "삭제",
      dataset: { action: "delete", payload: JSON.stringify(entry) },
    });
    li.appendChild(delBtn);
    list.appendChild(li);
  }

  // 카운트들
  $("#remaining").textContent = data.remaining;
  $("#total-winners").textContent = data.total;

  // 경품별 개수
  const giftCountsDiv = $("#gift-counts");
  const giftCounts = data.gift_counts || {};
  giftCountsDiv.replaceChildren();
  const pieces = [];
  for (const [g, c] of Object.entries(giftCounts)) pieces.push(`${g}: ${c}명`);
  giftCountsDiv.appendChild(document.createTextNode(pieces.join("   •   ")));
}

// ===== 액션들 =====
async function doDraw() {
  if (busy) return;
  hideError();

  // 입력 검증
  const countStr = $("#count").value.trim();
  const gift = $("#gift").value;
  const limitStr = $("#gift-limit").value.trim();

  const count = Number.parseInt(countStr, 10);
  if (!Number.isFinite(count) || count <= 0) {
    showError("추첨 인원 수는 1 이상의 정수여야 합니다.");
    return;
  }
  if (!gift) {
    showError("경품명을 선택하세요.");
    return;
  }

  // 프런트 로컬 제한값 갱신(서버도 동시에 업데이트)
  if (limitStr !== "") {
    const parsed = Number.parseInt(limitStr, 10);
    if (!Number.isFinite(parsed) || parsed < 1) {
      showError("경품 최대 인원 수는 1 이상의 정수여야 합니다.");
      return;
    }
    giftLimits[gift] = parsed;
  }

  // 이중 클릭 방지
  busy = true;
  const btn = $("#btn-draw");
  btn.disabled = true;

  try {
    const body = new URLSearchParams();
    body.set("count", String(count));
    body.set("gift", gift);
    if (limitStr !== "") body.set("limit", limitStr);

    const data = await api("/draw", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });

    // 최근 테이블 즉시 표시(안전 렌더)
    const recentTbody = $("#recent-table-body");
    recentTbody.replaceChildren();
    for (const entry of data.result) {
      const tr = el("tr");
      tr.appendChild(el("td", { text: entry["면허번호"] }));
      tr.appendChild(el("td", { text: entry["이름"] }));
      tr.appendChild(el("td", { text: entry["소속기관"] }));
      tr.appendChild(el("td", { text: entry["경품"] }));
      tr.appendChild(el("td", {}, [
        el("button", {
          class: "btn btn-sm btn-outline-warning",
          type: "button",
          text: "재추첨",
          dataset: { action: "redraw", payload: JSON.stringify(entry) },
        }),
      ]));
      recentTbody.appendChild(tr);
    }

    await updateState();
    launchConfetti();

    // 서버 기준 최신 제한값 재동기화
    giftLimits = await api("/limits");
    // 현재 선택된 경품의 제한값 UI 갱신
    $("#gift-limit").value = giftLimits[gift] ?? "";

  } catch (e) {
    showError(e.message);
  } finally {
    busy = false;
    btn.disabled = false;
  }
}

async function doDelete(entry) {
  try {
    const ok = confirm(
      `정말로 삭제하시겠습니까?\n${entry["면허번호"]} - ${entry["이름"]} - ${entry["소속기관"]} - [${entry["경품"]}]`
    );
    if (!ok) return;
    await api("/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entry),
    });
    await updateState();
  } catch (e) {
    showError(e.message);
  }
}

async function doRedraw(entry) {
  try {
    const ok = confirm(
      `정말로 재추첨 하시겠습니까?\n${entry["면허번호"]} - ${entry["이름"]} - ${entry["소속기관"]} - [${entry["경품"]}]`
    );
    if (!ok) return;

    // 1) 삭제
    const delRes = await api("/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entry),
    });
    if (!delRes?.success) {
      throw new Error(delRes?.error || "삭제 실패");
    }

    // 2) 같은 경품으로 1명 재추첨 (해당 참가자 exclude)
    const params = new URLSearchParams();
    params.set("count", "1");
    params.set("gift", entry["경품"]);
    params.set("exclude", JSON.stringify(entry));

    const drawRes = await api("/draw", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: params,
    });
    if (!drawRes || drawRes.error) {
      throw new Error(drawRes?.error || "재추첨 실패");
    }

    // 최근 테이블 1명 교체 반영
    const recentTbody = $("#recent-table-body");
    recentTbody.replaceChildren();
    for (const ne of drawRes.result) {
      const tr = el("tr");
      tr.appendChild(el("td", { text: ne["면허번호"] }));
      tr.appendChild(el("td", { text: ne["이름"] }));
      tr.appendChild(el("td", { text: ne["소속기관"] }));
      tr.appendChild(el("td", { text: ne["경품"] }));
      tr.appendChild(el("td", {}, [
        el("button", {
          class: "btn btn-sm btn-outline-warning",
          type: "button",
          text: "재추첨",
          dataset: { action: "redraw", payload: JSON.stringify(ne) },
        }),
      ]));
      recentTbody.appendChild(tr);
    }

    await updateState();
    launchConfetti();
  } catch (e) {
    showError(e.message);
  }
}

async function doClear() {
  try {
    await api("/clear", { method: "POST" });
    await updateState();
  } catch (e) {
    showError(e.message);
  }
}

async function doReset() {
  try {
    const ok = confirm("정말 전체 초기화하시겠습니까? (업로드 목록/당첨자 전부 초기화)");
    if (!ok) return;
    await api("/reset", { method: "POST" });
    await updateState();
  } catch (e) {
    showError(e.message);
  }
}

// ===== 이벤트 바인딩 =====
document.addEventListener("DOMContentLoaded", async () => {
  try {
    hideError();
    await updateState();
    await loadGiftLimits();
  } catch (e) {
    showError(e.message);
  }

  // 추첨 버튼
  $("#btn-draw").addEventListener("click", doDraw);

  // Enter 키로 추첨
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      doDraw();
    }
  });

  // 경품 선택 변경 → 제한값 입력 반영
  $("#gift").addEventListener("change", () => {
    const gift = $("#gift").value;
    $("#gift-limit").value = giftLimits[gift] ?? "";
  });

  // 초기화 버튼들
  $("#btn-clear").addEventListener("click", doClear);
  $("#btn-reset").addEventListener("click", doReset);

  // 재추첨/삭제 이벤트 위임
  // - 최근 테이블의 재추첨 버튼
  $("#recent-table-body").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const payload = btn.dataset.payload ? JSON.parse(btn.dataset.payload) : null;
    if (action === "redraw" && payload) doRedraw(payload);
  });

  // - 전체 누적 리스트의 삭제 버튼
  $("#result").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const payload = btn.dataset.payload ? JSON.parse(btn.dataset.payload) : null;
    if (action === "delete" && payload) doDelete(payload);
  });
});

// ===== 이펙트 =====
function launchConfetti() {
  if (!window.confetti) return;
  confetti({
    particleCount: 150,
    spread: 120,
    origin: { y: 0.6 },
  });
}
