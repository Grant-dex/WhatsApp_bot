const express = require('express');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const path = require('path');
const sendResult = require('./lib/send-result');

let makeWASocket, useMultiFileAuthState, DisconnectReason;

const BRIDGE_PORT = parseInt(process.env.BRIDGE_PORT || '3001');
const BRIDGE_HOST = process.env.BRIDGE_HOST || '127.0.0.1';
const PYTHON_API = process.env.PYTHON_API || 'http://127.0.0.1:8000';
const DATA_DIR = process.env.WHATSAPP_BOT_DATA_DIR || path.join(__dirname, '..');
const AUTH_DIR = path.join(DATA_DIR, 'data', '.baileys-auth');
const TENANT_ID = process.env.WA_TENANT_ID || '';
const TENANT_HEADERS = TENANT_ID ? { 'X-Tenant-Id': TENANT_ID } : {};

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

async function notifyPython(path, body, options = {}) {
    const retries = Math.max(0, options.retries || 0);
    for (let attempt = 0; attempt <= retries; attempt++) {
        try {
            const r = await fetch(`${PYTHON_API}${path}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...TENANT_HEADERS },
                body: JSON.stringify(body)
            });
            if (r.ok) return true;
        } catch (e) { /* ignore - Python may not be up yet */ }
        if (attempt < retries) {
            await new Promise(resolve => setTimeout(resolve, 500 * Math.pow(2, attempt)));
        }
    }
    return false;
}

async function sendText(phone, message, timeoutMs = 15000) {
    if (!clientReady || !sock) {
        return sendResult.failedResult('桥接未认证，请先扫码登录 WhatsApp', 'bridge_unauthenticated');
    }
    const cleaned = sendResult.cleanPhone(phone);
    if (!cleaned) {
        return sendResult.failedResult('清理后电话号码为空', 'invalid_phone');
    }
    const jid = cleaned.includes('@') ? cleaned : `${cleaned}@s.whatsapp.net`;
    try {
        const sent = await Promise.race([
            sock.sendMessage(jid, { text: message }),
            sendResult.timeoutPromise(timeoutMs),
        ]);
        return sendResult.sentResult(sent, jid);
    } catch (e) {
        const result = sendResult.fromSendError(e);
        if (result.error_code === 'timeout') {
            const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
            result.error = proxy
                ? `消息发送超时（结果待确认）。已配置代理 ${proxy}，请检查代理与 WhatsApp 连接后人工核对。`
                : '消息发送超时（结果待确认）。未配置代理，请检查网络后人工核对。';
        }
        return result;
    }
}

async function forwardToPython(phone, body, msgId, timestamp) {
    try {
        const r = await fetch(`${PYTHON_API}/webhook/message`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...TENANT_HEADERS },
            body: JSON.stringify({ from: phone, body, msg_id: msgId || null, timestamp: timestamp ? String(timestamp) : null })
        });
        const result = await r.json(); console.log("[webhook] response:", JSON.stringify(result));
        if (result.action === 'reply' && result.message) {
            const delivery = await sendText(phone, result.message, 15000);
            const receipt = {
                conversation_id: result.conversation_id || null,
                whatsapp_msg_id: delivery.message_id || null,
                status: delivery.status,
                error: delivery.error || null,
                error_code: delivery.error_code || null,
            };
            if (receipt.conversation_id) {
                const delivered = await notifyPython('/webhook/delivery', receipt, { retries: 3 });
                if (!delivered) console.error('[webhook] delivery receipt not acknowledged:', JSON.stringify(receipt));
            }
            console.log("[send] reply delivery status:", delivery.status);
            return { ...result, delivery_status: delivery.status };
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

// ── Follow-up message transformation ──────────────────────
// Hardcoded template from Python backend uses full name and fixed phrasing.
// We intercept and rewrite to use first name + varied human-like templates.

function getFirstName(fullName) {
    if (!fullName) return 'there';
    const parts = fullName.trim().split(/\s+/);
    let first = parts[0];
    // Skip titles: Mr., Mrs., Ms., Miss, Dr., Prof., Eng., Sir, Madam
    if (/^(Mr|Mrs|Ms|Miss|Dr|Prof|Eng|Sir|Madam)\.?$/i.test(first)) {
        first = parts.length > 1 ? parts[1] : first;
    }
    // Skip single-letter initials
    if (first.length <= 1 && parts.length > 1) {
        first = parts[1];
    }
    // Capitalize first letter
    return first.charAt(0).toUpperCase() + first.slice(1).toLowerCase();
}

const FOLLOWUP_VARIATIONS = [
    (firstName) => `Hi ${firstName}, hope you're having a great week! This is Grant from Tide Power. Just wanted to check in — is there anything I can help with regarding your power generation needs?`,
    (firstName) => `Hi ${firstName}, Grant here from Tide Power. Following up on our earlier conversation — let me know if you have any questions or would like more details on any of our gas generator solutions.`,
    (firstName) => `Hello ${firstName}, just a quick note from Grant at Tide Power. Wanted to see if you had any updates on your project, or if I can assist with anything at all.`,
    (firstName) => `Hi ${firstName}, hope all is well! Grant from Tide Power checking in. If you need technical specs, pricing, or just want to discuss options, I'm here to help.`,
    (firstName) => `Hi ${firstName}, this is Grant with Tide Power. I wanted to follow up and see if the information we shared was helpful — happy to go deeper on any topic or answer any questions.`,
    (firstName) => `Hello ${firstName}, Grant from Tide Power here. Just touching base to see how things are going with your project — let me know if you need anything at all.`,
    (firstName) => `Hi ${firstName}, hope your week is going well! This is Grant at Tide Power. Quick check-in — any thoughts on the generator options we discussed? I'm here if you need anything.`,
];

function transformFollowupMessage(message, phone) {
    // Match the Python backend's hardcoded followup template:
    // "Hi <Full Name>, this is <Owner> from <Company>. Just following up on our conversation - is there anything I can help you with?"
    const pattern = /^Hi\s+(.+?),\s+this is\s+\S+(?:\s+\S+)?\s+from\s+\S.+?\.\s+Just following up on our conversation\s*[-–—]\s*is there anything I can help you with\??\s*$/i;
    const match = message.match(pattern);
    if (!match) return message; // Not the hardcoded followup template — pass through

    const fullName = match[1].trim();
    const firstName = getFirstName(fullName);

    // Hash phone number to pick a consistent variation per customer
    let hash = 0;
    for (let i = 0; i < phone.length; i++) {
        hash = ((hash << 5) - hash) + phone.charCodeAt(i);
        hash |= 0;
    }
    const idx = Math.abs(hash) % FOLLOWUP_VARIATIONS.length;
    const transformed = FOLLOWUP_VARIATIONS[idx](firstName);
    console.log('[send] transformed followup:', fullName, '->', firstName, '| variant', idx);
    return transformed;
}

app.get('/health', (_, r) => r.json({ status: 'ok' }));
app.get('/chats', (_, r) => {
    const chatList = Array.from(contacts.values());
    r.json(chatList);
});
app.get('/status', (_, r) => r.json({ authenticated: clientReady, phone: sock?.user?.id?.split(':')[0] || null }));
app.post('/send', async (req, res) => {
    if (!clientReady || !sock) return res.status(503).json(sendResult.failedResult('桥接未认证，请先扫码登录 WhatsApp', 'bridge_unauthenticated'));
    let { phone, message } = req.body;
    if (!phone || !message) return res.status(400).json(sendResult.failedResult('电话号码和消息内容不能为空', 'invalid_request'));
    // ── Robust phone cleaning ──────────────────────────────
    const cleaned = sendResult.cleanPhone(phone);
    if (!cleaned) return res.status(400).json(sendResult.failedResult('清理后电话号码为空', 'invalid_phone'));
    phone = cleaned;
    // Transform hardcoded followup template → first name + varied human-like message
    message = transformFollowupMessage(message, phone);
    const jid = phone.includes('@') ? phone : `${phone}@s.whatsapp.net`;
    console.log('[send] cleaned phone:', phone, '-> jid:', jid);
    const result = await sendText(phone, message, 15000);
    // Always return 200 with a structured status so the Python backend can
    // distinguish sent / failed / unknown. Status codes are reserved for
    // definite request-level failures.
    res.json(result);
});

// ── Document sending ──────────────────────────────────────
app.post('/send-document', async (req, res) => {
    if (!clientReady || !sock) return res.status(503).json({ status: 'failed', error: '桥接未认证，请先扫码登录 WhatsApp' });
    let { phone, filename, mime_type, file_data_base64, caption } = req.body;
    if (!phone || !filename || !file_data_base64) {
        return res.status(400).json({ status: 'failed', error: '缺少必填字段：phone, filename, file_data_base64' });
    }
    // Same robust phone cleaning as /send
    phone = sendResult.cleanPhone(phone);
    if (!phone) return res.status(400).json({ status: 'failed', error: '清理后电话号码为空' });
    const jid = phone.includes('@') ? phone : `${phone}@s.whatsapp.net`;
    let fileBuffer;
    try {
        fileBuffer = Buffer.from(file_data_base64, 'base64');
    } catch (e) {
        return res.status(400).json({ status: 'failed', error: '文件数据编码无效' });
    }
    const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB WhatsApp limit
    if (fileBuffer.length > MAX_FILE_SIZE) {
        return res.status(400).json({ status: 'failed', error: `文件过大（${(fileBuffer.length/1024/1024).toFixed(1)}MB），超过50MB限制` });
    }
    console.log('[send-document] sending', filename, `(${(fileBuffer.length/1024).toFixed(1)}KB)`, 'to', jid);
    try {
        await Promise.race([
            sock.sendMessage(jid, {
                document: fileBuffer,
                mimetype: mime_type || 'application/pdf',
                fileName: filename
            }),
            new Promise((_, reject) => setTimeout(() => reject(new Error('send timeout')), 60000))
        ]);
        console.log('[send-document] done:', filename);
        res.json({ status: 'sent' });
    } catch (e) {
        let errorMsg = e.message || 'unknown';
        if (errorMsg === 'send timeout') {
            errorMsg = '文件发送超时（60秒）。文件可能过大或网络不稳定，请稍后重试。';
        }
        console.error('[send-document] failed:', errorMsg);
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
