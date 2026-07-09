// Dev/QA tooling IPC: full save-data export.
//
// Gated behind QA tools mode (dev, or STELLARIS_QA_TOOLS=1) — see main.js. The
// heavy lifting is done by the Python backend (POST /api/qa/export), which reuses
// the same run_full_export as the `stellaris-qa-export` CLI.

function registerQaIpcHandlers({
  ipcMain,
  validateSender,
  dialog,
  shell,
  getMainWindow,
  callBackendApiEnvelope,
  isEnabled,
}) {
  const enabled = () => Boolean(typeof isEnabled === 'function' && isEnabled())

  ipcMain.handle('qa:enabled', async (event) => {
    try {
      validateSender(event)
    } catch {
      return false
    }
    return enabled()
  })

  ipcMain.handle('qa:export', async (event, opts = {}) => {
    try {
      validateSender(event)
    } catch (e) {
      return { ok: false, error: e instanceof Error ? e.message : 'IPC error' }
    }
    if (!enabled()) {
      return { ok: false, error: 'QA tools are disabled' }
    }

    const win = typeof getMainWindow === 'function' ? getMainWindow() : null
    const { canceled, filePath } = await dialog.showSaveDialog(win, {
      title: 'Export save data (QA)',
      defaultPath: 'stellaris-qa-export.json',
      filters: [{ name: 'JSON', extensions: ['json'] }],
    })
    if (canceled || !filePath) {
      return { ok: false, canceled: true }
    }

    const res = await callBackendApiEnvelope('/api/qa/export', {
      method: 'POST',
      body: JSON.stringify({ output_path: filePath, include_raw: Boolean(opts.includeRaw) }),
    })

    if (res && res.ok && res.data) {
      try {
        shell.showItemInFolder(res.data.path || filePath)
      } catch {
        // Revealing in the file manager is best-effort; the file is still written.
      }
      return { ok: true, data: res.data }
    }
    return res || { ok: false, error: 'Backend error' }
  })
}

module.exports = {
  registerQaIpcHandlers,
}
