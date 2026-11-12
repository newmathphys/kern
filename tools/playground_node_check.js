const fs = require("fs");
const path = require("path");

const dir = path.join(__dirname, "..", "docs", "playground");
const smt = fs.readFileSync(path.join(dir, "sample.smt2"));
const proof = fs.readFileSync(path.join(dir, "sample.proof"));

let fails = 0;
const check = (name, got, want) => {
  const ok = String(got) === String(want);
  console.log(`  ${ok ? "[OK]" : "[FAIL]"} ${name}: ${got}${ok ? "" : ` (ожидалось ${want})`}`);
  if (!ok) fails++;
};

WebAssembly.instantiate(fs.readFileSync(path.join(dir, "kernc.wasm")), {}).then(({ instance: { exports: e } }) => {
  // ПРЕДСТАВЛЕНИЕ ПАМЯТИ БЕРЁМ ЗАНОВО ПЕРЕД КАЖДОЙ ЗАПИСЬЮ: модуль растит память,
  // и ранее созданный Uint8Array становится detached (поймано на первом прогоне).
  const view = () => new Uint8Array(e.memory.buffer);
  const ptr = e.kern_wasm_input_ptr();
  const cap = e.kern_wasm_input_cap();

  check("input_cap() == 65536", cap, 65536);
  check("input_ptr() != 0", ptr > 0, true);
  check("JOIN_K(T,F) == B(3)", e.kern_wasm_belnap_join(1, 2), 3);
  check("allow(B) == 0 (конфликт не пропущен)", e.kern_wasm_belnap_allow(3), 0);

  if (smt.length + proof.length > cap) {
    check("эталон влезает в входной буфер", false, true);
  } else {
    view().set(smt, ptr);
    view().set(proof, ptr + smt.length);
    const honest = e.kern_wasm_verify_proof(ptr, smt.length, ptr + smt.length, proof.length);
    check("честный Z3-сертификат ПРИНЯТ (1)", honest, 1);

    const bad = Buffer.from(proof);
    bad[bad.length >> 1] = bad[bad.length >> 1] === 0x29 ? 0x28 : 0x29;
    view().set(bad, ptr + smt.length);
    const sabot = e.kern_wasm_verify_proof(ptr, smt.length, ptr + smt.length, proof.length);
    check("подделка 1 байта ОТКЛОНЕНА (0)", sabot, 0);
  }

  console.log(fails ? `[FAIL] wasm-playground: провалов ${fails}` : "[OK] wasm-playground: 6/6 сценариев в Node");
  process.exit(fails ? 1 : 0);
}).catch((err) => {
  console.log("[FAIL] wasm-playground: " + err.message);
  process.exit(1);
});
