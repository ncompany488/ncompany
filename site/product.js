// 상품 페이지: product.html?id=<pid> → data/products/<NN>.json 에서 그 상품의 가격 기록을 읽어 보여줌
(() => {
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const fin = Number.isFinite;
  const won = (v) => (fin(v) ? Math.round(v).toLocaleString("ko-KR") + "원" : "");
  // 단가: 100원 미만이면 소수 한 자리까지 (100ml당 8.3원 등)
  const wonU = (v) => (!fin(v) ? "" : Math.abs(v) < 100 && Math.round(v) !== v
    ? v.toLocaleString("ko-KR", { maximumFractionDigits: 1 }) + "원" : won(v));
  const THIS_YEAR = new Date().getFullYear();
  // 날짜 문자열의 앞부분을 그대로 사용 (시간대 밀림 없음). 올해면 "10/12", 다른 해면 "2025.6.12"
  const ymd = (iso) => {
    const m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(String(iso || ""));
    return m ? { y: +m[1], mo: +m[2], da: +m[3] } : null;
  };
  const md = (iso) => { const d = ymd(iso); return !d ? "" : d.y === THIS_YEAR ? `${d.mo}/${d.da}` : `${d.y}.${d.mo}.${d.da}`; };
  const fullDate = (iso) => { const d = ymd(iso); return d ? `${d.y}.${d.mo}.${d.da}` : ""; };
  const timeOf = (o) => { const t = Date.parse(o.d); return fin(t) ? t : null; };

  // 샤드 번호: fnv1a32(UTF-8 바이트) % 64 → "07" (가공 쪽 계약과 같은 계산)
  function fnv1a32(str) {
    let h = 0x811c9dc5;
    for (const b of new TextEncoder().encode(str)) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
    return h >>> 0;
  }
  const shardOf = (pid) => String(fnv1a32(pid) % 64).padStart(2, "0");
  window.hhShardOf = shardOf; // 콘솔 확인용: hhShardOf("신라면")

  const FALLBACK_SRC = { arca: "아카라이브", clien: "클리앙", dealbada: "딜바다", dealnews: "DealNews", eomisae: "어미새", ppomppu: "뽐뿌", ppomppu_global: "해외뽐뿌", ruliweb: "루리웹", quasarzone: "퀘이사존", fmkorea: "에펨코리아" };
  let srcNames = { ...FALLBACK_SRC };
  const srcName = (k) => (k && Object.prototype.hasOwnProperty.call(srcNames, k) ? srcNames[k] : k || "");

  const main = $("#pd");
  const fail = (msg) => {
    main.innerHTML = `<section class="pcard"><p>${esc(msg)}</p><p><a class="plink" href="./">← 메인에서 다른 딜 보기</a></p></section>`;
  };

  // ---------- 단위 ----------
  const WEIGHT = { "100g": "g", "100ml": "ml" };
  let P = null; // 현재 상품
  const isWt = () => !!WEIGHT[P.basis];
  const unitWord = () => {
    if (isWt()) return P.basis;
    const l = typeof P.unit_label === "string" ? P.unit_label.trim() : "";
    return l && l.length <= 6 ? l : "개";
  };
  const sizeText = (v) => {
    if (!(fin(v) && v > 0)) return "";
    const ml = WEIGHT[P.basis] === "ml";
    return v >= 1000 ? `${Math.round(v / 100) / 10}${ml ? "L" : "kg"}` : `${v}${ml ? "ml" : "g"}`;
  };
  const cntWord = () => { const l = typeof P.unit_label === "string" ? P.unit_label.trim() : ""; return l && l.length <= 6 ? l : "개"; };
  const qtyText = (o) => (isWt() ? sizeText(o.g) : fin(o.n) && o.n > 0 ? o.n + cntWord() : "");
  const unitText = (o) => (P.basis && fin(o.u) ? `${unitWord()}당 ${wonU(o.u)}` : "");
  const tags = (o) => (o.c ? `<span class="ptag" title="카드·멤버십·신규가입 등 조건이 붙은 가격">조건부</span>` : "")
    + (o.e ? `<span class="ptag end">종료</span>` : "");
  const link = (o, label) => {
    const u = safeUrl(o.url);
    return u === "#" ? esc(label) : `<a class="plink${o.e ? " end" : ""}" href="${esc(u)}" target="_blank" rel="noopener nofollow" title="${esc(o.t || "")}">${esc(label)} ↗</a>`;
  };

  // ---------- 그래프 (u 기준, 단가 기록이 하나도 없으면 총액 p) ----------
  let useU = false;
  const val = (o) => (useU ? o.u : o.p);
  const wonV = (v) => (useU ? wonU(v) : won(v));

  function niceStep(x) {
    const p = Math.pow(10, Math.floor(Math.log10(x)));
    for (const m of [1, 2, 5, 10]) if (m * p >= x) return m * p;
    return 10 * p;
  }

  function chart(points, low) {
    const box = $("#chart");
    if (!box) return;
    if (!points.length) { box.innerHTML = `<p class="meta">그래프로 그릴 가격 기록이 없어요.</p>`; return; }
    const W = Math.max(260, Math.floor(box.clientWidth || 320));
    const H = W < 480 ? 210 : 250;
    const vs = points.map(val);
    let vmin = Math.min(...vs), vmax = Math.max(...vs);
    if (vmin === vmax) { const pad = Math.max(1, Math.abs(vmax) * 0.1); vmin -= pad; vmax += pad; }
    const step = niceStep((vmax - vmin) / 3);
    const y0 = Math.max(0, Math.floor(vmin / step) * step), y1 = Math.ceil(vmax / step) * step;
    const yt = [];
    for (let v = y0; v <= y1 + step / 1e6; v += step) yt.push(v);
    const labW = Math.max(...yt.map((v) => wonV(v).length)) * 6.6 + 10;
    const L = Math.ceil(labW), R = 14, T = 22, B = 26;
    const pw = W - L - R, ph = H - T - B;
    const ts = points.map(timeOf);
    let tmin = Math.min(...ts), tmax = Math.max(...ts);
    if (tmin === tmax) { tmin -= 86400000; tmax += 86400000; }
    const X = (t) => L + ((t - tmin) / (tmax - tmin)) * pw;
    const Y = (v) => T + (1 - (v - y0) / (y1 - y0 || 1)) * ph;
    const f1 = (n) => Math.round(n * 10) / 10;

    let s = "";
    // 가로 눈금선 + 금액
    for (const v of yt) s += `<line class="grid" x1="${L}" x2="${W - R}" y1="${f1(Y(v))}" y2="${f1(Y(v))}"/><text class="ax" x="${L - 6}" y="${f1(Y(v) + 4)}" text-anchor="end">${esc(wonV(v))}</text>`;
    // 날짜 눈금 (올해가 아니면 연도 포함)
    const nx = Math.max(2, Math.min(6, Math.floor(pw / 90)));
    const single = Math.min(...ts) === Math.max(...ts);
    const xts = single ? [ts[0]] : Array.from({ length: nx }, (_, i) => tmin + ((tmax - tmin) * i) / (nx - 1));
    xts.forEach((t, i) => {
      const d = new Date(t);
      const lab = d.getFullYear() === THIS_YEAR ? `${d.getMonth() + 1}/${d.getDate()}` : `${d.getFullYear()}.${d.getMonth() + 1}.${d.getDate()}`;
      const anchor = single ? "middle" : i === 0 ? "start" : i === xts.length - 1 ? "end" : "middle";
      s += `<line class="tick" x1="${f1(X(t))}" x2="${f1(X(t))}" y1="${T + ph}" y2="${T + ph + 4}"/><text class="ax" x="${f1(X(t))}" y="${H - 8}" text-anchor="${anchor}">${esc(lab)}</text>`;
    });
    // 계단선: 일반가 기록끼리 (다음 글이 올라올 때까지 그 가격이 유지된 것으로 표시)
    const plain = points.filter((o) => !o.c);
    if (plain.length > 1) {
      let d = `M${f1(X(timeOf(plain[0])))} ${f1(Y(val(plain[0])))}`;
      for (let i = 1; i < plain.length; i++) d += `H${f1(X(timeOf(plain[i])))}V${f1(Y(val(plain[i])))}`;
      s += `<path class="ln" d="${d}"/>`;
    }
    // 역대 최저 표시
    if (low) {
      const lx = X(timeOf(low)), ly = Y(val(low));
      const anchor = lx < L + 60 ? "start" : lx > W - R - 60 ? "end" : "middle";
      s += `<line class="lowline" x1="${L}" x2="${W - R}" y1="${f1(ly)}" y2="${f1(ly)}"/>`
        + `<circle class="lowring" cx="${f1(lx)}" cy="${f1(ly)}" r="8"/>`
        + `<text class="lowlab" x="${f1(lx)}" y="${f1(Math.max(12, ly - 12))}" text-anchor="${anchor}">최저 ${esc(wonV(val(low)))}</text>`;
    }
    // 점 (조건부 = 속 빈 점, 종료 = 흐리게). 마우스를 올리면 <title> 로 내용 표시
    for (const o of points) {
      const tip = [fullDate(o.d), won(o.p), unitText(o), qtyText(o), srcName(o.s), o.c ? "조건부" : "", o.e ? "종료" : "", o.t || ""].filter(Boolean).join(" · ");
      s += `<g class="pt${o.c ? " cond" : ""}${o.e ? " end" : ""}"><title>${esc(tip)}</title><circle class="hit" cx="${f1(X(timeOf(o)))}" cy="${f1(Y(val(o)))}" r="10"/><circle class="dot" cx="${f1(X(timeOf(o)))}" cy="${f1(Y(val(o)))}" r="4"/></g>`;
    }
    box.innerHTML = `<svg class="chart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(P.name || "상품")} 가격 추이 그래프">${s}</svg>`;
  }

  // ---------- 페이지 ----------
  function render(id) {
    const obs = (Array.isArray(P.obs) ? P.obs : [])
      .filter((o) => o && typeof o === "object" && (fin(o.p) || fin(o.u)) && timeOf(o) !== null)
      .map((o) => ({ ...o, c: o.c ? 1 : 0, e: o.e ? 1 : 0 }))
      .sort((a, b) => timeOf(a) - timeOf(b));
    if (!obs.length) return fail("이 상품의 가격 기록이 아직 없어요.");
    useU = !!P.basis && obs.some((o) => fin(o.u));
    const points = obs.filter((o) => fin(val(o)));
    const skipped = obs.length - points.length;
    const plain = points.filter((o) => !o.c);
    // 역대 최저 = 조건부 제외 기록 중 가장 싼 것 (같으면 먼저 나온 것)
    const minOf = (arr) => arr.reduce((m, o) => (!m || val(o) < val(m) ? o : m), null);
    const low = minOf(plain);
    const lowCond = minOf(points.filter((o) => o.c));
    const last = obs[obs.length - 1];
    const name = String(P.name || id);
    document.title = `${name} 가격 추이 - 핫딜 허브`;

    const priceLine = (o) => esc([useU && fin(o.u) ? `${unitWord()}당 ${wonU(o.u)}` : "", [qtyText(o), won(o.p)].filter(Boolean).join(" ")].filter(Boolean).join(" · "));
    const lowHtml = low
      ? `<b class="pbig">${priceLine(low)}</b><span class="psub">${esc(md(low.d))} ${esc(srcName(low.s))} · ${link(low, "원글")}</span>`
      : `<span class="psub">일반가 기록이 없어요${lowCond ? ` (조건부 최저 ${priceLine(lowCond)} · ${link(lowCond, "원글")})` : ""}</span>`;
    const condHtml = low && lowCond && val(lowCond) < val(low)
      ? `<div class="stat"><span class="sl">조건부 최저</span><span class="psub">${priceLine(lowCond)} (카드/멤버십 등) · ${esc(md(lowCond.d))} · ${link(lowCond, "원글")}</span></div>` : "";

    // 수량별 최저가: 개수(n) 또는 총 용량(g) 로 묶음. 일반가가 있으면 일반가 중 최저, 없으면 조건부 중 최저
    const kf = isWt() ? "g" : "n";
    const groups = new Map();
    for (const o of obs) {
      const k = o[kf];
      if (!(fin(k) && k > 0)) continue;
      const cur = groups.get(k);
      const better = !cur || (cur.c && !o.c) || (cur.c === o.c && (o.p ?? Infinity) < (cur.p ?? Infinity));
      if (better) groups.set(k, o);
    }
    const rows = [...groups.entries()].sort((a, b) => a[0] - b[0]).map(([, o]) => o);
    const plainU = rows.filter((o) => !o.c && fin(o.u)).map((o) => o.u);
    const bestU = plainU.length ? Math.min(...plainU) : null;
    const tiers = rows.length ? `<section class="pcard"><h2>${isWt() ? "용량별" : "수량별"} 최저가</h2><div class="tscroll"><table class="ptable"><thead><tr><th>${isWt() ? "용량" : "수량"}</th><th>가격</th><th>${P.basis ? esc(unitWord()) + "당" : "단가"}</th><th>날짜·원글</th></tr></thead><tbody>${rows.map((o) => {
      const top = bestU !== null && !o.c && o.u === bestU;
      return `<tr class="${[top && "best", o.c && "cond"].filter(Boolean).join(" ")}"><td>${esc(qtyText(o) || "-")}</td><td>${esc(won(o.p) || "-")}</td><td>${fin(o.u) ? esc(wonU(o.u)) + (top ? " 🏆" : "") : "-"}</td><td>${tags(o)} ${link(o, [md(o.d), srcName(o.s)].filter(Boolean).join(" ") || "원글")}</td></tr>`;
    }).join("")}</tbody></table></div></section>` : "";

    const posts = obs.slice().reverse().map((o) => `<li class="post${o.e ? " ended" : ""}">
        <div class="prow"><span class="pdate">${esc(fullDate(o.d))}</span><b class="pp">${esc(won(o.p) || "가격 모름")}</b>${unitText(o) ? `<span class="punit">${esc(unitText(o))}</span>` : ""}${qtyText(o) ? `<span>${esc(qtyText(o))}</span>` : ""}<span class="shop">${esc(srcName(o.s) || "출처 모름")}</span>${tags(o)}</div>
        <div class="ptitle">${link(o, o.t || "원글")}</div></li>`).join("");

    const basisNote = useU ? `${unitWord()}당 단가 기준${skipped ? ` · 단가를 알 수 없는 기록 ${skipped}건은 그래프에서 제외` : ""}` : "총 가격 기준";
    main.innerHTML = `
      <section class="pcard phead">
        <h2 class="pname">${esc(name)}</h2>
        <div class="prow">${P.cat ? `<span class="shop">${esc(P.cat)}</span>` : ""}<span>기록 ${obs.length.toLocaleString()}건 · ${esc(fullDate(obs[0].d))}부터</span></div>
        <div class="stats">
          <div class="stat"><span class="sl">역대 최저 <small>(조건부 제외)</small></span>${lowHtml}</div>
          ${condHtml}
          <div class="stat"><span class="sl">최근 가격</span><b class="pbig2">${priceLine(last)}</b><span class="psub">${esc(md(last.d))} ${esc(srcName(last.s))} ${tags(last)} · ${link(last, "원글")}</span></div>
        </div>
      </section>
      <section class="pcard"><h2>가격 추이</h2>
        <div id="chart" class="chartbox"></div>
        <p class="legend"><span class="lg dot"></span>일반가 <span class="lg hollow"></span>조건부 <span class="lg dot dim"></span>종료 · ${esc(basisNote)}</p>
      </section>
      ${tiers}
      <section class="pcard"><h2>과거 글 ${obs.length.toLocaleString()}건 <small>(최신순)</small></h2><ul class="posts">${posts}</ul></section>`;
    chart(points, low);
    let rt;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => chart(points, low), 120); });
  }

  async function load() {
    const id = new URLSearchParams(location.search).get("id");
    if (!id || !id.trim()) return fail("상품 id가 없어요. 메인 화면의 '가격 추이 보기' 링크로 들어와 주세요.");
    // 소스 이름은 deals.json 에서 (실패하면 내장 이름표)
    const names = fetch("data/deals.json").then((r) => (r.ok ? r.json() : null)).then((d) => {
      for (const s of Array.isArray(d?.sources) ? d.sources : []) if (s && typeof s.key === "string" && typeof s.name === "string") srcNames[s.key] = s.name;
    }).catch(() => {});
    let shard;
    try {
      const r = await fetch(`data/products/${shardOf(id)}.json`);
      if (r.status === 404) return fail("이 상품의 가격 기록을 찾지 못했어요. 기록이 정리됐거나 주소가 잘못됐을 수 있어요.");
      if (!r.ok) throw new Error(r.status);
      shard = await r.json();
    } catch {
      return fail("가격 기록을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.");
    }
    const p = shard && typeof shard === "object" && Object.prototype.hasOwnProperty.call(shard, id) ? shard[id] : null;
    if (!p || typeof p !== "object") return fail("이 상품의 가격 기록을 찾지 못했어요. 기록이 정리됐거나 주소가 잘못됐을 수 있어요.");
    P = p;
    await names;
    render(id);
  }
  load();
})();
