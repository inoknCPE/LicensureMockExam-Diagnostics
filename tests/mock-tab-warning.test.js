const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'exam-demo.js'), 'utf8');

async function runExam(mode) {
    const listeners = {};
    const dialogs = [];
    let submitCalls = 0;
    const question = { q: 'Question', domain: 'Networking Fundamentals',
        questionType: 'identification', userAns: null, opts: [] };
    const exam = { mode, questions: [question], startedAt: Math.floor(Date.now() / 1000),
        timeSeconds: 3600, remainingSeconds: 3600 };
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, {
            style: {}, innerHTML: '', addEventListener() {}, appendChild() {},
            closest() { return null; }, insertAdjacentElement() {}
        });
        return elements.get(id);
    };
    const document = {
        hidden: false,
        addEventListener(name, callback) { listeners[name] = callback; },
        getElementById(id) { return id === 'exam-palette' || id === 'question-image' ? null : element(id); },
        body: { appendChild(dialog) { dialogs.push(dialog); } },
        createElement(tag) {
            const callbacks = {};
            return {
                style: {}, innerHTML: '', returnValue: '',
                setAttribute() {}, addEventListener(name, callback) { callbacks[name] = callback; },
                remove() {}, showModal() {},
                close() { if (callbacks.close) callbacks.close(); },
                querySelector() { return { addEventListener() {}, focus() {} }; }
            };
        }
    };
    const context = vm.createContext({
        document, window: { location: { href: 'exam.html' } },
        CpedleDB: {
            ready: Promise.resolve(), getActiveExam: () => exam,
            getCurrentUser: () => ({ role: 'STUDENT' }), saveActiveExamState() {},
            async finalizeExam() { submitCalls++; }
        },
        setInterval() { return 1; }, clearInterval() {}, alert() {}, confirm() { return true; }
    });
    vm.runInContext(source, context);
    await listeners.DOMContentLoaded();
    return { document, listeners, dialogs, context, getSubmitCalls: () => submitCalls };
}

test('mock licensure exam warns on return from a hidden tab without submitting', async () => {
    const app = await runExam('licensure');
    app.document.hidden = true;
    app.listeners.visibilitychange();
    assert.equal(app.dialogs.length, 0);
    app.document.hidden = false;
    app.listeners.visibilitychange();
    assert.equal(app.dialogs.length, 1);
    assert.match(app.dialogs[0].innerHTML, /tab switching is strictly not allowed/i);
    assert.match(app.dialogs[0].innerHTML, /Galatians 6:7–8/);
    assert.match(app.dialogs[0].innerHTML, /A man reaps what he sows/);
    assert.equal(app.getSubmitCalls(), 0);
    assert.equal(app.context.window.location.href, 'exam.html');
    app.dialogs[0].close();
});

test('practice exam does not show the licensure tab-switch warning', async () => {
    const app = await runExam('student_practice');
    assert.equal(app.listeners.visibilitychange, undefined);
    assert.equal(app.dialogs.length, 0);
});
