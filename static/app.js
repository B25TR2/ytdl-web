const $ = id => document.getElementById(id);
let pollTimer = null, clipN = 0;

fetch("/api/health").then(r => r.json()).then(h => {
  const el = $("health");
  if (h.ffmpeg) { el.textContent = "✅ ffmpeg siap • yt-dlp siap"; el.classList.add("ok"); }
  else el.textContent = "⚠️ ffmpeg TIDAK ditemukan — install dulu (lihat README).";
}).catch(() => { $("health").textContent = "⚠️ Server tidak merespons."; });

function showErr(id, msg) {
  const el = $(id);
  el.textContent = msg; el.classList.remove("hidden");
}

$("btn-info").onclick = async () => {
  const url = $("url").value.trim();
  showErr("info-err", "");
  $("info-err").classList.add("hidden");
  if (!url) return showErr("info-err", "Tempel dulu link videonya.");
  $("btn-info").disabled = true;
  try {
    const r = await fetch("/api/info", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url})
    });
    const d = await r.json();
    if (!d.ok) return showErr("info-err", d.error || "Gagal.");
    $("v-thumb").src = d.video.thumbnail || "";
    $("v-title").textContent = d.video.title || "(tanpa judul)";
    $("v-meta").textContent =
      `${d.video.uploader || ""} • durasi ${d.video.duration_str}`;
    $("video-card").classList.remove("hidden");
    $("step2").classList.remove("hidden");
    if (clipN === 0) addClip();
  } catch (e) {
    showErr("info-err", "Server tidak merespons. Coba lagi.");
  }
  $("btn-info").disabled = false;
};

document.querySelectorAll('input[name=mode]').forEach(r =>
  r.addEventListener("change", () =>
    $("clips-box").classList.toggle("hidden",
      document.querySelector('input[name=mode]:checked').value !== "clips")));

function addClip() {
  clipN++;
  const row = document.createElement("div");
  row.className = "clip-row";
  row.innerHTML =
    `<span class="n">Klip ${clipN}</span>
     <input type="text" placeholder="awal  cth: 1:30" data-k="start">
     <span>–</span>
     <input type="text" placeholder="akhir cth: 2:10" data-k="end">
     <button class="x" title="hapus">✕</button>`;
  row.querySelector(".x").onclick = () => row.remove();
  $("clips").appendChild(row);
}
$("btn-add-clip").onclick = addClip;

$("btn-dl").onclick = async () => {
  const url = $("url").value.trim();
  const mode = document.querySelector('input[name=mode]:checked').value;
  const quality = $("quality").value;
  $("dl-err").classList.add("hidden");
  let clips = [];
  if (mode === "clips") {
    document.querySelectorAll(".clip-row").forEach(row => {
      const s = row.querySelector('[data-k=start]').value.trim();
      const e = row.querySelector('[data-k=end]').value.trim();
      if (s || e) clips.push({start: s, end: e});
    });
    if (!clips.length) return showErr("dl-err", "Isi dulu minimal 1 klip (waktu awal & akhir).");
  }
  $("btn-dl").disabled = true;
  try {
    const r = await fetch("/api/download", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({url, mode, quality, clips})
    });
    const d = await r.json();
    if (!d.ok) { showErr("dl-err", d.error || "Gagal."); $("btn-dl").disabled = false; return; }
    $("progress-card").classList.remove("hidden");
    $("result-card").classList.add("hidden");
    $("p-err").classList.add("hidden");
    poll(d.job_id);
  } catch (e) {
    showErr("dl-err", "Server tidak merespons.");
    $("btn-dl").disabled = false;
  }
};

function poll(jobId) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const r = await fetch(`/api/status/${jobId}`);
    const d = await r.json();
    if (!d.ok) return;
    const j = d.job;
    $("bar-fill").style.width = `${j.progress || 0}%`;
    $("p-note").textContent = `${j.note || ""} (${(j.progress || 0).toFixed(0)}%)`;
    if (j.status === "done") {
      clearInterval(pollTimer);
      $("btn-dl").disabled = false;
      const box = $("files"); box.innerHTML = "";
      j.files.forEach(f => {
        const div = document.createElement("div");
        div.className = "file";
        div.innerHTML =
          `<div><div class="fn">${f.name}</div><div class="fs">${f.size}</div></div>
           <a href="/api/file/${jobId}/${encodeURIComponent(f.name)}">Download</a>`;
        box.appendChild(div);
      });
      $("result-card").classList.remove("hidden");
      $("progress-card").classList.add("hidden");
    } else if (j.status === "error") {
      clearInterval(pollTimer);
      $("btn-dl").disabled = false;
      showErr("p-err", j.error || "Download gagal.");
    }
  }, 1000);
}
