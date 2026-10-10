// KERN Lens — расширение VS Code (§ «KERN Lens»).
// СТАТУС (честно): рабочий скелет. Он вызывает РЕАЛЬНЫЕ CLI kernc/kernx через
// child_process и показывает вывод в Output Channel. Чего НЕТ: подсветки строк,
// LSP, инкрементального анализа — см. REVISION/HONEST_CAPABILITY_STATUS.md.
import * as vscode from "vscode";
import { execFile } from "child_process";

function run(bin: string, args: string[]): Promise<string> {
  return new Promise((resolve) => {
    execFile(bin, args, { cwd: vscode.workspace.rootPath }, (err, stdout, stderr) => {
      if (err) resolve(`[KERN] ошибка запуска ${bin}: ${err.message}\n${stderr}`);
      else resolve(stdout || stderr);
    });
  });
}

export function activate(context: vscode.ExtensionContext) {
  const channel = vscode.window.createOutputChannel("KERN");
  context.subscriptions.push(channel);

  context.subscriptions.push(
    vscode.commands.registerCommand("kernLens.checkIntegrity", async () => {
      const img = await vscode.window.showInputBox({ prompt: "Путь к .kimg", value: "tests/fixtures/valid_v1_3.kimg" });
      if (!img) return;
      channel.appendLine(await run("kernc", ["check-integrity", img]));
      channel.show();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("kernLens.status", async () => {
      const f = await vscode.window.showInputBox({ prompt: "Путь к .kern", value: "examples/project.kern" });
      if (!f) return;
      channel.appendLine(await run("kernx", ["status", f]));
      channel.show();
    })
  );
}

export function deactivate() {}
