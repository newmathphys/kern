<script>
"use strict";
let mod = null, mem = null, cap = 0, ptr = 0;

const $ = (id) => document.getElementById(id);
const say = (el, text, cls) => { const e = $(el); e.textContent = text;
                                 e.className = cls || ""; };

async function sha256Hex(bytes) {
  const d = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, "0")).join("");
}

(async function boot() {
  try {
    const resp = await fetch("kernc.wasm", { cache: "no-store" });
    const bytes = new Uint8Array(await resp.arrayBuffer());
    const sha = await sha256Hex(bytes);
    const { instance } = await WebAssembly.instantiate(bytes, {});
    mod = instance.exports;
    mem = mod.memory;
    ptr = mod.kern_wasm_input_ptr();
    cap = mod.kern_wasm_input_cap();
    let manifest = null;
    try { manifest = await (await fetch("build.json", { cache: "no-store" })).json(); }
    catch (_) { /* манифеста нет — НАЗВАННОЕ состояние, не тишина */ }
    const same = !!manifest && manifest.sha256 === sha;
    $("verify").innerHTML =
      `sha256(исполняемых байт) = <code>${sha}</code><br>размер = ${bytes.length} байт · ` +
      `входной буфер = ${cap} байт<br>` +
      (manifest
        ? (same
            ? `<span class="ok">[OK] совпадает с манифестом сборки (коммит ${manifest.commit})</span>`
            : `<span class="bad">[FAIL] манифест ${manifest.sha256} ≠ посчитанный ${sha}</span>`)
        : `<span class="mut">манифест build.json не найден: сверка невозможна — считайте сами</span>`) +
      `<br><span class="mut">Независимая сверка: <code>zig build wasm &amp;&amp; ` +
      `sha256sum zig-out/bin/kernc.wasm</code></span>`;
    $("verify").className = "";
  } catch (e) {
    say("verify", "не удалось загрузить kernc.wasm: " + e.message, "bad");
  }
})();

const BEL = ["N", "T", "F", "B"];  // ИЗМЕРЕНО в ядре: t|(n<<1): N=0, T=1, F=2, B=3
function join(a, b) {
  const v = mod.kern_wasm_belnap_join(a, b);
  say("outA", `JOIN_K(${BEL[a]}, ${BEL[b]}) = ${BEL[v]}` +
      (v === 3 ? "  → 409 Conflict: оба утверждения сохранены" : ""), "ok");
}
function allow() {
  const t = mod.kern_wasm_belnap_allow(1), b = mod.kern_wasm_belnap_allow(3);
  say("outA", `allow(T) = ${t} · allow(B) = ${b}  ` +
      `(B не пропускается молча: конфликт обязан быть решён)`, "ok");
}
function hamming(code) {
  const v = mod.kern_wasm_admission_valid(BigInt(code));
  say("outB", `admission_valid(${code}) = ${v}`, "ok");
}
function lia(a1, b1, c1, a2, b2, c2) {
  const v = mod.kern_wasm_lia_unsat2(BigInt(a1), BigInt(b1), BigInt(c1),
                                     BigInt(a2), BigInt(b2), BigInt(c2));
  say("outC", `lia_unsat2(...) = ${v}` + (v ? "  → система несовместна" : "  → совместна"), "ok");
}
function verifyProof() {
  const text = new TextEncoder().encode($("proofIn").value);
  if (text.length > cap) {
    say("outD", `вход ${text.length} байт > буфера ${cap} — отказ ДО записи`, "bad");
    return;
  }
  new Uint8Array(mem.buffer, ptr, text.length).set(text);
  let cut = text.indexOf(10);
  if (cut < 0) cut = text.length;
  const v = mod.kern_wasm_verify_proof(ptr, cut, ptr + cut + 1,
                                       Math.max(0, text.length - cut - 1));
  say("outD", `verify_proof(${text.length} байт) = ${v}` +
      (v ? "  → сертификат принят" : "  → ОТКЛОНЁН (ядро не доверяет входу)"), v ? "ok" : "bad");
}
</script>
