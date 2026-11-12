"use strict";
// ДВУЯЗЫЧИЕ: английский — ЯЗЫК ПО УМОЛЧАНИЮ (аудитория HN), русский по navigator.language
// или по кнопке. Переключение без перезагрузки; выбор запоминается в localStorage.
const I18N = {
  en: {
    "h1": "KERN playground",
    "intro": "The real kernel in WebAssembly: <code>wasm32-freestanding</code>, no WASI, no syscalls, a 4 MB static arena. Everything runs <b>in your browser</b>, offline.",
    "v.h": "Verify the binary (do not trust the label — compute it)",
    "a.h": "1. Belnap logic: a conflict does not collapse",
    "a.p": "Allow (T) ⊔ Deny (F) = B — “yes and no” (HTTP 409), not “deny wins”.",
    "a.allow": "admission via B",
    "b.h": "2. Hamming code: admission with error correction",
    "b.p": "A 64-bit <code>AdmissionCode</code>; flip bits and watch the verdict hold.",
    "c.h": "3. Fourier–Motzkin solver: two linear systems",
    "c.p": "Are <code>a1·x ≤ b1·y + c1</code> and <code>a2·x ≤ b2·y + c2</code> jointly satisfiable? The kernel decides, not JS.",
    "c.b1": "x≤0 and x≤-1 (jointly)",
    "c.b2": "x≤0 and -x≤-1 (empty)",
    "d.h": "4. <code>verifyProof</code>: re-checking a Z3 certificate in memory",
    "d.p": "Bytes go into a <b>separate input buffer</b> (<code>kern_wasm_input_ptr</code> / <code>kern_wasm_input_cap</code>) so the arena allocator cannot overwrite the input during verification. Reference: <code>abs.c</code>, 16 proof-DAG steps, captured from a live Z3 run.",
    "d.b1": "Load reference certificate → ACCEPTED (1)",
    "d.b2": "Sabotage one byte in the proof → REJECTED (0)"
  },
  ru: {
    "h1": "KERN playground",
    "intro": "Настоящее ядро в WebAssembly: <code>wasm32-freestanding</code>, без WASI, без сисколлов, статическая арена 4 МБ. Всё считается <b>в вашем браузере</b>, офлайн.",
    "v.h": "Сверка бинарника (не верьте подписи — посчитайте сами)",
    "a.h": "1. Логика Белнапа: конфликт не схлопывается",
    "a.p": "Разрешение (T) ⊔ запрет (F) = B — «и да, и нет» (HTTP 409), а не «deny побеждает».",
    "a.allow": "допуск по B",
    "b.h": "2. Код Хэмминга: допуск с исправлением ошибки",
    "b.p": "64-битный <code>AdmissionCode</code>; меняйте биты и смотрите, что вердикт держится.",
    "c.h": "3. Решатель Фурье–Моцкина: две линейные системы",
    "c.p": "Совместны ли <code>a1·x ≤ b1·y + c1</code> и <code>a2·x ≤ b2·y + c2</code>? Решает ядро, не JS.",
    "c.b1": "x≤0 и x≤-1 (совместно)",
    "c.b2": "x≤0 и -x≤-1 (пусто)",
    "d.h": "4. <code>verifyProof</code>: перепроверка Z3-сертификата в памяти",
    "d.p": "Байты кладутся в <b>отдельный входной буфер</b> (<code>kern_wasm_input_ptr</code> / <code>kern_wasm_input_cap</code>), чтобы аллокатор арены не затёр вход во время проверки. Эталон: <code>abs.c</code>, 16 шагов proof-DAG, снят с живого Z3.",
    "d.b1": "Загрузить эталонный сертификат → ПРИНЯТ (1)",
    "d.b2": "Подделать 1 байт в доказательстве → ОТКЛОНЁН (0)"
  }
};
const MSG = {
  en: {
    loading: "Loading", notFound: "build.json manifest not found: cannot compare — compute it yourself",
    match: "matches the build manifest (commit", mismatch: "manifest", differs: "≠ computed",
    independent: "Independent check:", same: "Same results", accepted: "ACCEPTED: trusted: 0, `false` concluded",
    rejected: "REJECTED (the kernel does not trust the input)", conflict: "409 Conflict: both statements kept",
    notPassed: "B is not silently admitted: a conflict must be resolved", unsat: "the system is unsatisfiable",
    sat: "jointly satisfiable", noSample: "cannot read the reference: ", over: "input exceeds buffer",
    refuse: "— refuse BEFORE writing", admitB: "allow(T)=", allowB: "allow(B)="
  },
  ru: {
    loading: "Загружаю", notFound: "манифест build.json не найден: сверка невозможна — считайте сами",
    match: "совпадает с манифестом сборки (коммит", mismatch: "манифест", differs: "≠ посчитанный",
    independent: "Независимая сверка:", same: "", accepted: "ПРИНЯТ: trusted: 0, вывод `false` подтверждён",
    rejected: "ОТКЛОНЁН (ядро не доверяет входу)", conflict: "409 Conflict: оба утверждения сохранены",
    notPassed: "B не пропускается молча: конфликт обязан быть решён", unsat: "система несовместна",
    sat: "совместна", noSample: "не удалось прочитать эталон: ", over: "вход больше буфера",
    refuse: "— отказ ДО записи", admitB: "allow(T)=", allowB: "allow(B)="
  }
};
let LANG = "en";
let mod = null, ptr = 0, cap = 0;
const $ = (id) => document.getElementById(id);
const M = (k) => (MSG[LANG] && MSG[LANG][k]) || MSG.en[k] || k;

function setLang(lang) {
  LANG = I18N[lang] ? lang : "en";
  document.documentElement.lang = LANG;
  for (const el of document.querySelectorAll("[data-i18n]")) {
    const key = el.getAttribute("data-i18n");
    const txt = I18N[LANG][key];
    if (txt) el.innerHTML = txt;
  }
  $("btnEn").setAttribute("aria-pressed", String(LANG === "en"));
  $("btnRu").setAttribute("aria-pressed", String(LANG === "ru"));
  try { localStorage.setItem("kern.playground.lang", LANG); } catch (_) { /* приватный режим */ }
}
const say = (el, text, cls) => { const e = $(el); e.textContent = text; e.className = cls || ""; };

async function sha256Hex(bytes) {
  const d = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}


(async function boot() {
  // Язык: сохранённый выбор -> navigator.language (ru*), иначе EN.
  let saved = null;
  try { saved = localStorage.getItem("kern.playground.lang"); } catch (_) {}
  setLang(saved || ((navigator.language || "en").toLowerCase().startsWith("ru") ? "ru" : "en"));
  try {
    const resp = await fetch("kernc.wasm", { cache: "no-store" });
    const bytes = new Uint8Array(await resp.arrayBuffer());
    const sha = await sha256Hex(bytes);
    const { instance } = await WebAssembly.instantiate(bytes, {});
    mod = instance.exports;
    ptr = mod.kern_wasm_input_ptr();
    cap = mod.kern_wasm_input_cap();
    let manifest = null;
    try { manifest = await (await fetch("build.json", { cache: "no-store" })).json(); }
    catch (_) { /* манифеста нет — НАЗВАННОЕ состояние, не тишина */ }
    const same = !!manifest && manifest.sha256 === sha;
    $("verify").innerHTML =
      `sha256(bytes executed) = <code>${sha}</code><br>size = ${bytes.length} B · ` +
      `input buffer = ${cap} B<br>` +
      (manifest
        ? (same
            ? `<span class="ok">[OK] ${M("match")} ${manifest.commit})</span>`
            : `<span class="bad">[FAIL] ${M("mismatch")} ${manifest.sha256} ${M("differs")} ${sha}</span>`)
        : `<span class="mut">${M("notFound")}</span>`) +
      `<br><span class="mut">${M("independent")} <code>zig build wasm &amp;&amp; ` +
      `sha256sum zig-out/bin/kernc.wasm</code></span>`;
    $("verify").className = "";
  } catch (e) {
    say("verify", M("noSample") + e.message, "bad");
  }
})();

const BEL = ["N", "T", "F", "B"];  // ИЗМЕРЕНО в ядре: t|(n<<1): N=0, T=1, F=2, B=3
function join(a, b) {
  const v = mod.kern_wasm_belnap_join(a, b);
  say("outA", `JOIN_K(${BEL[a]}, ${BEL[b]}) = ${BEL[v]}` + (v === 3 ? `  → ${M("conflict")}` : ""), "ok");
}
function allow() {
  const t = mod.kern_wasm_belnap_allow(1), b = mod.kern_wasm_belnap_allow(3);
  say("outA", `${M("admitB")}${t} · ${M("allowB")}${b}  (${M("notPassed")})`, "ok");
}
function hamming(code) {
  say("outB", `admission_valid(${code}) = ${mod.kern_wasm_admission_valid(BigInt(code))}`, "ok");
}
function lia(a1, b1, c1, a2, b2, c2) {
  const v = mod.kern_wasm_lia_unsat2(BigInt(a1), BigInt(b1), BigInt(c1),
                                     BigInt(a2), BigInt(b2), BigInt(c2));
  say("outC", `lia_unsat2(...) = ${v}  → ${v ? M("unsat") : M("sat")}`, "ok");
}

// ВАЖНО: представление памяти создаём ЗАНОВО перед каждой записью — модуль растит
// память, и ранее созданный Uint8Array становится detached (поймано в Node-прогоне).
function writeInput(smtBytes, proofBytes) {
  const view = new Uint8Array(mod.memory.buffer);
  view.set(smtBytes, ptr);
  view.set(proofBytes, ptr + smtBytes.length);
  return [smtBytes.length, proofBytes.length];
}

async function loadSample(sabotage) {
  try {
    const [smtBuf, proofBuf] = await Promise.all([
      fetch("sample.smt2", { cache: "no-store" }).then(r => r.arrayBuffer()),
      fetch("sample.proof", { cache: "no-store" }).then(r => r.arrayBuffer()),
    ]);
    const smtBytes = new Uint8Array(smtBuf);
    let proofBytes = new Uint8Array(proofBuf);
    if (sabotage) {
      proofBytes = proofBytes.slice();                    // копия: не портим кэш
      const i = proofBytes.length >> 1;
      proofBytes[i] = proofBytes[i] === 0x29 ? 0x28 : 0x29;
    }
    if (smtBytes.length + proofBytes.length > cap) {
      say("outD", `${M("over")} ${smtBytes.length + proofBytes.length} > ${cap} ${M("refuse")}`, "bad");
      return;
    }
    $("smtView").textContent = new TextDecoder().decode(smtBytes).trim();
    const [sl, pl] = writeInput(smtBytes, proofBytes);
    const v = mod.kern_wasm_verify_proof(ptr, sl, ptr + sl, pl);
    say("outD", `verify_proof(smt=${sl} B, proof=${pl} B${sabotage ? ", 1 byte sabotaged" : ""}) = ${v}` +
        `  → ${v ? M("accepted") : M("rejected")}`, v ? "ok" : "bad");
  } catch (e) {
    say("outD", M("noSample") + e.message, "bad");
  }
}
