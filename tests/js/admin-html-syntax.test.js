'use strict';

// Minimal syntax gate for the single inline admin script. This catches the
// template-literal/brace errors that otherwise only surface in the browser.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const htmlPath = path.join(__dirname, '..', '..', 'src', 'static', 'admin.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const externalScripts = [...html.matchAll(/<script src="\/assets\/([^"/]+\.js)"><\/script>/g)]
    .map(m => fs.readFileSync(path.join(path.dirname(htmlPath), 'assets', m[1]), 'utf8'));
const adminScript = [...scripts, ...externalScripts].join('\n');

test('admin.html inline scripts parse', () => {
    assert.ok(scripts.length >= 1, 'expected at least one inline script');
    // new Function compiles without executing DOM-dependent code.
    for (const script of [...scripts, ...externalScripts]) {
        assert.doesNotThrow(() => new Function(script));
    }
});

test('admin router suppresses self-triggered hashchange and has a load error fallback', () => {
    const htmlPath = path.join(__dirname, '..', '..', 'src', 'static', 'admin.html');
    const script = adminScript;

    // navigate() updates location.hash itself; without this guard the
    // hashchange listener calls navigate()/loadPage() a second time.
    assert.match(script, /expectedHashChange === location\.hash/);
    assert.match(script, /if \(location\.hash !== '#' \+ page\)/);
    // A failed page load must replace the spinner instead of leaving it forever.
    assert.match(script, /\[loadPage\]/);
    assert.match(script, /页面加载失败/);
});

test('a failed state request never keeps showing 运行中', () => {
    const htmlPath = path.join(__dirname, '..', '..', 'src', 'static', 'admin.html');
    const script = adminScript;

    // checkBotState used to swallow the error, leaving the previous (default)
    // "运行中" label in place — a dead backend looked healthy.
    assert.match(script, /后端不可达/);
    assert.match(script, /状态未知/);
    const botStateFn = script.slice(
        script.indexOf('async function checkBotState'),
        script.indexOf('async function toggleBotPause'),
    );
    assert.ok(botStateFn.length > 0, 'checkBotState not found');
    assert.doesNotMatch(botStateFn, /catch\s*\(\s*e\s*\)\s*\{\s*\}/,
        'an empty catch in checkBotState hides a failed state request');
});

test('setup state is unknown (not "configured") when the backend is unreachable', () => {
    const htmlPath = path.join(__dirname, '..', '..', 'src', 'static', 'admin.html');
    const script = adminScript;

    // Claiming configured=true on error hid the failure; callers now redirect
    // only on an explicit false.
    assert.match(script, /if \(configured === false\)/);
    assert.doesNotMatch(script, /setupConfigured = true; \/\/ don't block on error/);
});
