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
    lowOnly: store.get("lowOnly", false),
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
  const won = (v) => (Number.isFinite(v) ? Math.round(v).toLocaleString("ko-KR") + "원" : "");
  const cnt = (v) => (Number.isFinite(v) && v > 0 ? v : null);
  // 날짜: 올해면 "10/12", 다른 해면 "2025.6.12" (문자열의 날짜를 그대로 써서 시간대 밀림 없음)
  const THIS_YEAR = new Date().getFullYear();
  const md = (iso) => {
    const m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(String(iso || ""));
    const d = m ? { y: +m[1], mo: +m[2], da: +m[3] } : null;
    if (!d || !d.mo || !d.da) return "";
    return d.y === THIS_YEAR ? `${d.mo}/${d.da}` : `${d.y}.${d.mo}.${d.da}`;
  };
  // 역대 최저가 정보 (없거나 형식이 이상하면 null → 카드는 예전 그대로)
  const prodOf = (g) => (g.product && typeof g.product === "object" && (g.currency || "KRW") === "KRW" ? g.product : null);
  const histOf = (p) => (p && p.history && typeof p.history === "object" ? p.history : null);
  const samplesOf = (h) => (h && Number.isFinite(h.samples) && h.samples > 0 ? Math.floor(h.samples) : 0);
  // 화면에 쓰는 판정: '역대최저' 는 과거 기록 2건 이상일 때만 (1건 이하면 배지 없음)
  const verdictOf = (p) => (!p ? null : p.verdict === "lowest" && samplesOf(histOf(p)) < 2 ? null : p.verdict);
  const isCond = (o) => !!(o && o.cond === true);
  const obsOf = (o) => (o && typeof o === "object" && (Number.isFinite(o.price) || Number.isFinite(o.unit_price)) ? o : null);
  // 단위: "개"(기본) 또는 "100g"/"100ml" (무게·용량 판매 — count 없음, unit_price 는 100g/100ml 당)
  const WEIGHT = { "100g": "g", "100ml": "ml" };
  // 개수 단위 이름: product.unit_label ("캡슐"/"캔"/"정" …), 없거나 이상하면 "개"
  const countLabel = (p) => { const l = typeof p?.unit_label === "string" ? p.unit_label.trim() : ""; return l && l.length <= 6 ? l : "개"; };
  const unitName = (p) => (WEIGHT[p?.unit] ? p.unit : countLabel(p));
  const unitOf = (o, p) => (Number.isFinite(o.unit_price) ? o.unit_price
    : !WEIGHT[p?.unit] && Number.isFinite(o.price) && cnt(o.count) ? o.price / o.count : null);
  const sizeText = (v, p) => {
    if (!cnt(v)) return "";
    const ml = WEIGHT[p?.unit] === "ml";
    return v >= 1000 ? `${Math.round(v / 100) / 10}${ml ? "L" : "kg"}` : `${v}${ml ? "ml" : "g"}`;
  };
  // 수량(개) 또는 포장 크기(2kg) 표기
  const qtyText = (o, p) => (WEIGHT[p?.unit] ? sizeText(o.size_g, p) : cnt(o.count) ? cnt(o.count) + countLabel(p) : "");
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
      if (state.lowOnly && !["lowest", "near"].includes(verdictOf(prodOf(g)))) return false;
      // '전체'는 국내 + 공식몰만. 해외 딜은 '해외' 탭에서만 보임
      const region = regionOf(g, meta);
      if (state.region === "all" ? region === "global" : region !== state.region) return false;
      if (g.sources.every((s) => state.off.has(s.source))) return false;
      if (words.length) {
        const hay = (g.title + " " + (g.shop || "") + " " + (prodOf(g)?.name || "") + " " + g.sources.map((s) => s.title).join(" ")).toLowerCase();
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
      low: (a, b) => lowRank(a) - lowRank(b) || lowDiff(a) - lowDiff(b) || ts(b) - ts(a),
    }[state.sort];
    if (state.sort === "cheap") list = list.filter((g) => g.currency === "KRW" || state.region === "global");
    return list.sort(by);
  }

  // 역대최저 대비 싼 순: 역대최저 → 근접(차이 작은 순) → 비쌈(차이 작은 순) → 첫 기록 → 정보 없음
  const RANK = { lowest: 0, equal: 1, near: 1, higher: 2, first: 3 };
  const lowRank = (g) => RANK[verdictOf(prodOf(g))] ?? 4;
  const lowDiff = (g) => { const v = prodOf(g)?.diff_pct; return Number.isFinite(v) ? v : Infinity; };

  // ---------- 그리기 ----------
  // 과거 글 링크: "원글 · 2025.6.12 루리웹 ↗" (표 안에서는 앞의 '원글 ·' 생략). 원래 제목은 마우스오버
  const srcLink = (o, meta, short) => {
    const where = [md(o.date), meta[o.source]?.name || o.source || ""].filter(Boolean).join(" ");
    const label = short ? where || "원글" : where ? "원글 · " + where : "원글";
    const u = safeUrl(o.url);
    const tip = o.title ? "원글: " + o.title + (o.ended ? " (종료)" : "") : "";
    return u === "#" ? esc(label)
      : `<a class="plink${o.ended ? " end" : ""}" href="${esc(u)}" target="_blank" rel="noopener nofollow" title="${esc(tip)}">${esc(label)} ↗</a>`;
  };
  const condTag = (o) => (isCond(o) ? `<span class="ptag" title="카드·멤버십·신규가입 등 조건이 붙은 가격">조건부</span> ` : "");
  // "개당 795원 · 20개 15,900원" / "100g당 775원 · 2kg 15,500원" (단가 모르면 "15,900원")
  const obsText = (o, p) => {
    const u = unitOf(o, p), q = qtyText(o, p);
    if (u !== null) return [`${unitName(p)}당 ${won(u)}`, [q, won(o.price)].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
    return [q, won(o.price)].filter(Boolean).join(" ");
  };
  function lowest(g, meta) {
    const p = prodOf(g);
    if (!p) return "";
    const h = histOf(p);
    const v = verdictOf(p);
    const wt = !!WEIGHT[p.unit];
    const c = wt ? null : cnt(p.count);
    const q = wt ? sizeText(p.size_g, p) || (p.size ? String(p.size) : "") : c ? `${p.size ? p.size + "×" : ""}${c}${countLabel(p)}` : "";
    const unit = Number.isFinite(p.unit_price) ? esc(`${unitName(p)}당 ${won(p.unit_price)}` + (q ? ` (${q})` : "")) : "";
    const diff = Number.isFinite(p.diff_pct) ? Math.round(p.diff_pct * 10) / 10 : null;
    // 'first'(첫 기록)·표본 부족 '역대최저'·모르는 판정은 배지 없음
    const badge = {
      lowest: `<span class="pv low">🏆 역대최저</span>`,
      equal: `<span class="pv near">역대최저와 같음</span>`,
      near: `<span class="pv near">최저가 근접${diff !== null ? " +" + diff + "%" : ""}</span>`,
      higher: `<span class="pv high">역대최저 대비 ${diff !== null ? "+" + diff + "%" : "비쌈"}</span>`,
    }[v] || "";
    const n = samplesOf(h);
    const since = h ? md(h.since) : "";
    const rec = n ? `<span class="pn"${since ? ` title="${esc(since)}부터 기록"` : ""}>최근 ${n}건 중</span>` : "";

    let low = null, rows = [];
    if (h) {
      low = obsOf(h.low_unit) || obsOf(h.low_same_count);
      // 수량별 최저가 (tiers 가 비어도 low_unit/low_same_count 로 대신 채움)
      rows = (Array.isArray(h.tiers) ? h.tiers : []).map(obsOf).filter(Boolean);
      if (!rows.length) rows = [obsOf(h.low_unit), obsOf(h.low_same_count)].filter((o, i, a) => o && a.findIndex((x) => x && x.url === o.url && x.price === o.price) === i);
      if (!low && rows.length) low = rows[0];
    }
    // 최저가 줄이 없으면 표본 수는 배지 옆에
    const recInRow = badge && rec && !low;
    let out = unit || badge ? `<div class="prow">${unit ? `<span class="punit">${unit}</span>` : ""}${badge}${recInRow ? rec : ""}</div>` : "";
    if (!h) return out;

    const table = rows.length > 1; // 한 줄뿐이면 '역대 최저' 줄과 같으므로 표는 생략
    if (low) out += `<div class="plow${isCond(low) ? " cond" : ""}">${condTag(low)}${v === "lowest" ? "이전 최저" : "역대 최저"} ${esc(obsText(low, p))} · ${srcLink(low, meta)}${rec ? " · " + rec : ""}</div>`;
    // 조건부(카드·멤버십 등) 최저가는 따로 한 줄 (본 최저가와 같은 글이면 생략)
    const lc = obsOf(h.low_cond);
    if (lc && !(low && low.url === lc.url && low.price === lc.price)) {
      const lu = unitOf(lc, p);
      const lt = lu !== null ? `${unitName(p)}당 ${won(lu)}` : obsText(lc, p);
      out += `<div class="plow cond">조건부 최저 ${esc(lt)} (카드/멤버십 등) · ${srcLink(lc, meta)}</div>`;
    }
    if (table) {
      const units = rows.map((o) => unitOf(o, p));
      const curKey = wt ? cnt(p.size_g) : c;
      // 🏆 표시는 일반가 기준 (일반가가 하나도 없을 때만 조건부 포함)
      const plain = units.filter((u, i) => u !== null && !isCond(rows[i]));
      const best = Math.min(...(plain.length ? plain : units.filter((u) => u !== null)));
      const trs = rows.map((o, i) => {
        const same = !!curKey && cnt(wt ? o.size_g : o.count) === curKey;
        const top = units[i] !== null && units[i] === best && (!plain.length || !isCond(o));
        const cls = [same && "cur", top && "best", isCond(o) && "cond"].filter(Boolean).join(" ");
        return `<tr class="${cls}"><td>${esc(qtyText(o, p) || "-")}${same ? " <b>현재</b>" : ""}</td><td>${esc(won(o.price) || "-")}</td><td>${units[i] !== null ? esc(won(units[i])) : "-"}${top ? " 🏆" : ""}</td><td>${condTag(o)}${srcLink(o, meta, true)}</td></tr>`;
      }).join("");
      out += `<details class="tiers"><summary>${wt ? "용량별" : "수량별"} 최저가</summary><table><thead><tr><th>${wt ? "용량" : "수량"}</th><th>가격</th><th>${esc(unitName(p))}당</th><th>원글</th></tr></thead><tbody>${trs}</tbody></table></details>`;
    }
    return out;
  }

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
      ${lowest(g, meta)}
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
    // 해외 탭에선 해외 사이트 칩만, 나머지 탭에선 국내 사이트 칩만
    const wantGlobal = state.region === "global";
    // 지금 목록에 딜이 하나도 없는 소스(예: 서버에서 차단된 사이트)는 칩을 숨김
    const has = new Set((state.data.groups || []).flatMap((g) => (g.sources || []).map((s) => s.source)));
    $("#chips").innerHTML = (state.data.sources || []).filter((s) => (s.region === "global") === wantGlobal && has.has(s.key)).map((s) =>
      `<button class="chip${state.off.has(s.key) ? " off" : ""}" data-k="${esc(s.key)}">${esc(s.name)}</button>`).join("");
  }

  function renderStatus(st) {
    if (!st || typeof st.sources !== "object" || !st.sources) return;
    const meta = srcMeta();
    $("#status").innerHTML = Object.entries(st.sources).map(([k, v]) =>
      // blocked = 사이트가 수집을 막음(robots.txt·서버 차단) → 오류가 아니라 '수집 불가' 로 표시
      `<li title="${esc(v?.error || "")}"><span class="${v?.ok ? "ok" : v?.blocked ? "muted" : "err"}">●</span> ${esc(meta[k]?.name || k)} — ${v?.ok ? num(v.count) + "개" : v?.blocked ? "사이트가 자동 수집을 막아 제외" : "오류"}</li>`).join("")
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
      if (state.data) renderChips();
      render();
    };
  });
  $("#sort").value = state.sort;
  $("#sort").onchange = (e) => { state.sort = e.target.value; store.set("sort", state.sort); render(); };
  $("#hideEnded").checked = state.hideEnded;
  $("#hideEnded").onchange = (e) => { state.hideEnded = e.target.checked; store.set("hideEnded", state.hideEnded); render(); };
  $("#multiOnly").checked = state.multiOnly;
  $("#multiOnly").onchange = (e) => { state.multiOnly = e.target.checked; store.set("multiOnly", state.multiOnly); render(); };
  $("#lowOnly").checked = state.lowOnly;
  $("#lowOnly").onchange = (e) => { state.lowOnly = e.target.checked; store.set("lowOnly", state.lowOnly); state.shown = PAGE; render(); };
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
