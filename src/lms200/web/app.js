'use strict';
const $ = id => document.getElementById(id);
let latest = null, status = null, socket, pendingAction = 'start';
const canvas = $('scan'), ctx = canvas.getContext('2d');
function text(id, value) { $(id).textContent = value; }
function showError(message) { $('error').hidden = !message; text('error', message || ''); }
async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed');
  return data;
}
function updateStatus(data) {
  status = data;
  text('state', data.state); $('state').className = `badge ${data.state}`;
  const physical = ['tcp', 'serial'].includes(data.settings.transport);
  text('transport', data.settings.transport === 'simulator' ? 'Simulator · synthetic data' : data.settings.transport);
  text('source', data.settings.transport.toUpperCase());
  text('endpoint', data.settings.transport === 'tcp' ? `${data.settings.host}:${data.settings.tcp_port}` : (data.settings.serial_port || (physical ? 'Auto-discovery' : 'Local byte stream')));
  text('model', data.model || (physical ? 'Awaiting scanner' : 'LMS200-30106 / simulated'));
  text('firmware', data.device_status?.firmware || '—'); text('unit', data.device_status?.unit || '—');
  text('hz', `${Number(data.received_scan_hz).toFixed(2)} Hz`);
  text('points', data.points || '—'); text('baud', Number(data.baud).toLocaleString());
  text('geometry', data.device_status ? `${data.device_status.angle}° field · ${data.device_status.resolution}° increments` : 'Awaiting verified configuration');
  text('throughput', data.serial_ceiling_hz ? `Wire ceiling ≤ ${data.serial_ceiling_hz} complete scans/s` : '8 data bits · no parity · 1 stop bit');
  text('crc', `${data.framing.crc_errors} CRC errors`);
  text('errors', `${data.counters.timeouts} timeouts · ${data.counters.malformed + data.framing.invalid_lengths + data.framing.truncated_frames} malformed · ${data.counters.dropped_scans} missed`);
  text('nominal', `${data.nominal_complete_scan_hz} complete scans/s before serial limits at ${data.device_status?.resolution || data.settings.resolution}° resolution.`);
  text('recording-status', data.recording ? `Recording ${data.recording}` : 'Recording is off');
  $('record').classList.toggle('recording', Boolean(data.recording));
  $('record').textContent = data.recording ? '● Finish recording' : '● Record';
  for (const id of ['start', 'stop', 'reconnect', 'probe']) $(id).disabled = data.busy;
  $('record').disabled = data.state !== 'streaming' && !data.recording;
  $('download').disabled = !latest;
  if (data.error) showError(data.error);
  const log = $('log'); const nearEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
  log.textContent = data.log.join('\n') || 'Ready. Start the simulator or probe a connected device.';
  if (nearEnd) log.scrollTop = log.scrollHeight;
}
async function action(name) {
  showError('');
  if (['start', 'reconnect'].includes(name) && status?.settings.read_only && ['serial', 'tcp'].includes(status.settings.transport)) {
    pendingAction = name;
    const rs422 = status.settings.serial_standard === 'rs422';
    $('jumper-label').hidden = !rs422;
    document.querySelector('[name=rs422_pins_7_8_bridged]').required = rs422;
    $('hardware').showModal(); return;
  }
  await request('/api/action', {action: name});
  await refresh();
}
for (const name of ['start', 'stop', 'reconnect', 'probe']) $(name).onclick = () => action(name).catch(e => showError(e.message));
$('consent-form').onsubmit = async event => {
  event.preventDefault(); const consent = {};
  for (const input of event.target.querySelectorAll('input')) consent[input.name] = input.checked;
  try { await request('/api/consent', {consent, enable_writes: true}); $('hardware').close(); await refresh(); await action(pendingAction); }
  catch (e) { showError(e.message); $('hardware').close(); }
};
$('cancel-consent').onclick = () => $('hardware').close();
$('record').onclick = async () => {
  try { await request(`/api/record/${status?.recording ? 'stop' : 'start'}`, {}); await refresh(); await recordings(); }
  catch (e) { showError(e.message); }
};
$('download').onclick = () => { location.href = `/api/export/${$('format').value}`; };
$('range').oninput = () => { text('range-value', `${$('range').value} m`); draw(); };
function draw() {
  const rect = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
  ctx.scale(dpr, dpr); const w = rect.width, h = rect.height;
  const ox = w / 2, oy = h - 60, radius = Math.min(w / 2 - 44, h - 100), range = +$('range').value;
  ctx.clearRect(0, 0, w, h); ctx.lineWidth = 1; ctx.font = '10px Segoe UI, sans-serif';
  ctx.strokeStyle = '#284753'; ctx.fillStyle = '#668590'; ctx.textAlign = 'center';
  for (let i = 1; i <= 4; i++) {
    const r = radius * i / 4;
    ctx.beginPath(); ctx.arc(ox, oy, r, Math.PI, 2 * Math.PI); ctx.stroke();
    ctx.fillText(`${(range * i / 4).toFixed(1)} m`, ox + 22, oy - r + 14);
  }
  for (let a = 0; a <= 180; a += 30) {
    const rad = a * Math.PI / 180;
    ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(ox + radius * Math.cos(rad), oy - radius * Math.sin(rad)); ctx.stroke();
    ctx.fillText(`${a}°`, ox + (radius + 24) * Math.cos(rad), oy - (radius + 22) * Math.sin(rad) + 3);
  }
  ctx.strokeStyle = '#294959'; ctx.beginPath(); ctx.moveTo(24, oy); ctx.lineTo(w - 24, oy); ctx.stroke();
  if (latest) {
    ctx.fillStyle = '#b8ef73'; ctx.shadowColor = '#b8ef7355'; ctx.shadowBlur = 5;
    for (const p of latest.points) if (p.x !== null && p.y !== null && p.distance_m <= range) {
      ctx.beginPath(); ctx.arc(ox + p.x / range * radius, oy - p.y / range * radius, 2, 0, Math.PI * 2); ctx.fill();
    }
    ctx.shadowBlur = 0;
  } else { ctx.fillStyle = '#a4bac1'; ctx.fillText('Start a scan to see measured points', ox, oy - radius / 2); }
  ctx.strokeStyle = '#eef6f0'; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(ox - 5, oy - 5); ctx.lineTo(ox + 5, oy + 5); ctx.moveTo(ox - 5, oy + 5); ctx.lineTo(ox + 5, oy - 5); ctx.stroke();
}
new ResizeObserver(draw).observe(canvas.parentElement);
function connect() {
  socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/scans`);
  socket.onopen = () => text('socket-state', 'Live channel connected');
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === 'status') updateStatus(message.data);
    else if (message.type === 'scan') {
      latest = message.data; text('sequence', `SCAN ${String(latest.sequence).padStart(6, '0')}`);
      text('scanner-status', `${latest.status.severity}${latest.status.pollution ? ' · pollution' : ''}${latest.status.implausible ? ' · implausible values' : ''}`);
      draw();
    }
  };
  socket.onclose = () => { text('socket-state', 'Live channel interrupted · reconnecting'); setTimeout(connect, 1500); };
  socket.onerror = () => socket.close();
}
async function refresh() { updateStatus(await request('/api/status')); }
async function recordings() {
  const files = await request('/api/recordings'), container = $('recordings'); container.replaceChildren();
  for (const file of files.slice(-24).reverse()) {
    const a = document.createElement('a'); a.href = `/api/recordings/${encodeURIComponent(file.name)}`;
    a.textContent = `↓ ${file.name} · ${(file.bytes / 1024).toFixed(1)} KB`; container.append(a);
  }
  if (!files.length) container.textContent = 'No recordings yet';
}
connect(); refresh().catch(e => showError(e.message)); recordings().catch(() => {});
setInterval(() => refresh().catch(() => {}), 1000);
setInterval(() => recordings().catch(() => {}), 7000);
