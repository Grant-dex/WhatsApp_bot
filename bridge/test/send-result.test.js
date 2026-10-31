'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
    cleanPhone,
    sentResult,
    failedResult,
    unknownResult,
    isTimeoutError,
    fromSendError,
} = require('../lib/send-result');

test('cleanPhone strips invisible characters, suffixes and punctuation', () => {
    assert.equal(cleanPhone('+86 138-0000-0000'), '8613800000000');
    assert.equal(cleanPhone('+1 (555) 010-0001@s.whatsapp.net'), '15550100001');
    assert.equal(cleanPhone('\u200B8613800000000\u200E'), '8613800000000');
    assert.equal(cleanPhone('@lid'), '');
});

test('sentResult keeps the real platform message id', () => {
    const result = sentResult({
        key: {id: '3EB0ABCDEF', remoteJid: '8613800000000@s.whatsapp.net'},
    });
    assert.equal(result.status, 'sent');
    assert.equal(result.message_id, '3EB0ABCDEF');
    assert.equal(result.jid, '8613800000000@s.whatsapp.net');
});

test('timeouts are unknown, not failed', () => {
    assert.equal(isTimeoutError(new Error('send timeout')), true);
    assert.equal(isTimeoutError(new Error('ETIMEDOUT')), true);
    const result = fromSendError(new Error('send timeout'));
    assert.equal(result.status, 'unknown');
    assert.equal(result.error_code, 'timeout');
});

test('ordinary send errors are definite failures', () => {
    const result = fromSendError(new Error('invalid jid'));
    assert.equal(result.status, 'failed');
    assert.equal(result.error_code, 'send_failed');
});

test('failedResult and unknownResult do not claim a platform id', () => {
    assert.equal(failedResult('bad').message_id, null);
    assert.equal(unknownResult('maybe').message_id, null);
    assert.equal(failedResult('bad').status, 'failed');
    assert.equal(unknownResult('maybe').status, 'unknown');
});
