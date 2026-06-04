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
const contacts = new Map();
const MAX_CONTACTS = 10000;

function setContact(phone, data) {
    contacts.set(phone, data);
    // Evict oldest entries if over limit (Map maintains insertion order)
    while (contacts.size > MAX_CONTACTS) {
        const oldest = contacts.keys().next().value;
        contacts.delete(oldest);
    }
}
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
    const opts = { auth: state, printQRInTerminal: false, connectTimeoutMs: 60_000, browser: ['WhatsApp Bot', 'Chrome', '2.0.0'] };
    const agent = getProxyAgent(); if (agent) opts.agent = agent;
    sock = makeWASocket(opts);

    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('contacts.upsert', (items) => {
        for (const c of items) {
            const jid = c.id || c.jid || '';
            if (jid && !jid.endsWith('@g.us') && !jid.endsWith('@newsletter') && !jid.endsWith('@broadcast')) {
                const phone = jid.replace(/@s\.whatsapp\.net$/, '').replace(/@c\.us$/, '');
                const name = c.name || c.notify || c.verifiedName || '';
                setContact(phone, { phone, name });
            }
        }
    });
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
            const jid = m.key.remoteJid;
            if (jid && !jid.endsWith('@g.us') && !contacts.has(jid.replace(/@s\.whatsapp\.net$/, '').replace(/@c\.us$/, ''))) {
                const p = jid.replace(/@s\.whatsapp\.net$/, '').replace(/@c\.us$/, '');
                setContact(p, { phone: p, name: m.pushName || '' });
            }
            const text = m.message?.conversation || m.message?.extendedTextMessage?.text || '';
            if (!text.trim()) continue;
            console.log("[DEBUG] forwarding to", PYTHON_API); forwardToPython(m.key.remoteJid || 'unknown', text, m.key.id, m.messageTimestamp);
        }
    });
}

app.get('/health', (_, r) => r.json({ status: 'ok' }));
app.get('/chats', (_, r) => {
    const chatList = Array.from(contacts.values());
    r.json(chatList);
});
app.get('/status', (_, r) => r.json({ authenticated: clientReady, phone: sock?.user?.id?.split(':')[0] || null }));
app.post('/send', async (req, res) => {
    if (!clientReady || !sock) return res.status(503).json({ status: 'failed', error: '桥接未认证，请先扫码登录 WhatsApp' });
    let { phone, message } = req.body;
    if (!phone || !message) return res.status(400).json({ status: 'failed', error: '电话号码和消息内容不能为空' });
    phone = phone.replace(/^\+/, '');
    const jid = phone.includes('@') ? phone : `${phone}@s.whatsapp.net`;
    try {
        await Promise.race([
            sock.sendMessage(jid, { text: message }),
            new Promise((_, reject) => setTimeout(() => reject(new Error('send timeout')), 15000))
        ]);
        res.json({ status: 'sent' });
    } catch (e) {
        let errorMsg = e.message || 'unknown';
        // Provide actionable error messages
        if (errorMsg === 'send timeout') {
            const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
            if (proxy) {
                errorMsg = `消息发送超时（15秒）。已配置代理 ${proxy}，请检查：1) 代理是否正常运行 2) 代理地址和端口是否正确 3) WhatsApp 网络是否通畅`;
            } else {
                errorMsg = '消息发送超时（15秒）。未配置代理！国内网络可能无法直连 WhatsApp。请在桥接状态页面配置代理';
            }
        }
        // Return 200 so the Python backend reads the JSON body instead of throwing on status code
        res.json({ status: 'failed', error: errorMsg });
    }
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
    // Force-fetch WhatsApp contacts
app.post('/sync-contacts', async (_, r) => {
    if (!sock) return r.json({ok: false, error: 'not connected'});
    try {
        // Baileys stores contacts internally after sync
        const allContacts = [];
        if (sock.store && sock.store.contacts) {
            for (const [jid, contact] of Object.entries(sock.store.contacts)) {
                if (jid.endsWith('@s.whatsapp.net') || jid.endsWith('@c.us')) {
                    const phone = jid.replace(/@s\.whatsapp\.net$/, '').replace(/@c\.us$/, '');
                    setContact(phone, { phone, name: contact.name || contact.notify || contact.verifiedName || phone });
                    allContacts.push({ phone, name: contact.name || contact.notify || contact.verifiedName || phone });
                }
            }
        }
        r.json({ ok: true, count: allContacts.length, contacts: allContacts });
    } catch(e) { r.json({ ok: false, error: e.message }); }
});

app.listen(BRIDGE_PORT, BRIDGE_HOST, start);
})();
