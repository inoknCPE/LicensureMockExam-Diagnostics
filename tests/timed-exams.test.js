const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'data.js'), 'utf8');

test('student practice receives a server deadline and saves answers before finalizing', async () => {
    const saved = new Map();
    const calls = [];
    const questions = [
        { id: 'QB-1', q: 'Network question', opts: ['A', 'B', 'C', 'D'],
            domain: 'Networking Fundamentals', cognitive: 'Remember', difficulty: 'Easy' },
        { id: 'QB-2', q: 'Security question', opts: ['A', 'B', 'C', 'D'],
            domain: 'Network Security', cognitive: 'Apply', difficulty: 'Medium' }
    ];
    const bootstrap = { user: { role: 'STUDENT', discipline: 'Network Engineer' },
        csrf: 'token', questions, history: [] };
    const context = vm.createContext({
        console, setTimeout, clearTimeout,
        sessionStorage: {
            getItem: key => saved.get(key) || null,
            setItem: (key, value) => saved.set(key, value),
            removeItem: key => saved.delete(key)
        },
        document: { addEventListener() {} },
        window: { location: { href: '' } },
        fetch: async (url, options = {}) => {
            calls.push({ url, options });
            let body = bootstrap;
            if (url === '/api/exams/practice/start') {
                body = { attemptId: 'server-attempt', startedAt: 1000, expiresAt: 2200,
                    serverNow: 1000, timeSeconds: 1200, title: 'Practice Exam' };
            } else if (url.endsWith('/answers')) {
                body = { saved: true, expiresAt: 2200 };
            } else if (url.endsWith('/submit')) {
                body = { id: 9, scorePct: 50, title: 'Practice Exam', totalItems: 2 };
            }
            return { ok: true, json: async () => body };
        }
    });
    vm.runInContext(source, context);
    await vm.runInContext('CpedleDB.ready', context);
    const exam = await vm.runInContext(`CpedleDB.startPracticeExam({
        count: 2, timeMinutes: 20, domains: ['Networking Fundamentals', 'Network Security'],
        easyPct: 50, medPct: 50, hardPct: 0
    })`, context);
    assert.equal(exam.attemptId, 'server-attempt');
    assert.equal(exam.expiresAt, 2200);
    const stored = JSON.parse(saved.get('cpedle_active_exam'));
    stored.questions[0].userAns = 1;
    context.changedExam = stored;
    vm.runInContext('CpedleDB.saveActiveExamState(changedExam)', context);
    await vm.runInContext('CpedleDB.finalizeExam()', context);
    const answerCall = calls.find(call => call.url.endsWith('/answers'));
    const submitCall = calls.find(call => call.url.endsWith('/submit'));
    assert.ok(answerCall);
    assert.ok(submitCall);
    assert.ok(calls.indexOf(answerCall) < calls.indexOf(submitCall));
    assert.equal(JSON.parse(answerCall.options.body).answers[0].userAns, 1);
    assert.equal(saved.has('cpedle_active_exam'), false);
});
