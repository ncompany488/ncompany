// 핫딜 허브 화면 로직 (서버 없이 data/deals.json 만 읽음)
(() => {
  const CFG = window.HOTDEAL_CONFIG || {};
  const PAGE = 60;
  const $ = (s) => document.querySelector(s);
  const store = {
    get(k, d) { try { const v = localStorage.getItem("hh:" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("hh:" + k, JSON.stringify(v)); } catch {} },
  };

  const state = {
    data: null,
    q: "",
    region: store.get("region", "all"),
    sort: store.get("sort", "new"),
    hideEnded: store.get("hideEnded", true),
    multiOnly: store.get("multiOnly", false),
    off: new Set(store.get("off", [])),   // 숨긴 소스
    shown: PAGE,
  };

  // ---------- 테마 ----------
  const theme = store.get("theme", null);
  if (theme) document.documentElement.dataset.theme = theme;
  $("#theme").onclick = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set("theme", next);
  };

  // ---------- 유틸 ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  function price(g) {
    if (!Number.isFinite(g.price)) return "";
    if (g.currency === "USD") return "$" + (g.price / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return g.price.toLocaleString("ko-KR") + "원";
  }
  function ago(iso) {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (!Number.isFinite(s)) return "";
    if (s < 60) return "방금";
    if (s < 3600) return Math.floor(s / 60) + "분 전";
    if (s < 86400) return Math.floor(s / 3600) + "시간 전";
    return Math.floor(s / 86400) + "일 전";
  }
  const ts = (g) => new Date(g.posted_at || g.first_seen || 0).getTime() || 0;
  const num = (v) => (Number.isFinite(v) ? v : 0); // 데이터 숫자 칸은 숫자만 화면에
  const srcMeta = () => Object.fromEntries((state.data?.sources || []).map((s) => [s.key, s]));

  // 공식몰 직접 수집은 대부분 차단돼 있어서, 커뮤니티 딜 중 판매처가 대형 공식몰인 것을 '공식몰'로 분류
  const MALLS = /쿠팡|11번가|11st|g마켓|지마켓|gmarket|옥션|auction|ssg|이마트|롯데온|롯데|네이버|스마트스토어|컬리|올리브영|하이마트|홈플러스|오늘의집|무신사|cj|gs|현대|위메프|알리|aliexpress|테무|아마존|amazon|ebay|best\s*buy|walmart|target|costco|코스트코/i;
  function regionOf(g, meta) {
    const kinds = g.sources.map((s) => meta[s.source] || {});
    if (kinds.some((m) => m.region === "global") || g.currency !== "KRW") return "global";
    if (kinds.some((m) => m.kind === "official") || MALLS.test(g.shop || "")) return "official";
    return "kr";
  }

  // ---------- 필터·정렬 ----------
  function filtered() {
    const meta = srcMeta();
    const words = state.q.toLowerCase().split(/\s+/).filter(Boolean);
    let list = state.data.groups.filter((g) => {
      if (state.hideEnded && g.ended) return false;
      if (state.multiOnly && g.sources.length < 2) return false;
      if (state.region !== "all" && regionOf(g, meta) !== state.region) return false;
      if (g.sources.every((s) => state.off.has(s.source))) return false;
      if (words.length) {
        const hay = (g.title + " " + (g.shop || "") + " " + g.sources.map((s) => s.title).join(" ")).toLowerCase();
        const nos = hay.replace(/\s+/g, "");
        if (!words.every((w) => hay.includes(w) || nos.includes(w))) return false;
      }
      return true;
    });
    const hot = (g) => (g.likes || 0) * 3 + (g.comments || 0) + (g.sources.length - 1) * 30;
    const by = {
      new: (a, b) => ts(b) - ts(a),
      hot: (a, b) => hot(b) - hot(a) || ts(b) - ts(a),
      multi: (a, b) => b.sources.length - a.sources.length || ts(b) - ts(a),
      cheap: (a, b) => (a.price ?? Infinity) - (b.price ?? Infinity) || ts(b) - ts(a),
    }[state.sort];
    if (state.sort === "cheap") list = list.filter((g) => g.currency === "KRW" || state.region === "global");
    return list.sort(by);
  }

  // ---------- 그리기 ----------
  function card(g, meta) {
    const main = g.sources[0];
    const srcs = g.sources.map((s) =>
      `<a class="src${s.ended ? " end" : ""}" href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener nofollow" title="${esc(s.title)}">${esc(meta[s.source]?.name || s.source)}${num(s.likes) ? " 👍" + num(s.likes) : ""}${num(s.comments) ? " 💬" + num(s.comments) : ""}</a>`
    ).join("");
    const thumb = safeUrl(g.thumbnail) !== "#"
      ? `<img class="thumb" src="${esc(safeUrl(g.thumbnail))}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'">`
      : `<div class="thumb"></div>`;
    return `<li class="deal${g.ended ? " ended" : ""}">${thumb}<div class="body">
      <a class="title" href="${esc(safeUrl(main.url))}" target="_blank" rel="noopener nofollow">${esc(g.title)}</a>
      <div class="row">
        ${price(g) ? `<span class="price">${esc(price(g))}</span>` : ""}
        ${g.shop ? `<span class="shop">${esc(g.shop)}</span>` : ""}
        ${g.sources.length > 1 ? `<span class="multi">${g.sources.length}곳 공유</span>` : ""}
        ${g.ended ? `<span class="badge-end">종료</span>` : ""}
        <span>${ago(g.posted_at || g.first_seen)}</span>
      </div>
      <div class="srcs">${srcs}</div>
    </div></li>`;
  }

  function render() {
    if (!state.data) return;
    const meta = srcMeta();
    const list = filtered();
    $("#list").innerHTML = list.slice(0, state.shown).map((g) => card(g, meta)).join("");
    $("#more").hidden = list.length <= state.shown;
    $("#empty").hidden = list.length > 0;
    const up = ago(state.data.updated_at);
    $("#meta").textContent = `${list.length.toLocaleString()}개 딜` + (up ? ` · ${up} 업데이트` : "");
  }

  function renderChips() {
    $("#chips").innerHTML = (state.data.sources || []).map((s) =>
      `<button class="chip${state.off.has(s.key) ? " off" : ""}" data-k="${esc(s.key)}">${esc(s.name)}</button>`).join("");
  }

  function renderStatus(st) {
    if (!st || typeof st.sources !== "object" || !st.sources) return;
    const meta = srcMeta();
    $("#status").innerHTML = Object.entries(st.sources).map(([k, v]) =>
      `<li title="${esc(v?.error || "")}"><span class="${v?.ok ? "ok" : "err"}">●</span> ${esc(meta[k]?.name || k)} — ${v?.ok ? num(v.count) + "개" : "오류"}</li>`).join("")
      + (ago(st.run_at) ? `<li>마지막 수집: ${esc(new Date(st.run_at).toLocaleString("ko-KR"))}</li>` : "");
  }

  // ---------- 이벤트 ----------
  let qTimer;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { state.q = e.target.value.trim(); state.shown = PAGE; render(); }, 150);
  });
  document.querySelectorAll("#region button").forEach((b) => {
    b.classList.toggle("on", b.dataset.v === state.region);
    b.onclick = () => {
      state.region = b.dataset.v; store.set("region", state.region); state.shown = PAGE;
      document.querySelectorAll("#region button").forEach((x) => x.classList.toggle("on", x === b));
      render();
    };
  });
  $("#sort").value = state.sort;
  $("#sort").onchange = (e) => { state.sort = e.target.value; store.set("sort", state.sort); render(); };
  $("#hideEnded").checked = state.hideEnded;
  $("#hideEnded").onchange = (e) => { state.hideEnded = e.target.checked; store.set("hideEnded", state.hideEnded); render(); };
  $("#multiOnly").checked = state.multiOnly;
  $("#multiOnly").onchange = (e) => { state.multiOnly = e.target.checked; store.set("multiOnly", state.multiOnly); render(); };
  $("#chips").onclick = (e) => {
    const k = e.target.dataset?.k;
    if (!k) return;
    state.off.has(k) ? state.off.delete(k) : state.off.add(k);
    store.set("off", [...state.off]);
    renderChips(); render();
  };
  $("#more").onclick = () => { state.shown += PAGE; render(); };

  const bot = $("#botLink");
  if (CFG.telegramBot) bot.href = "https://t.me/" + encodeURIComponent(CFG.telegramBot);
  else bot.replaceWith(document.createTextNode("알림봇(아직 설정 전)"));

  // ---------- 데이터 ----------
  async function load() {
    try {
      const [d, st] = await Promise.all([
        fetch("data/deals.json?t=" + Date.now()).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }),
        fetch("data/status.json?t=" + Date.now()).then((r) => (r.ok ? r.json() : null)).catch(() => null),
      ]);
      // 형식이 이상해도 화면이 깨지지 않게 기본값
      d.groups = (Array.isArray(d.groups) ? d.groups : []).filter((g) => g && Array.isArray(g.sources) && g.sources.length);
      d.sources = Array.isArray(d.sources) ? d.sources : [];
      state.data = d;
      renderChips(); render(); renderStatus(st);
    } catch (e) {
      $("#meta").textContent = "데이터를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.";
    }
  }
  load();
  setInterval(load, (CFG.refreshMinutes || 5) * 60 * 1000);
  setInterval(render, 60 * 1000); // '몇 분 전' 갱신
})();
