const vscode = require('vscode');

function activate(context) {
  setTimeout(() => {
    try {
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
