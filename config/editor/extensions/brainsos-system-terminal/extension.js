const vscode = require('vscode');
const fs = require('fs');

const CHAT_CONTEXT_KEYS = [
  ['github.copilot.hasByokModels', true],
  [' nonCopilotLanguageModelsAreUserSelectable', true],
  ['nonCopilotLanguageModelsAreUserSelectable', true],
  ['github.copilot.interactiveSession.disabled', false],
  ['github.copilot.interactiveSession.gitHubLoginFailed', false],
  ['chatSetupCompleted', true],
  ['chatSetupHidden', true]
];

let lastSyncedLmContent = '';

function assertChatByokContext(forceSyncUserdata = false) {
  for (const [key, val] of CHAT_CONTEXT_KEYS) {
    try {
      vscode.commands.executeCommand('setContext', key, val).then(null, () => {});
    } catch (_) {}
  }

  try {
    const lmPath = '/home/coder/.local/share/code-server/User/chatLanguageModels.json';
    if (fs.existsSync(lmPath) && vscode.workspace && vscode.workspace.fs) {
      const contentBuf = fs.readFileSync(lmPath);
      const contentStr = contentBuf.toString('utf8');
      if (forceSyncUserdata || contentStr !== lastSyncedLmContent) {
        lastSyncedLmContent = contentStr;
        const userdataUri = vscode.Uri.from({
          scheme: 'vscode-userdata',
          path: '/User/chatLanguageModels.json'
        });
        Promise.resolve(
          vscode.workspace.fs.writeFile(userdataUri, Uint8Array.from(contentBuf))
        ).catch(() => {});
      }
    }
  } catch (_) {}
}

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
  assertChatByokContext(true);
  for (const delayMs of [2000, 5000, 15000]) {
    setTimeout(() => assertChatByokContext(delayMs === 2000), delayMs);
  }
  if (vscode.window && typeof vscode.window.onDidChangeWindowState === 'function') {
    const disp = vscode.window.onDidChangeWindowState(() => {
      assertChatByokContext(false);
    });
    if (context && Array.isArray(context.subscriptions)) {
      context.subscriptions.push(disp);
    }
  }

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
