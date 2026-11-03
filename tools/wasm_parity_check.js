// Испытание 5 (гейт #462): ФУНКЦИОНАЛЬНЫЙ ПАРИТЕТ раздаваемого wasm.
//
// ЗАЧЕМ. `wasm_check.sh` сверял `docs/kernc.wasm` с текущей сборкой БАЙТ-В-БАЙТ.
// Это ловит отставание файла, но НЕ ловит поломку СЕМАНТИКИ модуля (например,
// ошибку сборки под `wasm32-freestanding`, из-за которой вердикты разойдутся
// с ядром). Здесь модуль РЕАЛЬНО ИСПОЛНЯЕТСЯ (node/WebAssembly) и сверяется с
// НЕЗАВИСИМЫМ оракулом:
//   * решётка Белнапа B4 (JOIN_K, allow) — против ОПРЕДЕЛЕНИЯ (p,n)-битов;
//   * встроенный решатель Фурье — Моцкина — против ЗВУЧИХ свойств.
//
// ГРАНИЦА, названная честно: для LIA проверяется ЗВУЧИЕ, а не совпадение
// вердикта. Возврат `0` (unknown) ЗАКОНЕН, когда модуль не предъявил целую
// точку: это fail-closed, а не ошибка. Запрещены ровно два исхода:
//   * `1` (UNSAT), когда независимый брутфорс нашёл целую точку;
//   * `2` (SAT), когда область пуста (плотная сетка над R).
// ИЗМЕРЕНО на `67a8d43`: 28 проверок, 0 нарушений; один `0` на `x<=5, x>=3`.
const fs = require('fs');
const NAMES = { 0: 'N', 1: 'T', 2: 'F', 3: 'B' };

function main() {
  const bytes = fs.readFileSync('docs/kernc.wasm');
  return WebAssembly.instantiate(bytes, {}).then(({ instance }) => {
    const e = instance.exports;
    let checks = 0, bad = 0;
    for (let a = 0; a < 4; a++) for (let b = 0; b < 4; b++) {
      const exp = ((a & 1) | (b & 1)) | ((((a >> 1) & 1) | ((b >> 1) & 1)) << 1);
      const got = e.kern_wasm_belnap_join(a, b);
      checks++;
      if (got !== exp) { bad++; console.log(`  [FAIL] join ${NAMES[a]} ${NAMES[b]}: ${NAMES[got]} != ${NAMES[exp]}`); }
    }
    for (let v = 0; v < 4; v++) {
      const got = e.kern_wasm_belnap_allow(v);
      checks++;
      if (got !== (v === 1 ? 1 : 0)) { bad++; console.log(`  [FAIL] allow ${NAMES[v]}: ${got}`); }
    }
    const sys = [[-1,-1,0,1,-1,0],[1,-1,0,-1,1,0],[1,0,-1,-1,0,2],[1,0,-5,-1,0,3],
                 [1,1,-100,-1,-1,-100],[1,0,1,-1,0,1],[1,1,-1,-1,-1,-1],[2,0,-3,-2,0,4]];
    for (const s of sys) {
      const [a1,b1,c1,a2,b2,c2] = s;
      let w = null;
      for (let x = -40; x <= 40 && !w; x++) for (let y = -40; y <= 40; y++)
        if (a1*x + b1*y + c1 <= 0 && a2*x + b2*y + c2 <= 0) { w = [x, y]; break; }
      let realFeasible = false;
      for (let x = -200; x <= 200 && !realFeasible; x++) for (let y = -200; y <= 200; y++)
        if (a1*x/10 + b1*y/10 + c1 <= 0 && a2*x/10 + b2*y/10 + c2 <= 0) { realFeasible = true; break; }
      const got = e.kern_wasm_lia_unsat2(BigInt(a1),BigInt(b1),BigInt(c1),
                                         BigInt(a2),BigInt(b2),BigInt(c2));
      checks++;
      if (w && got === 1) { bad++; console.log(`  [FAIL] lia [${s}] witness ${w}, но вердикт UNSAT`); }
      else if (!realFeasible && got === 2) { bad++; console.log(`  [FAIL] lia [${s}] область пуста, но вердикт SAT`); }
    }
    console.log(`  [OK] wasm-паритет: проверок ${checks}, нарушений звучия ${bad}`);
    return bad === 0 ? 0 : 1;
  }).catch((err) => { console.log(`  [FAIL] wasm не исполняется: ${err}`); return 1; });
}

main().then((rc) => process.exit(rc));
