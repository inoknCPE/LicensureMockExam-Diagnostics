const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const data = fs.readFileSync(path.join(root, 'js/data.js'), 'utf8');

test('remediation uses the latest recorded result for each domain', () => {
    const context = vm.createContext({
        document: { addEventListener() {} }, console,
        fetch: async () => ({ ok: true, json: async () => ({ user: { role: 'GUEST' }, questions: [], history: [] }) }),
        sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} }
    });
    vm.runInContext(data, context);
    const history = [
        { domains: [{ name: 'Routing', scorePct: 80 }, { name: 'Security', scorePct: 40 }] },
        { domains: [{ name: 'Routing', scorePct: 20 }, { name: 'Security', scorePct: 30 }] }
    ];
    assert.deepEqual(Array.from(vm.runInContext('getRemediationDomains', context)(history)), ['Security']);
});

test('admin report loads the roster of all users rather than a missing endpoint', () => {
    const html = fs.readFileSync(path.join(root, 'pages', 'admin-reports.html'), 'utf8');
    assert.match(html, /apiCall\('\/admin\/reports\/roster'\)/);
    assert.match(html, /apiCall\('\/admin\/users'\)/);
    assert.match(html, /rpt-attempts-body/);
});

test('exam history can load and display an individual saved answer review', () => {
    const html = fs.readFileSync(path.join(root, 'pages', 'exam-history.html'), 'utf8');
    assert.match(html, /loadAnswerReview\(\$\{index\}, \$\{item\.id\}\)/);
    assert.match(html, /CpedleDB\.getExamReport\(examId\)/);
    assert.match(html, /Your answer:/);
    assert.match(html, /Correct answer:/);
    assert.match(html, /Could not load answer review:/);
});

test('saved exam report lookup is restricted to the current student', async () => {
    const calls = [];
    const context = vm.createContext({
        document: { addEventListener() {} }, console,
        sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
        fetch: async url => {
            calls.push(url);
            const body = url === '/api/bootstrap'
                ? { user: { role: 'STUDENT' }, questions: [], history: [] }
                : { questionReview: [] };
            return { ok: true, json: async () => body };
        }
    });
    vm.runInContext(data, context);
    await vm.runInContext('CpedleDB.ready', context);
    await vm.runInContext('CpedleDB.getExamReport(42)', context);
    assert.ok(calls.includes('/api/reports/exams/42'));
    const invalidLookup = await vm.runInContext(
        'CpedleDB.getExamReport("42").catch(error => error.message)', context);
    assert.equal(invalidLookup, 'A saved student exam report is required.');
});
