/* ===== 08 file parsing: TXT, DOCX (zip+xml), and basic PDF text extraction. Scanned/complex PDFs need the backend OCR adapter. ===== */
const MAX_FILE = 8 * 1024 * 1024, ALLOWED_EXT = ['txt', 'md', 'docx', 'pdf'];
async function inflate(bytes, fmt) {
  if (typeof DecompressionStream === 'undefined') throw new Error('Decompression is not supported in this browser.');
  const ds = new DecompressionStream(fmt); const w = ds.writable.getWriter(); w.write(bytes).catch(() => {}); w.close().catch(() => {});
  return new Uint8Array(await new Response(ds.readable).arrayBuffer());
}
async function readZipEntry(buf, wanted) {
  const b = new Uint8Array(buf); const dv = new DataView(buf); let e = -1;
  for (let i = b.length - 22; i >= Math.max(0, b.length - 66000); i--) if (dv.getUint32(i, true) === 0x06054b50) { e = i; break; }
  if (e < 0) throw new Error('Not a valid DOCX file.');
  const n = dv.getUint16(e + 10, true); let p = dv.getUint32(e + 16, true);
  for (let i = 0; i < n; i++) {
    if (dv.getUint32(p, true) !== 0x02014b50) break;
    const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), nl = dv.getUint16(p + 28, true), el = dv.getUint16(p + 30, true), cl = dv.getUint16(p + 32, true), off = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(b.subarray(p + 46, p + 46 + nl));
    if (name === wanted) { const ln = dv.getUint16(off + 26, true), le = dv.getUint16(off + 28, true); const data = b.subarray(off + 30 + ln + le, off + 30 + ln + le + csize); return method === 0 ? data : inflate(data, 'deflate-raw'); }
    p += 46 + nl + el + cl;
  }
  throw new Error('The DOCX file has no readable body.');
}
const unXml = s => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&#(\d+);/g, (m, d) => String.fromCharCode(+d)).replace(/&amp;/g, '&');
async function parseDocx(buf) {
  const xml = new TextDecoder().decode(await readZipEntry(buf, 'word/document.xml')); const out = [];
  xml.split(/<\/w:p>/).forEach(par => {
    let t = ''; const re = /<w:t(?:\s[^>]*)?>([^<]*)<\/w:t>|<w:tab\/>|<w:br\s+w:type="page"\/>|<w:br\/>|<w:lastRenderedPageBreak\/>/g; let m;
    while ((m = re.exec(par))) { if (m[1] != null) t += unXml(m[1]); else if (m[0].startsWith('<w:tab')) t += ' '; else if (/page|lastRendered/.test(m[0])) t = '\f' + t; else t += ' '; }
    if (t.replace(/\f/g, '').trim() || t.includes('\f')) out.push(t.trim() === '' ? t : t);
  });
  return out.join('\n\n');
}
function pdfString(s) { return s.replace(/\\([nrtbf()\\]|[0-7]{1,3})/g, (m, g) => ({ n: '\n', r: '\r', t: '\t', b: '\b', f: '\f', '(': '(', ')': ')', '\\': '\\' }[g] ?? String.fromCharCode(parseInt(g, 8)))); }
function contentToLines(cs) {
  const lines = []; let y = 0, cur = '', curY = null; const flush = () => { if (cur.trim()) lines.push({ y: curY, t: cur.trim() }); cur = ''; };
  const tok = /\((?:\\.|[^\\)])*\)|\[(?:\((?:\\.|[^\\)])*\)|[^\]])*\]|<[0-9A-Fa-f\s]*>|[-+]?\d*\.?\d+|\/[^\s/<>\[\]()]+|[A-Za-z'"*]+/g; const stack = []; let m; let hex = 0;
  while ((m = tok.exec(cs))) {
    const s = m[0];
    if (/^[-+]?\d*\.?\d+$/.test(s)) { stack.push(parseFloat(s)); continue; }
    if (s[0] === '(' || s[0] === '[' || s[0] === '<' || s[0] === '/') { stack.push(s); continue; }
    if (s === 'Td' || s === 'TD') { const dy = stack[stack.length - 1]; if (typeof dy === 'number') { if (dy !== 0) { flush(); y += dy; } else cur += ' '; } }
    else if (s === 'Tm') { const ny = stack[stack.length - 1]; if (typeof ny === 'number' && ny !== y) { flush(); y = ny; } }
    else if (s === 'T*' || s === "'" || s === '"') { flush(); y -= 1; if (s !== 'T*' && typeof stack[stack.length - 1] === 'string') cur += pdfString(stack[stack.length - 1].slice(1, -1)); }
    else if (s === 'Tj') { const a = stack[stack.length - 1]; if (typeof a === 'string') { if (a[0] === '<') hex++; else cur += pdfString(a.slice(1, -1)); } if (curY == null) curY = y; }
    else if (s === 'TJ') { const a = stack[stack.length - 1]; if (typeof a === 'string') { const parts = a.match(/\((?:\\.|[^\\)])*\)|-?\d+\.?\d*|<[0-9A-Fa-f\s]*>/g) || []; parts.forEach(pp => { if (pp[0] === '(') cur += pdfString(pp.slice(1, -1)); else if (pp[0] === '<') hex++; else if (parseFloat(pp) < -180) cur += ' '; }); } if (curY == null) curY = y; }
    if (/^[A-Za-z'"*]+$/.test(s)) { stack.length = 0; if (s === 'ET' || s === 'BT') { flush(); curY = null; } }
    if (s !== 'Td' && s !== 'TD' && s !== 'Tm') { /* keep curY */ }
    if (cur && curY == null) curY = y;
    if (!cur) curY = null;
  }
  flush(); return { lines, hex };
}
function ascii85(u8) {
  let s = ''; for (let i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
  s = s.replace(/^\s*<~/, '').replace(/~>[\s\S]*$/, '').replace(/\s+/g, ''); const out = []; let g = [];
  const flush = n => { let v = 0; for (let i = 0; i < 5; i++) v = v * 85 + (g[i] == null ? 84 : g[i]); const bytes = [(v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255]; for (let i = 0; i < n; i++) out.push(bytes[i]); };
  for (const ch of s) { if (ch === 'z' && !g.length) { out.push(0, 0, 0, 0); continue; } g.push(ch.charCodeAt(0) - 33); if (g.length === 5) { flush(4); g = []; } }
  if (g.length > 1) flush(g.length - 1);
  return new Uint8Array(out);
}
async function decodeStream(data, dict) {
  const m = dict.match(/\/Filter\s*(\[[^\]]*\]|\/\w+)/); if (!m) return data;
  const filters = m[1].match(/\/\w+/g) || [];
  for (const f of filters) { if (f === '/ASCII85Decode' || f === '/A85') data = ascii85(data); else if (f === '/FlateDecode' || f === '/Fl') data = await inflate(data, 'deflate'); else throw new Error('unsupported filter ' + f); }
  return data;
}
async function parsePdf(buf) {
  const b = new Uint8Array(buf); let bin = ''; for (let i = 0; i < b.length; i += 0x8000) bin += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  const re = /(?<!end)stream\r?\n/g; let m; const pages = []; let hexTotal = 0;
  while ((m = re.exec(bin))) {
    const start = m.index + m[0].length; const end = bin.indexOf('endstream', start); if (end < 0) break;
    const dict = bin.slice(Math.max(0, m.index - 400), m.index); const dictStart = dict.lastIndexOf('obj'); const d = dictStart >= 0 ? dict.slice(dictStart) : dict;
    let data = b.subarray(start, end); re.lastIndex = end;
    try { data = await decodeStream(data, d); } catch (e) { continue; }
    let cs = ''; for (let i = 0; i < data.length; i++) cs += String.fromCharCode(data[i]);
    if (!/\bBT\b/.test(cs)) continue;
    const { lines, hex } = contentToLines(cs); hexTotal += hex; if (!lines.length) continue;
    const gaps = []; for (let i = 1; i < lines.length; i++) gaps.push(Math.abs(lines[i - 1].y - lines[i].y)); gaps.sort((x, y) => x - y); const med = gaps.length ? (gaps[gaps.length >> 1] || 1) : 1;
    const paras = []; let cur = '';
    lines.forEach((ln, i) => { const gap = i ? Math.abs(lines[i - 1].y - ln.y) : 0; if (i && gap > med * 1.5 && cur) { paras.push(cur); cur = ''; } cur += (cur ? ' ' : '') + ln.t; });
    if (cur) paras.push(cur); pages.push(paras.join('\n\n'));
  }
  return { text: pages.join('\f'), hex: hexTotal };
}
async function parseFile(file) {
  const name = file.name || 'file'; const ext = (name.split('.').pop() || '').toLowerCase();
  if (!ALLOWED_EXT.includes(ext)) return { ok: false, error: 'Unsupported file type. Use PDF, DOCX or TXT.' };
  if (file.size > MAX_FILE) return { ok: false, error: 'File is larger than the 8 MB limit.' };
  if (file.size === 0) return { ok: false, error: 'The file is empty.' };
  try {
    if (ext === 'txt' || ext === 'md') return { ok: true, text: await file.text(), extractor: 'txt', mime: 'text/plain' };
    const buf = await file.arrayBuffer();
    if (ext === 'docx') return { ok: true, text: await parseDocx(buf), extractor: 'docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' };
    const r = await parsePdf(buf); const note = r.text.replace(/\s/g, '').length < 20 ? 'No text layer found. Scanned or image-only PDFs need the OCR adapter in the backend build.' : (r.hex > 20 ? 'Some text uses embedded font encodings that this browser extractor cannot read.' : '');
    return { ok: true, text: r.text, extractor: 'pdf-basic', mime: 'application/pdf', note };
  } catch (e) { return { ok: false, error: 'This file could not be read. Try TXT or DOCX, or paste the text.' }; }
}
