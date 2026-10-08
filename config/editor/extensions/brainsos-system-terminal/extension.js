const vscode = require('vscode');

function pruneExplorerViews() {
  const viewsToPrune = [
    'outline',
    'timeline',
    'foam-vscode.connections',
    'foam-vscode.tags-explorer',
    'foam-vscode.notes-explorer',
    'foam-vscode.orphans',
    'foam-vscode.placeholders',
    'foam-vscode.smart-folders',
    'npm'
  ];
  for (const v of viewsToPrune) {
    try {
      vscode.commands.executeCommand(`${v}.removeView`).then(null, () => {});
    } catch (_) {}
  }
}

function activate(context) {
  setTimeout(() => {
    try {
      pruneExplorerViews();
      if (vscode.window.terminals.length === 0) {
        const terminal = vscode.window.createTerminal({
          name: "System Terminal",
          location: vscode.TerminalLocation.Editor,
          cwd: "/data"
        });
        terminal.show();
      } else {
        vscode.window.terminals[0].show();
      }
    } catch (err) {
      console.error("[brainsOS] Failed to initialize startup terminal:", err);
    }
  }, 500);
}

function deactivate() {}

module.exports = { activate, deactivate };
