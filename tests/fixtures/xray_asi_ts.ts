// KERN regression fixture — class #401 (branch scope) / ASI (no semicolons).
// A brace-less `if` MUST NOT swallow the rest of the body. Before the fix
// `_clike_block_end` fell back to the next `;`; in ASI-style TS there is none,
// so inner conditions leaked as enclosing facts onto later statements -> two
// mutually exclusive leaks -> UNSAT -> a FALSE "[DEAD BRANCH]".
export function settingsPolicy(trigger: any, bot: boolean) {
  if (bot) {
    const mode = trigger.mode
    if (mode === "off") return { silent: true }
    if (mode === "on") return { silent: false }
  }
  if (!trigger.human) return { notify: false }
  return { notify: true }
}
