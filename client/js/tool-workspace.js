/* Execution observations are plain text, never model-generated markup. */
(() => {
  window.createToolWorkspace = (panel, stage) => {
    const list = panel.querySelector('.tool-workspace-list');
    const count = panel.querySelector('#tool-workspace-count');
    const rows = new Map();
    let turn = '';
    let follow = true;
    let omitted = 0;
    const labels = { running: 'Running', succeeded: 'Done', failed: 'Failed', cancelled: 'Cancelled', background: 'Background' };
    list.addEventListener('scroll', () => {
      follow = list.scrollHeight - list.scrollTop - list.clientHeight < 24;
    });
    function detail(label, value, truncated, patch = false) {
      const block = document.createElement('details');
      block.dataset.section = patch ? 'patch' : 'arguments';
      const summary = document.createElement('summary');
      summary.textContent = label + (truncated ? ' (preview; remainder omitted)' : '');
      const pre = document.createElement('pre');
      if (patch) {
        for (const line of String(value).split('\n')) {
          const span = document.createElement('span');
          span.className = line.startsWith('+') ? 'diff-add' : line.startsWith('-') ? 'diff-remove' : '';
          span.textContent = line + '\n';
          pre.appendChild(span);
        }
      } else pre.textContent = String(value);
      block.append(summary, pre);
      return block;
    }
    function reset() {
      rows.clear(); list.replaceChildren(); omitted = 0; follow = true;
    }
    function handle(data) {
      if (!data.turn_id) return;
      if (data.action === 'begin') {
        if (turn !== data.turn_id) reset();
        turn = data.turn_id;
        omitted = Number(data.omitted) || 0;
        panel.classList.remove('hidden'); stage.classList.add('has-tool-workspace');
        count.textContent = String(rows.size) + (omitted ? ` · ${omitted} earlier omitted` : '');
        return;
      }
      if (data.turn_id !== turn) return;
      if (data.action === 'end') {
        reset(); turn = ''; panel.classList.add('hidden'); stage.classList.remove('has-tool-workspace');
        return;
      }
      if (data.action !== 'call' || !data.call_id) return;
      let row = rows.get(data.call_id);
      const expanded = new Set(row ? [...row.querySelectorAll('details[open]')].map(el => el.dataset.section) : []);
      if (!row) {
        row = document.createElement('article'); row.className = 'tool-call';
        rows.set(data.call_id, row); list.appendChild(row);
      }
      row.replaceChildren();
      const heading = document.createElement('div'); heading.className = 'tool-call-heading';
      const name = document.createElement('strong'); name.textContent = String(data.tool || 'tool');
      const status = document.createElement('span');
      status.className = 'tool-call-status ' + (Object.hasOwn(labels, data.status) ? data.status : 'running');
      status.textContent = labels[data.status] || data.status || 'Running';
      if (data.status === 'background' && data.session_id) status.textContent += ' #' + data.session_id;
      heading.append(name, status); row.append(heading);
      row.append(detail('Arguments', data.arguments || '{}', data.arguments_truncated));
      if (typeof data.patch === 'string') row.append(detail('Diff', data.patch || '(no text changes)', data.patch_truncated, true));
      row.querySelectorAll('details').forEach(el => { el.open = expanded.has(el.dataset.section); });
      while (rows.size > 100) {
        const first = rows.keys().next().value;
        rows.get(first).remove(); rows.delete(first); omitted++;
      }
      omitted = Math.max(omitted, Number(data.omitted) || 0);
      count.textContent = String(rows.size) + (omitted ? ` · ${omitted} earlier omitted` : '');
      if (follow) list.scrollTop = list.scrollHeight;
    }
    return { handle };
  };
})();
