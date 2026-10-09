// 新标签页看板：壁纸 + 搜索 + 快捷方式 + 毛玻璃积分面板
const API = "http://127.0.0.1:17173";
const $ = (id) => document.getElementById(id);

/* ---------- 时钟 ---------- */
function tickClock() {
  const n = new Date();
  $("clockTime").textContent =
    n.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  $("clockDate").textContent =
    n.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
}
setInterval(tickClock, 1000);
tickClock();

/* ---------- 小工具 ---------- */
async function jget(path, opt) {
  const r = await fetch(API + path, opt);
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
function setBar(id, done, total) {
  const el = $(id);
  if (!el) return;
  const pct = total ? Math.max(0, Math.min(100, Math.round((done / total) * 100))) : 0;
  el.style.width = pct + "%";
}

/* ---------- 壁纸 ---------- */
async function loadWallpaper() {
  try {
    const w = await jget("/api/wallpaper");
    if (!w || !w.url) return;
    const img = new Image();
    img.onload = () => {
      const bg = $("bg");
      bg.style.backgroundImage = 'url("' + w.url + '")';
      bg.classList.add("on");
    };
    img.src = w.url;
  } catch (e) { /* 失败时保持纯色背景 */ }
}

/* ---------- 快捷方式 ---------- */
function shortName(t) {
  let s = String(t || "").trim();
  const i = s.search(/[-\u2013\u2014|\u00b7]/);
  if (i > 0) s = s.slice(0, i).trim();
  return s.length > 12 ? s.slice(0, 12) : s;
}
function faviconFor(u) {
  try { return "https://" + new URL(u).hostname + "/favicon.ico"; }
  catch (e) { return null; }
}
async function loadLinks() {
  let items = [];
  try { items = await jget("/api/quicklinks"); } catch (e) { items = []; }
  if (!Array.isArray(items) || !items.length) {
    items = [
      { title: "积分看板", url: "http://127.0.0.1:17173/" },
      { title: "哔哩哔哩", url: "https://www.bilibili.com/" },
      { title: "GitHub", url: "https://github.com/" },
    ];
  }
  const box = $("links");
  box.textContent = "";
  for (const it of items.slice(0, 12)) {
    const a = document.createElement("a");
    a.className = "link";
    a.href = it.url;
    a.title = it.title || it.url;
    const tile = document.createElement("span");
    tile.className = "tile";
    const f = faviconFor(it.url);
    if (f) {
      const img = document.createElement("img");
      img.alt = "";
      img.src = f;
      img.addEventListener("error", () => {
        img.remove();
        tile.classList.add("char");
        tile.textContent = (it.title || "?").trim().charAt(0).toUpperCase();
      });
      tile.appendChild(img);
    } else {
      tile.classList.add("char");
      tile.textContent = (it.title || "?").trim().charAt(0).toUpperCase();
    }
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = shortName(it.title || it.url);
    a.appendChild(tile);
    a.appendChild(label);
    box.appendChild(a);
  }
}

/* ---------- 搜索 ---------- */
$("searchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("q").value.trim();
  if (q) location.href = "https://cn.bing.com/search?q=" + encodeURIComponent(q);
});
$("q").focus();

/* ---------- 看板数据 ---------- */
function tidyNext(s) {
  const m = /(\d+)\/(\d+)\/(\d+)\s+(\d+):(\d+)/.exec(s || "");
  if (!m) return s || "";
  return m[1] + "-" + m[2] + " " + m[4] + ":" + m[5];
}

async function loadState() {
  let d = null;
  try { d = await jget("/api/state?src=ext&v=2.1"); } catch (e) { d = null; }
  if (!d) {
    $("vStatus").innerHTML = '<span class="dot red"></span>看板服务未连接';
    return;
  }
  const ts = d.today_stats || {};
  $("vBalance").textContent = d.balance == null ? "—" : Number(d.balance).toLocaleString("zh-CN");
  $("vDelta").textContent = "今日 +" + (ts.delta ?? 0) + " 分";

  const dl = (d.progress && d.progress.dailyset) || (d.live && d.live.dailyset) || {};
  $("vDaily").textContent = (dl.done ?? "—") + "/" + (dl.total ?? 3);
  setBar("barDaily", dl.done || 0, dl.total || 3);

  const sdone = ts.searches ?? 0;
  const stotal = d.search_target ?? 6;
  $("vSearch").textContent = sdone + "/" + stotal;
  setBar("barSearch", sdone, stotal);

  const pend = (d.progress && d.progress.pending) ?? (d.live && d.live.pending) ?? 0;
  $("vPending").textContent = Number(pend).toLocaleString("zh-CN");
  $("vPendingSub").textContent = pend > 0 ? "已检测到待领取, 运行即领" : "自动补领已开启";

  const sys = d.system || {};
  const tasks = sys.tasks || [];
  const next = tasks.length ? tidyNext(tasks[0].next) : "";
  const bits = [sys.watcher ? "看守运行中" : "看守未运行"];
  if (sys.bot_running) bits.push("任务执行中");
  if (next) bits.push("下次 " + next);
  const ok = !!sys.watcher;
  $("vStatus").innerHTML =
    '<span class="dot ' + (ok ? "" : "red") + '"></span>' + bits.join(" · ");
}

/* ---------- 立即运行 ---------- */
$("btnRun").addEventListener("click", async () => {
  const b = $("btnRun");
  b.disabled = true;
  b.textContent = "触发中…";
  try {
    const r = await jget("/api/run", { method: "POST" });
    setTimeout(loadState, 1200);
    alert(r.msg || (r.ok ? "已触发" : "触发失败"));
  } catch (e) {
    alert("触发失败：" + e);
  }
  b.disabled = false;
  b.textContent = "立即运行";
});

/* ---------- 天气 ---------- */
async function loadWeather() {
  try {
    const w = await jget("/api/weather");
    if (!w || w.temp == null) return;
    $("weather").textContent =
      (w.name ? w.name + " " : "") + (w.icon || "") + Math.round(w.temp) + "\u00b0";
  } catch (e) { /* 离线时保持空 */ }
}

/* ---------- 启动 ---------- */
loadWallpaper();
loadLinks();
loadState();
loadWeather();
setInterval(loadState, 30000);
setInterval(loadWeather, 30 * 60 * 1000);
