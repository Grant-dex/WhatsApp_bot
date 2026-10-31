'use strict';

// Pure helpers shared by the bridge send paths and its Node tests.
// Keeping result construction here makes "sent" vs "failed" vs "unknown"
// explicit and prevents a timeout from being reported as a definite failure.

const TIMEOUT_ERROR = 'send timeout';

function cleanPhone(raw) {
    if (!raw) return '';
    let phone = String(raw);
    phone = phone.replace(/[\u200B-\u200F\u2028-\u202E\u2060-\u2069\uFEFF\uFFF0-\uFFFF]/g, '');
    phone = phone.replace(/^\++/, '').replace(/\++$/, '');
    phone = phone.replace(/@lid$/, '').replace(/@c\.us$/, '').replace(/@s\.whatsapp\.net$/, '');
    phone = phone.replace(/[\s\-\(\)]/g, '');
    phone = phone.replace(/^[^\d]+/, '');
    return phone.trim();
}

function sentResult(result, jid) {
    return {
        status: 'sent',
        message_id: (result && result.key && result.key.id) || null,
        jid: (result && result.key && result.key.remoteJid) || jid || null,
    };
}

function failedResult(error, errorCode) {
    return {
        status: 'failed',
        message_id: null,
        error: typeof error === 'string' ? error : (error && error.message) || 'send failed',
        error_code: errorCode || 'send_failed',
    };
}

function unknownResult(error, errorCode) {
    return {
        status: 'unknown',
        message_id: null,
        error: typeof error === 'string' ? error : (error && error.message) || 'result unknown',
        error_code: errorCode || 'unknown',
    };
}

function isTimeoutError(error) {
    const message = (error && error.message) || String(error || '');
    return message === TIMEOUT_ERROR ||
        /timed?\s*out/i.test(message) ||
        (error && (error.code === 'ETIMEDOUT' || error.code === 'ESOCKETTIMEDOUT'));
}

function fromSendError(error) {
    // A timeout may happen after WhatsApp accepted the message. It must be
    // surfaced as unknown so Python does not blindly retry or mark success.
    if (isTimeoutError(error)) {
        return unknownResult('send timeout', 'timeout');
    }
    return failedResult(error, 'send_failed');
}

function timeoutPromise(ms, message) {
    return new Promise((_, reject) => setTimeout(() => reject(new Error(message || TIMEOUT_ERROR)), ms));
}

module.exports = {
    TIMEOUT_ERROR,
    cleanPhone,
    sentResult,
    failedResult,
    unknownResult,
    isTimeoutError,
    fromSendError,
    timeoutPromise,
};
