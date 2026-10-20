const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'admin-question-approvals.html'), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];

test('admin approval shows readable pending requests and uses the decision API', async () => {
    const list = { innerHTML: '' };
    const calls = [];
    const question = {
        id: 'CPE-TEST', q: 'What is the full form of OSI?',
        opts: ['Optical Service Implementation', 'Open Service Internet',
            'Open System Interconnection', 'Operating System Interface'],
        ans: 2, domain: 'Networking Fundamentals', cognitive: 'Remember',
        difficulty: 'Easy', explanation: 'The OSI reference model.'
    };
    const context = vm.createContext({
        document: { getElementById: () => list, addEventListener() {} },
        apiCall: async (url, options) => {
            calls.push([url, options]);
            return url === '/questions/change-requests'
                ? [{ id: 7, action: 'ADD', question, proposer: 'Examiner09' }] : { ok: true };
        },
        escapeHtml: value => String(value ?? ''),
        confirmActionDialog: async () => true,
        alert: () => {},
        console
    });
    vm.runInContext(script, context);
    await vm.runInContext('loadApprovals()', context);
    assert.match(list.innerHTML, /What is the full form of OSI\?/);
    assert.match(list.innerHTML, /C\. Open System Interconnection/);
    assert.match(list.innerHTML, /Explanation:<\/strong> The OSI reference model/);
    assert.match(list.innerHTML, /Submitted by Examiner09/);
    assert.doesNotMatch(list.innerHTML, /<pre>|payload_json/);
    await vm.runInContext('decideQuestion(7, true)', context);
    assert.equal(calls[1][0], '/admin/questions/change-requests/7/decision');
    assert.equal(calls[1][1].method, 'POST');
    assert.equal(JSON.parse(calls[1][1].body).approve, true);
});

test('admin sees the impact of a deletion request before approving it', async () => {
    const list = { innerHTML: '' };
    const context = vm.createContext({
        document: { getElementById: () => list, addEventListener() {} },
        apiCall: async () => [{ id: 8, action: 'DELETE', proposer: 'Examiner09',
            question: { q: 'Old question', opts: ['A', 'B', 'C', 'D'], ans: 0,
                domain: 'Networking Fundamentals', cognitive: 'Remember', difficulty: 'Easy' } }],
        escapeHtml: value => String(value ?? ''), console
    });
    vm.runInContext(script, context);
    await vm.runInContext('loadApprovals()', context);
    assert.match(list.innerHTML, /DELETE request/);
    assert.match(list.innerHTML, /remove the question from the live bank/);
});
