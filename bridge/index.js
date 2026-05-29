const express = require('express');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const path = require('path');

let makeWASocket, useMultiFileAuthState, DisconnectReason;

const BRIDGE_PORT = parseInt(process.env.BRIDGE_PORT || '3001');
const BRIDGE_HOST = process.env.BRIDGE_HOST || '127.0.0.1';
const PYTHON_API = process.env.PYTHON_API || 'http://127.0.0.1:8000';
const DATA_DIR = process.env.WHATSAPP_BOT_DATA_DIR || path.join(__dirname, '..');
const AUTH_DIR = path.join(DATA_DIR, 'data', '.baileys-auth');

const app = express();
app.use(express.json());

let sock = null, clientReady = false, isShutdown = false;
let reconnectAttempt = 0;
const BACKOFF_BASE = 2000, BACKOFF_MAX = 300_000;
let backoffTimer = null;

function resetBackoff() { reconnectAttempt = 0; if (backoffTimer) { clearTimeout(backoffTimer); backoffTimer = null; } }
function getBackoffDelay() {
    reconnectAttempt++;
    const d = Math.min(BACKOFF_BASE * Math.pow(2, reconnectAttempt - 1), BACKOFF_MAX);
    return Math.round(d * (1 + 0.25 * (Math.random() * 2 - 1)));
}
function getProxyAgent() {
    const u = process.env.HTTPS_PROXY || process.env.https_proxy;
    if (!u) return undefined;
    try { const { HttpsProxyAgent } = require('https-proxy-agent'); console.log(`Using proxy: ${u}`); return new HttpsProxyAgent(u); }
    catch (e) { console.error('Proxy agent failed:', e.message); return undefined; }
}

async function notifyPython(path, body) {
    try {
        await fetch(`${PYTHON_API}${path}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
    } catch (e) { /* ignore - Python may not be up yet */ }
}

async function forwardToPython(phone, body, msgId, timestamp) {
    try {
        const r = await fetch(`${PYTHON_API}/webhook/message`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ from: phone, body, msg_id: msgId || null, timestamp: timestamp ? String(timestamp) : null })
        });
        const result = await r.json(); console.log("[webhook] response:", JSON.stringify(result));
        if (result.action === 'reply' && result.message) {
            const jid = phone.includes('@') ? phone : `${phone}@s.whatsapp.net`;
            console.log("[send] sending to", jid); await sock.sendMessage(jid, { text: result.message }); console.log("[send] done");
        }
        return result;
    } catch (e) { console.error('[webhook] forward failed:', e.message, e.stack); return { action: 'ignore', reason: 'fetch failed' }; }
}

async function start() {
    const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
    const opts = { auth: state, printQRInTerminal: false, connectTimeoutMs: 60_000 };
    const agent = getProxyAgent(); if (agent) opts.agent = agent;
    sock = makeWASocket(opts);

    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (qr) {
            console.log('>>> QR_RECEIVED <<<'); console.log('RAW_QR:' + qr); qrcode.generate(qr, { small: true }); console.log('>>> QR_END <<<');
            notifyPython('/webhook/qr', { qr_text: qr });
        }
        if (connection === 'open') {
            resetBackoff(); clientReady = true; console.log(`WHATSAPP_READY:${sock.user?.id?.split(':')[0] || 'unknown'}`);
            notifyPython('/webhook/qr', { qr_text: null });
        }
        if (connection === 'close') {
            clientReady = false;
            const code = lastDisconnect?.error?.output?.statusCode;
            console.log(`WHATSAPP_DISCONNECTED:${code || lastDisconnect?.error?.message || 'unknown'}`);
            if (isShutdown) return;
            if (code === DisconnectReason.loggedOut) {
                try { fs.rmSync(AUTH_DIR, { recursive: true, force: true }); } catch (_) {}
                resetBackoff(); backoffTimer = setTimeout(start, 3000); return;
            }
            backoffTimer = setTimeout(start, getBackoffDelay());
        }
    });

    sock.ev.on('messages.upsert', async (msg) => {
        console.log("[DEBUG] upsert fired", msg.messages.length);
        if (isShutdown || !clientReady) return;
        for (const m of msg.messages) {
            if (!m.key || m.key.fromMe) continue;
            const text = m.message?.conversation || m.message?.extendedTextMessage?.text || '';
            if (!text.trim()) continue;
            console.log("[DEBUG] forwarding to", PYTHON_API); forwardToPython(m.key.remoteJid || 'unknown', text, m.key.id, m.messageTimestamp);
        }
    });
}

app.get('/health', (_, r) => r.json({ status: 'ok' }));
app.get('/status', (_, r) => r.json({ authenticated: clientReady, phone: sock?.user?.id?.split(':')[0] || null }));
app.post('/send', async (req, res) => {
    if (!clientReady || !sock) return res.status(503).json({ status: 'failed', error: 'not authenticated' });
    let { phone, message } = req.body;
    if (!phone || !message) return res.status(400).json({ status: 'failed', error: 'phone and message required' });
    phone = phone.replace(/^\+/, '');
    const jid = phone.includes('@') ? phone : `${phone}@s.whatsapp.net`;
    try {
        await Promise.race([
            sock.sendMessage(jid, { text: message }),
            new Promise((_, reject) => setTimeout(() => reject(new Error('send timeout')), 15000))
        ]);
        res.json({ status: 'sent' });
    } catch (e) { res.status(500).json({ status: 'failed', error: e.message }); }
});

['SIGINT', 'SIGTERM'].forEach(s => process.on(s, () => { isShutdown = true; resetBackoff(); if (sock) sock.end(undefined); process.exit(0); }));

async function loadBaileys() {
    const m = await import('@whiskeysockets/baileys');
    makeWASocket = m.makeWASocket;
    useMultiFileAuthState = m.useMultiFileAuthState;
    DisconnectReason = m.DisconnectReason;
}

(async () => {
    await loadBaileys();
    console.log(`Bridge listening on ${BRIDGE_HOST}:${BRIDGE_PORT}`);
    app.listen(BRIDGE_PORT, BRIDGE_HOST, start);
})();
