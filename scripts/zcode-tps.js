/**
 * ZCode TPS Footer v1.2.0 —— 输入框工具栏统计胶囊（无常驻服务，多窗格独立渲染）
 * 每个会话窗格最近一轮: ● 时间 · 首 token Xs · X tok/s · out X（生成中实时刷新）
 *
 * 数据源: 页面内 MessagePort 会话事件流（preload 转交的 zcode:service-port）
 *   - conversation 行事件: turnHeader / userInput / reasoning / assistantText / row.delta(文本增量)
 *   - version:1 事件流: usage.delta(精确 usage，每次模型请求完成时发) / stream.chunk(首块+心跳)
 * 指标口径:
 *   - 流式中 tok/s 与 out 为估算(CJK 1 字≈1 token、其余 4 字符≈1 token)，4s 滑动窗口即时速度；
 *     usage.delta 到达后用精确值覆盖。轮结束后为精确值(精确 out ÷ 首块→末次 usage 解码窗口)。
 *   - 工具执行等静默期速度保持最近值；点停止/出错未报 usage 时 out 以内容估算兜底；
 *     同一 turnId 复用(编辑重发/重试)时自动清零旧统计。
 *
 * v1.2.0:
 *   - 段优先级（高→低）: tok/s > 首 token > out > 时间。宽度不足按 时间→out→首 token 丢弃，
 *     tok/s 永不丢；连「● tok/s」都放不下时该窗格整体隐藏。降级时 hover 显示完整 tooltip。
 *   - 多窗格独立渲染：按 composer 卡片逐窗格渲染，各窗格只统计本窗格会话
 *     （可见轮次 section 按其祖先 data-session-id 归属窗格）。多个独立窗口天然隔离
 *     （每窗口一份本脚本实例）。
 *   - MutationObserver 过滤自身 DOM 操作（胶囊/tooltip/量宽探针），杜绝自激重渲染循环。
 *
 * v1.1.0 宽度自适应（修复侧栏展开时的重叠/消失）:
 *   - 胶囊 position:fixed 悬浮（body 级），不插入工具栏 flex 流——工具栏左侧簇 flex-1+min-w-0，
 *     行变窄时内容右溢会压住流内元素。
 *   - 按工具栏行水平带内真实元素矩形计算空隙，胶囊居中悬浮其中；宽度恢复自动还原。
 *   - 会话归属改自「可见轮次/卡片的祖先 data-session-id」——侧栏等面板里也有更靠前的
 *     [data-session-id]，按文档序取第一个会误判。
 *   - 工具栏行定位按结构特征（含 mode-select-trigger 的 flex items-end 行），不依赖文案。
 */
(() => {
  if (window.__ztps) return;
  window.__ztps = true;
  const dec = new TextDecoder();
  const MARK = "data-ztps";
  const BAR = "data-ztps-bar";
  const TIP = "data-ztps-tip";
  const PROBE = "data-ztps-probe";
  const OURS_SEL = `[${BAR}],[${TIP}],[${PROBE}]`;
  const GAP_PAD = 10;       // 空隙两侧留白

  const turns = new Map();          // turnId(msg_xxx) -> 轮统计
  const firstChunkByScid = {};
  const rowTurn = new Map();        // rowId -> turnId（row.delta 增量归属）
  const respTurn = new Map();       // assistantResponseId -> turnId（stream.chunk 的 assistantMessageId 归属）
  const scidTurn = new Map();       // sourceCommandId -> turnId（usage.delta 关联兜底）

  const get = (id) => {
    if (!turns.has(id)) turns.set(id, {
      msgId: id, sourceCommandId: null, sessionId: null,
      startedAt: null, endedAt: null, activeMs: null,
      firstChunkAt: null, rowFirstAt: null, lastUsageAt: null,
      outputTokens: 0, inputTokens: 0, cacheReadTokens: 0, totalTokens: 0,
      textTok: 0, win: [], modelId: null, streaming: false,
    });
    return turns.get(id);
  };

  // 轮复用（编辑重发/重试复用同一 turnId）时清空上一轮统计，避免旧值残留到新轮
  function resetTurnStats(t) {
    t.endedAt = null; t.activeMs = null;
    t.firstChunkAt = null; t.rowFirstAt = null; t.lastUsageAt = null;
    t.outputTokens = 0; t.inputTokens = 0; t.cacheReadTokens = 0; t.totalTokens = 0;
    t.textTok = 0; t.win = []; t.lastTps = null; t.streaming = true;
  }

  // token 粗估：CJK 字符 1 字 ≈ 1 token，其余 4 字符 ≈ 1 token
  const estTok = (s) => {
    let n = 0;
    for (let i = 0; i < s.length; i++) n += s.charCodeAt(i) > 0x2e7f ? 1 : 0.25;
    return Math.round(n);
  };

  const pushWin = (t, ts, tok) => {
    t.win.push([ts, tok]);
    const floor = ts - 6000;
    while (t.win.length > 2 && t.win[0][0] < floor) t.win.shift();
  };

  function onRow(row) {
    if (!row) return;
    if (row.op === "row.delta") { onRowDelta(row); return; }
    if (!row.turnId) return;
    const t = get(row.turnId);
    if (row.rowId != null) rowTurn.set(row.rowId, row.turnId);
    if (row.kind === "turnHeader") {
      if ((t.endedAt != null || t.lastUsageAt != null) && row.startedAt && row.startedAt !== t.startedAt) resetTurnStats(t);
      t.startedAt = row.startedAt ?? t.startedAt;
      t.endedAt = row.endedAt ?? t.endedAt;
      t.activeMs = row.activeMs ?? t.activeMs;
      t.streaming = row.state != null && !/^(completedSuccess|completed|failed|stopped|cancelled)/.test(row.state);
      if (row.sourceCommandId) t.sourceCommandId = row.sourceCommandId;
      scan();
    } else if (row.kind === "userInput") {
      if ((t.endedAt != null || t.lastUsageAt != null) && row.createdAt && row.createdAt !== t.startedAt) resetTurnStats(t);
      t.startedAt = row.createdAt ?? t.startedAt;
      t.streaming = true;
      if (row.sourceCommandId) t.sourceCommandId = row.sourceCommandId;
      scan();
    } else if (row.kind === "reasoning" || row.kind === "assistantText") {
      if (row.assistantResponseId) respTurn.set(row.assistantResponseId, row.turnId);
      if (row.text && row.text.length) t.textTok = estTok(row.text);   // 全量覆盖，防增量累计漂移
      if (t.firstChunkAt == null && t.rowFirstAt == null && row.createdAt) {
        t.rowFirstAt = row.createdAt;   // 兜底首块（优先 stream.chunk）
      }
    }
  }

  function onRowDelta(row) {
    if (row.path !== "text" || !row.append) return;
    const turnId = rowTurn.get(row.rowId);
    if (!turnId) return;
    const t = turns.get(turnId);
    if (!t) return;
    t.textTok += estTok(row.append);
    pushWin(t, Date.now(), t.textTok);
  }

  function onEvent(ev) {
    if (!ev || ev.version !== 1) return;
    const scid = ev.sourceCommandId;
    if (ev.kind === "usage.delta") {
      if (!scid) return;
      const t = findByScid(scid) || turns.get(scidTurn.get(scid));
      if (!t) return;
      t.outputTokens += ev.outputTokens || 0;
      t.inputTokens += ev.inputTokens || 0;
      t.cacheReadTokens += ev.cacheReadTokens || 0;
      t.totalTokens += ev.totalTokens || 0;
      t.modelId = ev.modelId || t.modelId;
      t.sessionId = ev.sessionId || t.sessionId;
      t.lastUsageAt = ev.occurredAt ?? t.lastUsageAt;
      if (t.firstChunkAt == null && firstChunkByScid[scid] != null) {
        t.firstChunkAt = firstChunkByScid[scid];
      }
      scan();
    } else if (ev.kind === "stream.chunk") {
      if (firstChunkByScid[scid] == null) firstChunkByScid[scid] = ev.occurredAt;
      let t = findByScid(scid);
      if (!t && ev.assistantMessageId) {
        const tid = respTurn.get(ev.assistantMessageId);
        if (tid) { t = turns.get(tid); if (t && scid) scidTurn.set(scid, tid); }
      }
      if (!t && scid && scidTurn.has(scid)) t = turns.get(scidTurn.get(scid));
      if (!t) return;
      if (t.firstChunkAt == null) t.firstChunkAt = firstChunkByScid[scid];
      t.sessionId = ev.sessionId || t.sessionId;
      t.streaming = true;   // turnHeader 未到时也标记生成中
      pushWin(t, ev.occurredAt || Date.now(), t.textTok);   // 心跳采样，保证窗口时间轴连续
    }
  }

  const findByScid = (scid) => {
    for (const t of turns.values()) if (t.sourceCommandId === scid) return t;
    return null;
  };

  function handleFrame(data) {
    try {
      let d = data;
      if (d == null) return;
      if (d instanceof ArrayBuffer) d = new Uint8Array(d);
      if (!ArrayBuffer.isView(d)) return;
      const txt = dec.decode(d);
      const i = txt.indexOf("{");
      if (i < 0) return;
      const j = JSON.parse(txt.slice(i));
      if (j.version === 1) { onEvent(j); return; }
      const payload = j.frame && j.frame.payload;
      if (!payload) return;
      const evs = payload.events || payload.deltas || [];
      for (const e of evs) {
        if (e.row) onRow(e.row);
        else if (e.op === "row.appended" || e.op === "row.upserted" || e.op === "row.delta") onRow(e.row || e);
      }
    } catch (err) { /* 静默 */ }
  }

  // ---------- 格式化 ----------
  const fmtLat = (ms) => {
    const s = Math.max(0, (ms || 0) / 1000);
    return (s < 10 ? String(+s.toFixed(1)) : String(Math.round(s))) + "s";
  };
  const fmtTps = (v) => (v >= 10 ? String(Math.round(v)) : String(+Number(v || 0).toFixed(1)));
  const fmtTok = (v) => {
    if (v < 1e3) return String(v);
    const trim = (n) => String(+n.toFixed(n < 10 ? 1 : 0));
    if (v < 1e6) return trim(v / 1e3) + "k";
    if (v < 1e9) return trim(v / 1e6) + "m";
    return trim(v / 1e9) + "b";
  };
  const fmtStamp = (ms) => {
    if (ms == null) return null;
    const d = new Date(ms), now = new Date();
    const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    return d.toDateString() === now.toDateString() ? hm
      : d.getFullYear() === now.getFullYear() ? `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`
      : `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
  };

  function statsOf(t) {
    const firstAt = t.firstChunkAt ?? t.rowFirstAt ?? null;
    const ttft = firstAt != null && t.startedAt != null ? firstAt - t.startedAt : null;
    let out = t.outputTokens;
    if (out === 0 && t.textTok > 0) out = t.textTok;   // 中止/失败未报 usage：以内容估算兜底
    let tps = null;
    if (t.streaming) {
      out = Math.max(out, t.textTok);   // 流式中 usage 未到，用内容估算补齐（精确值到达后自然切换）
      const now = Date.now();
      const win = t.win.filter((w) => now - w[0] <= 4000);
      if (win.length >= 2) {
        const dt = (win[win.length - 1][0] - win[0][0]) / 1000;
        const dtok = win[win.length - 1][1] - win[0][1];
        if (dt >= 1 && dtok > 0) tps = dtok / dt;
      }
      if (tps == null && t.lastTps != null) tps = t.lastTps;   // 工具执行等静默期：保持最近速度
    } else {
      const decodeFrom = firstAt ?? t.startedAt;
      const decodeMs = decodeFrom != null && t.lastUsageAt != null ? t.lastUsageAt - decodeFrom : null;
      tps = t.outputTokens > 0 && decodeMs > 500 ? t.outputTokens / (decodeMs / 1000) : null;
      if (tps == null && t.lastTps != null) tps = t.lastTps;
    }
    if (tps != null) t.lastTps = tps;
    return {
      stamp: fmtStamp(t.endedAt || t.startedAt), ttft, tps, out,
      streaming: t.streaming,
    };
  }

  const hasActivity = (t) => t.streaming || t.textTok > 0 || t.outputTokens > 0;

  // ---------- 定位: 工具栏行（结构特征优先，文案兜底） ----------
  function findToolbarRow(card) {
    for (const el of card.querySelectorAll("div")) {
      const c = el.className || "";
      if (!/flex[^"]*items-end/.test(c)) continue;
      if (el.querySelector("[data-testid='chat-mode-select-trigger']")) return el;
    }
    for (const el of card.querySelectorAll("div")) {
      const c = el.className || "";
      if (/flex[^"]*items-end/.test(c) && (el.textContent || "").includes("完全访问")) return el;
    }
    return null;
  }

  // 卡片所属窗格的会话 id（沿祖先链找 data-session-id；侧栏/其它窗格的会话元素不在本链上）
  function paneSessionOf(card) {
    for (let a = card.parentElement; a; a = a.parentElement) {
      const sid = a.getAttribute && a.getAttribute("data-session-id");
      if (sid) return sid;
    }
    return null;
  }

  // ---------- 几何: 行水平带内障碍物之间的空隙 ----------
  // 返回 {cx, w}：空隙中心与可用宽度；无可用空隙返回 null。
  // 障碍物 = 卡片子树中与行水平带垂直相交的最内层元素（有带内子元素的容器视为包装盒跳过，
  // 避免左侧簇 flex-1 撑出的空白盒把可用空隙吃掉）。胶囊/tooltip 悬浮于 body 级，不在卡片子树内。
  function freeGap(card, row) {
    const rr = row.getBoundingClientRect();
    if (rr.width < 1) return null;
    const bandTop = rr.top, bandBot = rr.bottom;
    const inBand = (r) => r.height > 0 && r.bottom > bandTop + 1 && r.top < bandBot - 1;
    const cand = [];
    for (const el of card.querySelectorAll("*")) {
      const r = el.getBoundingClientRect();
      if (r.width < 2 || !inBand(r)) continue;
      cand.push({ el, r });
    }
    const iv = [];
    for (const { el, r } of cand) {
      const hasInner = cand.some((c2) => c2.el !== el && el.contains(c2.el));
      if (!hasInner) iv.push([r.left, r.right]);
    }
    if (!iv.length) return { cx: (rr.left + rr.right) / 2, w: rr.width };
    // 合并区间
    iv.sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const [l, r] of iv) {
      if (merged.length && l <= merged[merged.length - 1][1]) {
        if (r > merged[merged.length - 1][1]) merged[merged.length - 1][1] = r;
      } else merged.push([l, r]);
    }
    // 优先取包含行中心的空隙；中心被挡则取最大空隙
    const cx = (rr.left + rr.right) / 2;
    let lo = rr.left, hi = rr.right, blocked = false;
    for (const [l, r] of merged) {
      if (r <= cx) lo = Math.max(lo, r);
      else if (l >= cx) hi = Math.min(hi, l);
      else { blocked = true; break; }
    }
    if (!blocked && hi - lo > 0) return { cx: (lo + hi) / 2, w: hi - lo };
    let best = null;
    let prev = rr.left;
    for (const [l, r] of merged) {
      if (l - prev > 0 && (!best || l - prev > best.w)) best = { cx: (prev + l) / 2, w: l - prev };
      prev = Math.max(prev, r);
    }
    if (rr.right - prev > 0 && (!best || rr.right - prev > best.w)) best = { cx: (prev + rr.right) / 2, w: rr.right - prev };
    return best;
  }

  const ACCENT = "var(--color-warning, #e0983a)";
  const VALUE = "var(--color-foreground, #e8e8e8)";

  // ---------- 段构建（显示顺序: 时间 · 首 token · tok/s · out；p 为优先级键） ----------
  function buildSegs(s, full) {
    const span = (txt, cls) => {
      const sp = document.createElement("span");
      sp.textContent = txt;
      if (cls === "ACCENT") sp.style.color = ACCENT;
      else if (cls === "VALUE") sp.style.color = VALUE;
      return sp;
    };
    const segs = [];
    if (s.stamp != null) segs.push({ p: 0, nodes: [span(s.stamp)] });
    if (full && s.ttft != null && s.ttft >= 0) segs.push({ p: 1, nodes: [span("首 token "), span(fmtLat(s.ttft), "VALUE")] });
    if (full && s.tps != null) segs.push({ p: 2, nodes: [span(fmtTps(s.tps) + " tok/s", "ACCENT")] });
    if (full && s.out > 0) segs.push({ p: 3, nodes: [span("out "), span(fmtTok(s.out), "VALUE")] });
    return segs;
  }

  // ---------- 渲染: 逐窗格悬浮统计胶囊 ----------
  function renderAll() {
    try {
      // 1. 枚举全部 composer 卡片（每窗格一个；多窗口时各窗口独立实例）
      const cards = [];
      const seen = new Set();
      for (const ta of document.querySelectorAll("[data-testid='v4-composer-input']")) {
        const card = (ta.closest("form") ? ta.closest("form").parentElement : ta.parentElement) || null;
        if (card && !seen.has(card)) { seen.add(card); cards.push(card); }
      }
      // 2. 可见轮次按「祖先 data-session-id」分窗格归属
      const secsBySess = new Map();   // sessId|null -> Set<turnId>
      for (const sec of document.querySelectorAll("section[data-turn-id]")) {
        if (sec.offsetParent == null) continue;
        let s = null;
        for (let a = sec.parentElement; a; a = a.parentElement) {
          const sid = a.getAttribute && a.getAttribute("data-session-id");
          if (sid) { s = sid; break; }
        }
        if (!secsBySess.has(s)) secsBySess.set(s, new Set());
        secsBySess.get(s).add(sec.getAttribute("data-turn-id"));
      }
      // 3. 逐窗格渲染
      const liveKeys = new Set();
      for (const card of cards) {
        try { renderPane(card, cards, secsBySess, liveKeys); } catch (err) { /* 静默 */ }
      }
      // 4. 清理不再归属任何窗格的胶囊与 tooltip
      document.querySelectorAll(`[${BAR}]`).forEach((el) => {
        if (!liveKeys.has(el.getAttribute("data-ztps-pane"))) {
          const tip = document.querySelector(`[${TIP}]`);
          if (tip && tip._zhost === el) tip.remove();
          el.remove();
        }
      });
      document.querySelectorAll(`[${TIP}]`).forEach((t) => {
        if (!t._zhost || !t._zhost.isConnected) t.remove();
      });
    } catch (err) { /* 静默 */ }
  }

  function positionHost(host, gap, rr, allowed) {
    const w = Math.min(host._zw || allowed, allowed);
    host.style.width = w + "px";
    const cy = rr.top + rr.height / 2;
    host.style.left = Math.round(gap.cx - w / 2) + "px";
    host.style.top = Math.round(cy - 11) + "px";
  }

  function renderPane(card, cards, secsBySess, liveKeys) {
    const paneSess = paneSessionOf(card);
    const paneKey = paneSess != null ? "s:" + paneSess : "c:" + cards.indexOf(card);
    let host = document.querySelector(`[${BAR}][data-ztps-pane="${paneKey}"]`);
    const row = findToolbarRow(card);
    if (!row) { if (host) host.remove(); return; }

    // 本窗格的候选轮次（DOM 分组；单窗格无会话标记时兜底全量可见轮次）
    let cand = secsBySess.get(paneSess) || null;
    if (!cand && paneSess == null && cards.length === 1) {
      cand = new Set();
      for (const s of secsBySess.values()) for (const id of s) cand.add(id);
    }
    let latest = null;
    if (cand) for (const t of turns.values()) {
      if (!cand.has(t.msgId)) continue;
      if (t.sessionId && paneSess && t.sessionId !== paneSess) continue;   // 会话切换 DOM 中间态兜底
      if (!latest || (t.startedAt ?? 0) > (latest.startedAt ?? 0)) latest = t;
    }
    if (!latest || (!hasActivity(latest) && latest.endedAt == null && latest.startedAt == null)) {
      if (host) host.remove();
      return;
    }

    const gap = freeGap(card, row);
    const rr = row.getBoundingClientRect();
    const allowed = gap ? Math.max(0, gap.w - GAP_PAD) : 0;
    const s = statsOf(latest);

    // 数据与可用宽度均未变化：跳过量宽/重建，仅跟随定位（行/窗格可能移动）
    const key = [s.stamp, s.ttft, s.tps, s.out, s.streaming, Math.round(allowed)].join("|");
    if (host && host._zkey === key) {
      positionHost(host, gap, rr, allowed);
      positionTip(host);
      liveKeys.add(paneKey);
      return;
    }

    // 离线探针量宽 + 降级：优先级 tok/s(2) > 首 token(1) > out(3) > 时间(0)，
    // 低优先级先丢（时间→out→首 token），tok/s 永不丢；只剩 ●+tok/s 仍放不下则整体隐藏
    const segs = buildSegs(s, true);
    const probe = document.createElement("div");
    probe.setAttribute(PROBE, "1");
    Object.assign(probe.style, {
      display: "inline-flex", alignItems: "center", gap: "6px",
      position: "fixed", left: "-9999px", top: "0", visibility: "hidden",
      fontSize: "11px", height: "22px", whiteSpace: "nowrap",
      fontVariantNumeric: "tabular-nums", padding: "0 10px",
    });
    const dot = document.createElement("span");
    dot.textContent = "●";
    probe.appendChild(dot);
    segs.forEach((g) => g.nodes.forEach((n) => probe.appendChild(n)));
    document.body.appendChild(probe);
    let fullW = 0;
    try {
      fullW = probe.getBoundingClientRect().width;
      for (const p of [0, 3, 1]) {
        if (fullW <= allowed) break;
        const g = segs.find((x) => x.p === p);
        if (!g) continue;
        g.nodes.forEach((n) => n.remove());
        fullW = probe.getBoundingClientRect().width;
      }
    } finally {
      probe.remove();
    }
    if (!gap || fullW > allowed) {
      if (host) host.remove();
      return;
    }
    const dropped = segs.filter((x) => x.nodes[0].parentNode == null).map((x) => x.p);

    if (!host) {
      host = document.createElement("div");
      host.setAttribute(BAR, "1");
      host.setAttribute("data-ztps-pane", paneKey);
      Object.assign(host.style, {
        display: "inline-flex", alignItems: "center", gap: "6px",
        position: "fixed", left: "0", top: "0", zIndex: "60",
        minWidth: "0",
        fontSize: "11px", height: "22px", userSelect: "none",
        fontVariantNumeric: "tabular-nums",
        whiteSpace: "nowrap", overflow: "hidden",
        borderRadius: "999px",
        background: "rgba(127,127,127,0.12)",
        padding: "0 10px",
        color: "var(--color-foreground-subtle, #7a7a7a)",
      });
      document.body.appendChild(host);
      hookHostEvents(host);
    }

    host._zstats = s;
    host._zdropped = dropped;
    host._zkey = key;
    host._zw = fullW;
    host.innerHTML = "";
    const dot2 = document.createElement("span");
    dot2.textContent = "●";
    dot2.style.color = "#4ade80";
    if (s.streaming) dot2.style.textShadow = "0 0 6px rgba(74,222,128,.8)";
    host.appendChild(dot2);
    // 只挂载幸存段（探针中已摘除的段 parentNode 为 null），段间插分隔符
    const alive = segs.filter((g) => g.nodes[0].parentNode != null);
    alive.forEach((g, i) => {
      if (i > 0) {
        const sep = document.createElement("span");
        sep.textContent = "·";
        sep.style.opacity = "0.55";
        host.appendChild(sep);
      }
      g.nodes.forEach((n) => host.appendChild(n));
    });
    positionHost(host, gap, rr, allowed);
    positionTip(host);
    liveKeys.add(paneKey);
  }

  // ---------- hover tooltip: 降级时显示完整指标 ----------
  function hideTip() {
    const t = document.querySelector(`[${TIP}]`);
    if (t) t.remove();
  }
  function positionTip(host) {
    const tip = document.querySelector(`[${TIP}]`);
    if (!tip || !host || tip._zhost !== host) return;
    const hr = host.getBoundingClientRect();
    tip.style.left = Math.round(hr.left + hr.width / 2) + "px";
    tip.style.top = Math.round(hr.top - 8) + "px";
  }
  function showTip(host) {
    try {
      if (!host._zdropped || !host._zdropped.length || !host._zstats) return;
      hideTip();
      const tip = document.createElement("div");
      tip.setAttribute(TIP, "1");
      tip._zhost = host;
      Object.assign(tip.style, {
        position: "fixed", transform: "translate(-50%, -100%)", zIndex: "2147483000",
        display: "inline-flex", alignItems: "center", gap: "6px",
        fontSize: "11px", height: "24px", whiteSpace: "nowrap",
        fontVariantNumeric: "tabular-nums",
        borderRadius: "8px", padding: "0 10px",
        background: "rgba(40,40,40,0.96)",
        border: "1px solid rgba(255,255,255,0.12)",
        boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
        color: "var(--color-foreground-subtle, #9a9a9a)",
        pointerEvents: "none",
      });
      const dot = document.createElement("span");
      dot.textContent = "●";
      dot.style.color = "#4ade80";
      if (host._zstats.streaming) dot.style.textShadow = "0 0 6px rgba(74,222,128,.8)";
      tip.appendChild(dot);
      buildSegs(host._zstats, true).forEach((g, i) => {
        if (i > 0) {
          const sep = document.createElement("span");
          sep.textContent = "·";
          sep.style.opacity = "0.55";
          tip.appendChild(sep);
        }
        g.nodes.forEach((n) => tip.appendChild(n));
      });
      document.body.appendChild(tip);
      positionTip(host);
    } catch (err) { /* 静默 */ }
  }
  function hookHostEvents(host) {
    host.addEventListener("mouseenter", () => showTip(host));
    host.addEventListener("mouseleave", hideTip);
  }

  // ---------- 清理历史遗留的逐轮统计行（统计只在工具栏展示） ----------
  function removeLegacyFooters() {
    try {
      document.querySelectorAll(`[${MARK}]:not([${BAR}]):not([${TIP}]):not([${PROBE}])`).forEach((el) => el.remove());
    } catch (err) { /* 静默 */ }
  }

  function scan() {
    renderAll();
    removeLegacyFooters();
  }

  // 自身 DOM 操作（胶囊/tooltip/探针的增删改）不算应用变化，不触发重渲染——防自激循环
  function ourMutation(rec) {
    const t = rec.target;
    if (t === document.body || t === document.documentElement) {
      let all = true;
      for (const n of rec.addedNodes) if (!(n.nodeType === 1 && n.matches && n.matches(OURS_SEL))) all = false;
      for (const n of rec.removedNodes) if (!(n.nodeType === 1 && n.matches && n.matches(OURS_SEL))) all = false;
      return all && (rec.addedNodes.length + rec.removedNodes.length) > 0;
    }
    return !!(t.closest && t.closest(OURS_SEL));
  }

  function start() {
    setInterval(scan, 1000);   // 流式估算 1s 刷新节奏 + 悬浮位置跟踪
    window.addEventListener("resize", scan);
    try {
      let lastSync = 0;
      const mo = new MutationObserver((recs) => {
        if (recs && recs.length && recs.every(ourMutation)) return;
        // DOM 一变立即同步刷新，切换会话零残留；16ms 节流防回放风暴
        const now = performance.now();
        if (now - lastSync > 16) { lastSync = now; renderAll(); }
        clearTimeout(mo._t);
        mo._t = setTimeout(scan, 60);
      });
      mo.observe(document.body, { childList: true, subtree: true });
    } catch (err) { /* 静默 */ }
    scan();
  }
  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start);

  // ---------- 端口获取 ----------
  function hookPort(port) {
    if (!port || port.__ztps) return;
    port.__ztps = true;
    port.addEventListener("message", (ev) => handleFrame(ev.data));
    port.start();
    window.__ztpsPort = port;   // 调试用：暴露端口供旁路监听原始帧
  }
  window.addEventListener("message", (e) => {
    if (e.source !== window) return;
    const d = e.data;
    if (d === "zcode:service-port" || (d && d.type === "zcode:scoped-service-port")) {
      if (e.ports && e.ports[0]) hookPort(e.ports[0]);
    }
  }, true);

  window.__ztpsTurns = turns;
  window.__ztpsHook = hookPort;   // 调试用：热注入时可对存量端口手动补挂
})();
