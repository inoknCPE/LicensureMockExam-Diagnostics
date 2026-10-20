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
    let alertCalls = 0;
    let timerTick;
    const question = { q: 'Question', domain: 'Networking Fundamentals',
        questionType: 'identification', userAns: null, opts: [] };
    const exam = { mode, questions: [question], startedAt: Math.floor(Date.now() / 1000),
        timeSeconds: 3600, remainingSeconds: 3600 };
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, {
            style: {}, innerHTML: '', addEventListener(name, callback) { this[name + 'Handler'] = callback; },
            click() { this.clickHandler?.(); }, appendChild() {},
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
            const controls = new Map();
            return {
                style: {}, innerHTML: '', returnValue: '',
                setAttribute() {}, addEventListener(name, callback) { callbacks[name] = callback; },
                remove() {}, showModal() {},
                close(value) {
                    if (value !== undefined) this.returnValue = value;
                    if (callbacks.close) callbacks.close();
                },
                querySelector(selector) {
                    if (!controls.has(selector)) controls.set(selector, {
                        disabled: false, textContent: '', addEventListener(name, callback) { this[name] = callback; }, focus() {}
                    });
                    return controls.get(selector);
                }
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
        setInterval(callback) { timerTick = callback; return 1; }, clearInterval() {},
        alert() { alertCalls++; }, confirm() { return true; }
    });
    vm.runInContext(source, context);
    await listeners.DOMContentLoaded();
    return { document, listeners, dialogs, context, exam,
        submit: () => element('btn-next').click(),
        tick: () => timerTick(), getSubmitCalls: () => submitCalls, getAlertCalls: () => alertCalls };
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

for (const mode of ['student_practice', 'licensure']) {
    test(`${mode} asks before submitting unanswered questions and honors Cancel`, async () => {
        const app = await runExam(mode);
        app.submit();
        assert.equal(app.dialogs.length, 1);
        const canceled = app.dialogs[0];
        assert.equal(canceled.className, 'logout-dialog');
        assert.match(canceled.innerHTML, /You still have unanswered questions, are you sure you want to submit the exam\?/);
        assert.match(canceled.innerHTML, /No, Continue Exam/);
        assert.match(canceled.innerHTML, /Yes, Submit Exam/);
        assert.equal(app.getSubmitCalls(), 0);
        canceled.close('cancel');
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(app.getSubmitCalls(), 0);
        assert.equal(app.context.window.location.href, 'exam.html');

        app.submit();
        assert.equal(app.dialogs.length, 2);
        app.dialogs[1].close('confirm');
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(app.getSubmitCalls(), 1);
        assert.equal(app.context.window.location.href, 'results.html');
    });

    test(`${mode} submits without a warning when every question is answered`, async () => {
        const app = await runExam(mode);
        app.exam.questions[0].userAns = 'answer';
        app.submit();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(app.dialogs.length, 0);
        assert.equal(app.getSubmitCalls(), 1);
    });

    test(`${mode} expiry submits automatically and shows the styled scripture dialog`, async () => {
        const app = await runExam(mode);
        app.exam.remainingSeconds = 1;
        if (mode === 'licensure') app.exam.timeSeconds = 0;
        await app.tick();
        assert.equal(app.getSubmitCalls(), 1);
        assert.equal(app.getAlertCalls(), 0);
        assert.equal(app.dialogs.length, 1);
        const dialog = app.dialogs[0];
        assert.equal(dialog.className, 'logout-dialog time-expired-dialog');
        assert.match(dialog.innerHTML, /Time has expired, submitting your answers/);
        assert.match(dialog.innerHTML, /Proverbs 3:5-6/);
        assert.match(dialog.innerHTML, /Trust in the Lord with all your heart/);
        assert.equal(dialog.querySelector('button').disabled, false);
        assert.equal(app.context.window.location.href, 'exam.html');
        dialog.querySelector('button').click();
        assert.equal(app.context.window.location.href, 'results.html');
    });
}
