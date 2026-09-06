// fragments/pdf-chart-generation/app.js
(function () {
  // =========================
  // Constants & configuration
  // =========================
  const DETAILS_DOWNLOAD_SUFFIX = '_modified.json';
  const SERVER_ENDPOINT = '/api/generate-pdf';
  const DEPLOY_ACCESS_ENDPOINT = '/api/deploy/access';

  // =========================
  // Module state
  // =========================
  let rawDataCsvTexts = [];               // array of raw data csv texts
  let detailsJson = null;                 // details.json as a JavaScript object
  let detailsOriginalName = '';           // original details file name
  const metadataInputs = new Map();       // label -> <input>
  const channelEditors = [];              // channel -> {transducerInput, gaugeInput, visibleCheckbox}
  const massSpecTimingEditors = [];       // label -> {startInput, stopInput}
  const holdsEditors = [];                // cycle_index -> {channelInput, startOfStabilisationInput, startOfHoldInput, endOfHoldInput, breakoutTorqueInput, runningTorqueInput}
  const cyclesEditors = [];               // cycle_index -> {btoInput, btcInput}
  let calibrationEditor = {};             // {channelNameInput, channelIndexInput, maxRangeInput, keyPointsInputs}
  let uiWired = false;                    // prevent double binding
  let calibrationAccessPromise = null;    // memoized whitelist check

  // =========================
  // DOM helpers
  // =========================
  const byId = id => /** @type {HTMLElement|null} */(document.getElementById(id));
  const el = (tag, props = {}, children = []) => {
    const node = document.createElement(tag);
    Object.assign(node, props);
    for (const c of children) node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    return node;
  };

  // Simple reusable error dialog
  function showErrorDialog(title, message, details = '') {
    let backdrop = byId('pcg-error-backdrop');
    let dialog = byId('pcg-error-dialog');

    if (!backdrop) {
      backdrop = el('div', {
        id: 'pcg-error-backdrop',
        style: `
          position: fixed;
          inset: 0;
          background: rgba(0,0,0,0.55);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 9999;
        `
      });

      dialog = el('div', {
        id: 'pcg-error-dialog',
        style: `
          background: var(--panel, #1f2933);
          color: var(--text, #f9fafb);
          max-width: 520px;
          width: 90%;
          border-radius: 12px;
          box-shadow: 0 20px 40px rgba(0,0,0,.6);
          padding: 18px 20px;
          box-sizing: border-box;
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        `
      });

      const titleEl = el('h2', {
        id: 'pcg-error-title',
        style: 'margin: 0 0 8px; font-size: 1.1rem; font-weight: 600;'
      });

      const msgEl = el('p', {
        id: 'pcg-error-message',
        style: 'margin: 0 0 8px; white-space: pre-wrap;'
      });

      const detailsEl = el('pre', {
        id: 'pcg-error-details',
        style: `
          margin: 8px 0 0;
          padding: 8px;
          max-height: 160px;
          overflow: auto;
          font-size: 0.8rem;
          background: rgba(0,0,0,0.3);
          border-radius: 8px;
          white-space: pre-wrap;
        `
      });

      const buttonRow = el('div', {
        style: 'margin-top: 14px; display: flex; justify-content: flex-end; gap: 8px;'
      });

      const closeBtn = el('button', {
        textContent: 'Close',
        className: 'btn',
        style: 'padding: 6px 14px; border-radius: 999px;'
      });

      closeBtn.addEventListener('click', () => {
        backdrop.style.display = 'none';
        document.body.style.overflow = '';
      });

      buttonRow.append(closeBtn);
      dialog.append(titleEl, msgEl, detailsEl, buttonRow);
      backdrop.appendChild(dialog);
      document.body.appendChild(backdrop);
    }

    const titleEl = byId('pcg-error-title');
    const msgEl = byId('pcg-error-message');
    const detailsEl = byId('pcg-error-details');

    if (titleEl) titleEl.textContent = title || 'PDF generation error';
    if (msgEl) msgEl.textContent = message || 'Something went wrong while generating the PDF.';
    if (detailsEl) {
      detailsEl.textContent = (details || '').trim();
      detailsEl.style.display = details ? 'block' : 'none';
    }

    backdrop.style.display = 'flex';
  }

  // Helper for table headers
  // width argument allows forcing columns to shrink (e.g. '1%')
  const th = (text, width = '') => el('th', {
    textContent: text,
    style: `white-space: nowrap; padding: 8px; ${width ? 'width: ' + width : ''}`
  });

  // Helper for table inputs
  const tableInputProps = (extraClass = '') => ({
    className: `form-input ${extraClass}`,
    style: 'width: 100%; box-sizing: border-box; min-width: 40px;'
  });

  function labelledInput(labelText, value = '') {
    const wrap = el('div', { style: 'margin: 6px 0' });
    const label = el('label', {
      textContent: labelText + ': ',
      style: 'display: inline-block; min-width: 220px;'
    });
    const input = el('input', { type: 'text', value, className: 'form-input', style: 'width: 100%;' });
    wrap.append(label, input);
    return { wrap, input };
  }

  function labelledCheckbox(labelText, checked = false) {
    const wrap = el('div', { style: 'margin: 6px 0; display:flex; align-items:center;' });
    const label = el('label', {
      textContent: labelText + ': ',
      style: 'display: inline-flex; align-items:center; min-width: 210px;'
    });
    const cbWrap = el('div', { style: 'width:60%; display:flex; margin: 0px 0px;' });
    const cb = el('input', { type: 'checkbox', className: 'form-checkbox h-4 w-4 text-blue-600' });
    cb.checked = !!checked;
    cbWrap.append(cb);
    wrap.append(label, cbWrap);
    return { wrap, cb };
  }

  function filenameFromContentDisposition(cdHeader) {
    if (!cdHeader) return null;

    // RFC 5987 form: filename*=UTF-8''<url-encoded>
    const m1 = cdHeader.match(/filename\*=UTF-8''([^;]+)/i);
    if (m1 && m1[1]) {
      try { return decodeURIComponent(m1[1]); } catch {}
    }

    // Basic form: filename="<name>" or filename=<name>
    const m2 = cdHeader.match(/filename="?([^"]+)"?/i);
    if (m2 && m2[1]) return m2[1];

    return null;
  }

  async function isCalibrationTabAllowed() {
    if (calibrationAccessPromise) return calibrationAccessPromise;

    calibrationAccessPromise = fetch(DEPLOY_ACCESS_ENDPOINT, { cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) return false;
        const payload = await response.json().catch(() => null);
        return Boolean(payload && payload.allowed);
      })
      .catch(() => false);

    return calibrationAccessPromise;
  }

  // =========================
  // File picking & classification
  // =========================
  function classifyFiles(files) {
    const csvs = files.filter(f => f.name.toLowerCase().endsWith('.csv'));
    const jsons = files.filter(f => f.name.toLowerCase().endsWith('.json'));

    if (csvs.length < 1 || jsons.length !== 1) {
      return { error: 'Please select at least one .csv file and exactly one .json file.' };
    }

    return {
      csvs: csvs.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' })),
      details: jsons[0]
    };
  }

  // =========================
  // Details form builders
  // =========================
  async function buildEditor(details) {
    const navLinksHost = byId('pcg-dynamic-nav-links');
    const contentHost = byId('pcg-editor-content-host');
    if (!navLinksHost || !contentHost) {
      console.error("Required host elements not found for editor.");
      return;
    }

    navLinksHost.innerHTML = '';
    contentHost.innerHTML = '';

    metadataInputs.clear();
    channelEditors.length = 0;
    massSpecTimingEditors.length = 0;
    holdsEditors.length = 0;
    cyclesEditors.length = 0;
    calibrationEditor = {};

    const allContentSections = [];

    const showContentSection = (targetId) => {
      allContentSections.forEach(section => {
        section.style.display = (section.id === targetId) ? 'block' : 'none';
      });
      // Also update the active state of the nav links
      navLinksHost.querySelectorAll('a').forEach(link => {
        link.classList.toggle('active', link.hash === `#pdf-chart-generation/${targetId}`);
      });
    };

    const createSection = (key, title, content) => {
      const anchorId = key;
      const navHash = `#pdf-chart-generation/${anchorId}`;

      // Create nav link
      const navLink = el('a', {
        href: navHash,
        textContent: title,
        className: 'sub-nav-link'
      });
      navLink.addEventListener('click', (e) => {
        e.preventDefault();
        history.pushState(null, '', navHash);
        showContentSection(anchorId);
      });
      navLinksHost.appendChild(navLink);

      // Create content section
      const section = el('section', { id: anchorId });
      section.appendChild(el('h2', { textContent: title }));
      section.appendChild(content);
      contentHost.appendChild(section);
      allContentSections.push(section);
    };

    // Metadata
    const metadataForm = el('div');
    for (const key in details.metadata) {
      const value = details.metadata[key];
      const { wrap, input, cb } = (typeof value === 'boolean')
        ? labelledCheckbox(key, value)
        : labelledInput(key, value);
      metadataForm.appendChild(wrap);
      metadataInputs.set(key, input || cb);
    }
    createSection('metadata', 'Metadata', metadataForm);

    // Channel Info
    const channelInfoForm = el('div');
    const channelTable = el('table', { className: 'pcg-table pcg-table-auto', style: 'width: 100%;' });
    const channelHeader = el('tr', {}, [
      th('Channel'),
      th('Transducer'),
      th('Gauge'),
      th('Visible', '1%')
    ]);
    const channelBody = el('tbody');
    channelTable.append(channelHeader, channelBody);
    details.channel_info.forEach(channel => {
      const transducerInput = el('input', { type: 'text', value: channel.transducer, ...tableInputProps() });
      const gaugeInput = el('input', { type: 'text', value: channel.gauge, ...tableInputProps() });
      const visibleCheckbox = el('input', { type: 'checkbox' });
      visibleCheckbox.checked = channel.visible;
      const tr = el('tr', {}, [
        el('td', { textContent: channel.channel }),
        el('td', {}, [transducerInput]),
        el('td', {}, [gaugeInput]),
        el('td', { style: 'text-align: center;' }, [visibleCheckbox])
      ]);
      channelBody.appendChild(tr);
      channelEditors.push({ channel: channel.channel, transducerInput, gaugeInput, visibleCheckbox });
    });
    channelInfoForm.appendChild(channelTable);
    createSection('channel-info', 'Channel Info', channelInfoForm);

    // Mass Spec Timings
    const massSpecTimingsForm = el('div');
    const massSpecTable = el('table', { className: 'pcg-table pcg-table-auto', style: 'width: 100%;' });
    const massSpecHeader = el('tr', {}, [
      th('Label', '20%'),
      th('Start'),
      th('Stop')
    ]);
    const massSpecBody = el('tbody');
    massSpecTable.append(massSpecHeader, massSpecBody);
    details.mass_spec_timings.forEach(timing => {
      const startInput = el('input', { type: 'text', value: timing.start, ...tableInputProps() });
      const stopInput = el('input', { type: 'text', value: timing.stop, ...tableInputProps() });
      const tr = el('tr', {}, [
        el('td', { textContent: timing.label }),
        el('td', {}, [startInput]),
        el('td', {}, [stopInput])
      ]);
      massSpecBody.appendChild(tr);
      massSpecTimingEditors.push({ label: timing.label, startInput, stopInput });
    });
    massSpecTimingsForm.appendChild(massSpecTable);
    createSection('mass-spec-timings', 'Mass Spec Timings', massSpecTimingsForm);

    // Holds
    const holdsForm = el('div');
    const holdsTable = el('table', { className: 'pcg-table pcg-table-auto', style: 'width: 100%;' });

    const holdsHeader = el('tr', {}, [
      th('Cycle Index', '1%'),
      th('Channel'),
      th('Start of Stabilisation'),
      th('Start of Hold'),
      th('End of Hold'),
      th('Breakout Torque', '1%'),
      th('Running Torque', '1%'),
      th('', '1%')
    ]);
    const holdsBody = el('tbody');
    holdsTable.append(holdsHeader, holdsBody);

    const addHoldRow = (hold) => {
      const cycleIndexInput = el('input', { type: 'number', value: hold.cycle_index, min: '0', step: '1', ...tableInputProps() });
      const channelInput = el('input', { type: 'text', value: hold.channel, ...tableInputProps() });
      const startOfStabilisationInput = el('input', { type: 'text', value: hold.start_of_stabilisation, ...tableInputProps() });
      const startOfHoldInput = el('input', { type: 'text', value: hold.start_of_hold, ...tableInputProps() });
      const endOfHoldInput = el('input', { type: 'text', value: hold.end_of_hold, ...tableInputProps() });
      const breakoutTorqueInput = el('input', { type: 'text', value: hold.breakout_torque, ...tableInputProps() });
      const runningTorqueInput = el('input', { type: 'text', value: hold.running_torque, ...tableInputProps() });

      const deleteButton = el('button', {
        textContent: 'Delete',
        className: 'btn',
        style: 'width: 100%; background-color: #9ca3af; color: white;'
      });

      const tr = el('tr', {}, [
        el('td', {}, [cycleIndexInput]),
        el('td', {}, [channelInput]),
        el('td', {}, [startOfStabilisationInput]),
        el('td', {}, [startOfHoldInput]),
        el('td', {}, [endOfHoldInput]),
        el('td', {}, [breakoutTorqueInput]),
        el('td', {}, [runningTorqueInput]),
        el('td', {}, [deleteButton])
      ]);

      holdsBody.appendChild(tr);

      const editor = {
        cycleIndexInput,
        channelInput,
        startOfStabilisationInput,
        startOfHoldInput,
        endOfHoldInput,
        breakoutTorqueInput,
        runningTorqueInput
      };

      deleteButton.addEventListener('click', (e) => {
        e.preventDefault();
        holdsBody.removeChild(tr);
        const idx = holdsEditors.indexOf(editor);
        if (idx !== -1) holdsEditors.splice(idx, 1);
      });

      holdsEditors.push(editor);
    };

    details.holds.forEach(addHoldRow);

    const addHoldButton = el('button', {
      textContent: 'Add Hold Row',
      className: 'btn',
      style: 'margin-top: 8px; width: 100%;'
    });

    let nextHoldIndex = Math.max(0, ...details.holds.map(h => Number(h.cycle_index) || 0)) + 1;
    addHoldButton.addEventListener('click', (e) => {
      e.preventDefault();
      addHoldRow({
        cycle_index: nextHoldIndex++,
        channel: '',
        start_of_stabilisation: '',
        start_of_hold: '',
        end_of_hold: '',
        breakout_torque: '',
        running_torque: ''
      });
    });

    holdsForm.append(holdsTable, addHoldButton);
    createSection('holds', 'Holds', holdsForm);

    // Cycles
    const cyclesForm = el('div');
    const cyclesTable = el('table', { className: 'pcg-table pcg-table-auto', style: 'width: 100%;' });
    const cyclesHeader = el('tr', {}, [
      th('Cycle Index', '1%'),
      th('BTO'),
      th('BTC'),
      th('', '1%')
    ]);
    const cyclesBody = el('tbody');
    cyclesTable.append(cyclesHeader, cyclesBody);

    const addCycleRow = (cycle) => {
      const cycleIndexInput = el('input', { type: 'number', value: cycle.cycle_index, min: '0', step: '1', ...tableInputProps() });
      const btoInput = el('input', { type: 'text', value: cycle.bto, ...tableInputProps() });
      const btcInput = el('input', { type: 'text', value: cycle.btc, ...tableInputProps() });
      const deleteButton = el('button', {
        textContent: 'Delete',
        className: 'btn',
        style: 'width: 100%; background-color: #9ca3af; color: white;'
      });
      const tr = el('tr', {}, [
        el('td', {}, [cycleIndexInput]),
        el('td', {}, [btoInput]),
        el('td', {}, [btcInput]),
        el('td', {}, [deleteButton])
      ]);
      cyclesBody.appendChild(tr);
      const editor = { cycleIndexInput, btoInput, btcInput };

      deleteButton.addEventListener('click', (e) => {
        e.preventDefault();
        cyclesBody.removeChild(tr);
        const idx = cyclesEditors.indexOf(editor);
        if (idx !== -1) cyclesEditors.splice(idx, 1);
      });

      cyclesEditors.push(editor);
    };

    details.cycles.forEach(addCycleRow);

    const addCycleButton = el('button', {
      textContent: 'Add Cycle Row',
      className: 'btn',
      style: 'margin-top: 8px; width: 100%;'
    });

    let nextCycleRowIndex = Math.max(0, ...details.cycles.map(c => Number(c.cycle_index) || 0)) + 1;

    addCycleButton.addEventListener('click', (e) => {
      e.preventDefault();
      addCycleRow({
        cycle_index: nextCycleRowIndex++,
        bto: '',
        btc: ''
      });
    });

    cyclesForm.append(cyclesTable, addCycleButton);
    createSection('cycles', 'Cycles', cyclesForm);

    const canViewCalibration = await isCalibrationTabAllowed();
    if (canViewCalibration) {
    // Calibration Section Layout
    const calibrationForm = el('div');

    // Helper to create a vertical stack (Label over Input)
    const createVerticalField = (label, value) => {
      const wrapper = el('div', { style: 'display: flex; flex-direction: column; gap: 4px;' });
      const lbl = el('label', { textContent: label, style: 'font-weight: 600;' });
      const inp = el('input', { type: 'text', value: value, className: 'form-input', style: 'width: 100%;' });
      wrapper.append(lbl, inp);
      return { wrapper, inp };
    };

    // 1. Create a grid container for the top three fields
    const gridContainer = el('div', {
      style: 'display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 20px;'
    });

    const nameField = createVerticalField('Channel Name', details.calibration.channel_name);
    const indexField = createVerticalField('Channel Index', details.calibration.channel_index);
    const rangeField = createVerticalField('Max Range', details.calibration.max_range);

    gridContainer.append(nameField.wrapper, indexField.wrapper, rangeField.wrapper);

    // 2. Key Points Section
    const keyPointsHeader = el('h3', { textContent: 'Key Points', style: 'margin-bottom: 8px;' });

    const keyPointsContainer = el('div', {
      style: 'display: flex; flex-wrap: wrap; gap: 12px;'
    });

    const keyPointsInputs = [];
    details.calibration.key_points.forEach(point => {
      const input = el('input', {
        type: 'text',
        value: point,
        className: 'form-input',
        style: 'flex: 1; min-width: 100px;'
      });
      keyPointsContainer.appendChild(input);
      keyPointsInputs.push(input);
    });

    calibrationForm.append(
      gridContainer,
      keyPointsHeader,
      keyPointsContainer
    );

    calibrationEditor = {
      channelNameInput: nameField.inp,
      channelIndexInput: indexField.inp,
      maxRangeInput: rangeField.inp,
      keyPointsInputs
    };

    createSection('calibration', 'Calibration', calibrationForm);
    }

    const navActions = el('div', { style: 'margin-top: 12px;' });
    const navGenerateButton = el('button', {
      textContent: 'Generate PDF Chart',
      className: 'btn btn-primary',
      style: 'width: 100%;'
    });
    navGenerateButton.addEventListener('click', () => {
      byId('pcg-send-server')?.click();
    });
    navActions.appendChild(navGenerateButton);
    navLinksHost.appendChild(navActions);

    // Show the first section by default
    if (allContentSections.length > 0) {
      showContentSection(allContentSections[0].id);
    }
  }

  async function loadDetails(jsonText) {
    try {
      const details = JSON.parse(jsonText);
      detailsJson = details;
      await buildEditor(details);

      // Hide initial content and the original 'Generate' button container
      byId('pcg-initial-content').style.display = 'none';
      const generateButtonContainer = byId('generate');
      if (generateButtonContainer) {
        generateButtonContainer.style.display = 'none'; // Hide the container of the original button
      }

    } catch (e) {
      console.error('Error parsing details.json:', e);
      showErrorDialog(
        'Invalid details JSON',
        'The details file could not be parsed. Please check that it is valid JSON and try again.',
        e && e.message ? e.message : String(e)
      );
    }
  }

  // =========================
  // Apply UI edits back to detailsJson object
  // =========================
  function applyEditsToDetails() {
    if (!detailsJson) return;

    // Metadata
    for (const [key, input] of metadataInputs.entries()) {
      detailsJson.metadata[key] = input.type === 'checkbox' ? input.checked : input.value;
    }

    // Channel Info
    detailsJson.channel_info.forEach((channel, i) => {
      const editor = channelEditors[i];
      if (editor) {
        channel.transducer = editor.transducerInput.value;
        channel.gauge = editor.gaugeInput.value;
        channel.visible = editor.visibleCheckbox.checked;
      }
    });

    // Mass Spec Timings
    detailsJson.mass_spec_timings.forEach((timing, i) => {
      const editor = massSpecTimingEditors[i];
      if (editor) {
        timing.start = editor.startInput.value;
        timing.stop = editor.stopInput.value;
      }
    });

    // Holds
    detailsJson.holds = holdsEditors.map(editor => ({
      cycle_index: editor.cycleIndexInput.value,
      channel: editor.channelInput.value,
      start_of_stabilisation: editor.startOfStabilisationInput.value,
      start_of_hold: editor.startOfHoldInput.value,
      end_of_hold: editor.endOfHoldInput.value,
      breakout_torque: editor.breakoutTorqueInput.value,
      running_torque: editor.runningTorqueInput.value,
    }));

    // Cycles
    detailsJson.cycles = cyclesEditors.map(editor => ({
      cycle_index: editor.cycleIndexInput.value,
      bto: editor.btoInput.value,
      btc: editor.btcInput.value,
    }));

    // Calibration (only editable on whitelisted IPs)
    if (
      detailsJson.calibration &&
      calibrationEditor.channelNameInput &&
      calibrationEditor.channelIndexInput &&
      calibrationEditor.maxRangeInput &&
      Array.isArray(calibrationEditor.keyPointsInputs)
    ) {
      const cal = detailsJson.calibration;
      cal.channel_name = calibrationEditor.channelNameInput.value;
      cal.channel_index = calibrationEditor.channelIndexInput.value;
      cal.max_range = calibrationEditor.maxRangeInput.value;
      cal.key_points = calibrationEditor.keyPointsInputs.map(input => input.value);
    }
  }

  // =========================
  // Downloads & server I/O
  // =========================
  function downloadTextFile(text, downloadName) {
    const blob = new Blob([text], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = downloadName;
    a.click();
    Promise.resolve().then(() => URL.revokeObjectURL(a.href));
  }

  function triggerDownload(downloadUrl, downloadName = '') {
    const a = document.createElement('a');
    a.href = downloadUrl;
    if (downloadName) a.download = downloadName;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  function downloadBlobFile(blob, downloadName) {
    const url = URL.createObjectURL(blob);
    triggerDownload(url, downloadName);
    Promise.resolve().then(() => URL.revokeObjectURL(url));
  }

  async function downloadGeneratedFiles(files) {
    const queue = Array.isArray(files) ? files.filter(Boolean) : [];

    for (const file of queue) {
      if (file.blob) {
        downloadBlobFile(file.blob, file.name);
      } else if (file.downloadUrl) {
        triggerDownload(file.downloadUrl, file.name);
      }

      // Give the browser a brief moment so multiple downloads are dispatched separately.
      await new Promise(resolve => setTimeout(resolve, 150));
    }
  }

  function timestampedName(prefix, ext = 'json') {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    return `${prefix}_${stamp}.${ext}`;
  }

  async function postFilesToServer(csvTexts, detailsJsonText) {
    const detailsFile = new File(
      [detailsJsonText],
      timestampedName('details_modified'),
      { type: 'application/json', lastModified: Date.now() }
    );

    const fd = new FormData();
    fd.append('details_json', detailsFile);

    csvTexts.forEach((text, i) => {
      // Use padded index to ensure lexicographical sort order in backend (e.g. data_001)
      const index = (i + 1).toString().padStart(3, '0');
      const dataFile = new File(
        [text],
        timestampedName(`data_${index}`, 'csv'),
        { type: 'text/csv', lastModified: Date.now() }
      );
      fd.append('data_csv', dataFile);
    });

    let res;

    try {
      res = await fetch(SERVER_ENDPOINT, {
        method: 'POST',
        body: fd,
        cache: 'no-store',
      });
    } catch (err) {
      return { ok: false, networkError: true, errorText: err?.message || String(err) };
    }

    // If you’re cross-origin, make sure the server sets:
    //   Access-Control-Expose-Headers: Content-Disposition
    const cd = res.headers.get('Content-Disposition') || '';
    const contentType = (res.headers.get('Content-Type') || '').toLowerCase();
    const suggestedName =
      filenameFromContentDisposition(cd) ||
      timestampedName('chart', 'pdf');

    if (!res.ok) {
      const errText = await res.text().catch(() => '');
      return { ok: false, status: res.status, statusText: res.statusText, name: suggestedName, errorText: errText };
    }

    if (contentType.includes('application/json')) {
      const payload = await res.json().catch(() => null);
      const files = Array.isArray(payload?.files)
        ? payload.files
          .map(file => ({
            name: file?.name || timestampedName('chart', 'pdf'),
            downloadUrl: file?.download_url || file?.downloadUrl || '',
          }))
          .filter(file => file.downloadUrl)
        : [];

      if (files.length === 0) {
        return {
          ok: false,
          status: 500,
          statusText: 'Invalid server response',
          errorText: 'The PDF generator did not return any downloadable files.',
        };
      }

      return { ok: true, files };
    }

    const blob = await res.blob();
    return { ok: true, files: [{ blob, name: suggestedName }] };
  }

  // =========================
  // UI wiring
  // =========================
  function initUI() {
    const navSelect = byId('pcg-link'); // your "Select Files" <a>

    // Hook up nav link to trigger file dialog and keep SPA routing happy
    if (navSelect && !navSelect.dataset.pcgBound) {
      navSelect.addEventListener('click', (e) => {
        e.preventDefault();

        const targetHash = '#pdf-chart-generation';
        const openPicker = () => byId('pcg-files')?.click(); // runs in the same user gesture

        if (window.location.hash !== targetHash) {
          window.location.hash = targetHash;
          // Let the router/render tick happen, then open the picker
          requestAnimationFrame(openPicker);
        } else {
          openPicker();
        }
      });
      navSelect.dataset.pcgBound = '1';
    }

    const overlay = byId('pcg-loading-overlay');

    if (uiWired) return;

    const fileInput = byId('pcg-files');
    const statusEl = byId('pcg-status');
    const summaryEl = byId('pcg-file-summary');
    const btnServer = byId('pcg-send-server');

    if (!fileInput || !btnServer || !overlay) {
      console.log('[pcg] initUI: waiting for fragment elements');
      return;
    }

    uiWired = true;
    console.log('[pcg] UI wired');

    // handle files when selected
    fileInput.addEventListener('change', async (e) => {
      if (statusEl) statusEl.textContent = '';

      const files = Array.from(e.target.files || []);
      const picked = classifyFiles(files);

      if (picked.error) {
        if (summaryEl) {
          summaryEl.textContent = picked.error;
          summaryEl.style.color = 'salmon';
        }
        console.warn('[pcg] classifyFiles error:', picked.error);
        showErrorDialog('File selection error', picked.error);
        return;
      }

      if (summaryEl) {
        summaryEl.style.color = 'var(--muted)';
        const csvNames = picked.csvs.map(f => f.name).join('\n  ');
        summaryEl.textContent = `Data CSVs:\n  ${csvNames}\nDetails: ${picked.details.name}`;
      }

      detailsOriginalName = picked.details.name;

      // Read all files
      const csvPromises = picked.csvs.map(f => f.text());
      const detailsPromise = picked.details.text();

      const [csvTexts, detailsText] = await Promise.all([
        Promise.all(csvPromises),
        detailsPromise
      ]);

      rawDataCsvTexts = csvTexts;
      await loadDetails(detailsText);

      if (statusEl) statusEl.textContent = 'Details loaded. Edit fields, then Generate.';

      // Auto-navigate to the Metadata step so the forms are visible
      if (window.location.hash.split('/')[0] === '#pdf-chart-generation') {
        window.location.hash = '#pdf-chart-generation/metadata';
      }

      fileInput.value = '';
    });

    btnServer?.addEventListener('click', async (e) => {
      e.preventDefault();

      if (!detailsJson || rawDataCsvTexts.length === 0) {
        const msg = 'Please load one or more data CSVs and details JSON before generating the PDF.';
        if (statusEl) statusEl.textContent = msg;
        showErrorDialog('Files not loaded', msg);
        overlay?.classList.add('hidden');
        document.body.style.overflow = '';
        return;
      }

      const targetHash = '#pdf-chart-generation';

      if (window.location.hash !== targetHash) {
        window.location.hash = targetHash;
      }

      applyEditsToDetails();

      // Show loading overlay and prevent scroll while generating
      const prevOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      overlay?.classList.remove('hidden');

      // Build fresh JSON text
      const detailsText = JSON.stringify(detailsJson, null, 2);

      // Also download the modified details locally
      {
        const stem = (detailsOriginalName || 'details').replace(/\.json$/i, '') + DETAILS_DOWNLOAD_SUFFIX;
        downloadTextFile(detailsText, stem);
        if (statusEl) statusEl.textContent = 'Modified details JSON downloaded. Sending to server…';
      }

      try {
        const res = await postFilesToServer(rawDataCsvTexts, detailsText);

        if (!res.ok) {
          const msg = res.networkError
            ? 'Cannot reach the PDF generator. Please make sure the server is running and that you are on the right network.'
            : `The PDF generator returned an error (${res.status} ${res.statusText}).`;

          const shortDetail = (res.errorText || '').slice(0, 2000);

          console.log('[pcg] Server error:',
            res.networkError ? 'network' : res.status,
            res.networkError ? 'unreachable' : res.statusText,
            res.errorText || msg
          );

          if (statusEl) statusEl.textContent = msg;
          showErrorDialog(
            'PDF generation failed',
            msg,
            shortDetail
          );
          return;
        }

        await downloadGeneratedFiles(res.files);

        const count = Array.isArray(res.files) ? res.files.length : 0;
        if (statusEl) {
          statusEl.textContent = count === 1
            ? 'PDF downloaded.'
            : `Download started for ${count} PDFs.`;
        }
      } catch (err) {
        console.error(err);
        const msg = 'Network or server error while talking to the PDF generator.';
        if (statusEl) statusEl.textContent = msg;
        showErrorDialog(
          'PDF generator unreachable',
          msg,
          err && err.message ? err.message : String(err)
        );
      } finally {
        overlay?.classList.add('hidden');
        document.body.style.overflow = prevOverflow;
      }

    });
  }

  // Expose an init the router can call after fragment injection
  window.initPdfChartGenerator = initUI;

  // Also auto-init when the fragment appears (in case the router didn’t call us yet)
  const targets = [byId('navHost'), byId('contentHost')].filter(Boolean);
  const ready = () => byId('pcg-files') && byId('pcg-link') && byId('pcg-send-server') && byId('pcg-loading-overlay');

  if (!ready()) {
    const mo = new MutationObserver(() => {
      if (ready()) { initUI(); mo.disconnect(); }
    });
    targets.forEach(t => mo.observe(t, { childList: true, subtree: true }));
  } else {
    initUI();
  }
})();
