const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'admin-question-approvals.html'), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];

function node(tag) {
    return {
        tag, children: [], textContent: '', className: '', style: {},
        appendChild(child) { this.children.push(child); },
        replaceChildren() { this.children = []; },
        addEventListener() {}
    };
}

function walk(root) {
    return [root, ...root.children.flatMap(walk)];
}

test('admin approval renders a readable question instead of raw JSON', async () => {
    const list = node('div');
    const message = node('p');
    const question = {
        id: 'CPE-TEST', q: 'What is the full form of OSI?',
        opts: ['Optical Service Implementation', 'Open Service Internet',
            'Open System Interconnection', 'Operating System Interface'],
        ans: 2, domain: 'Networking Fundamentals', cognitive: 'Remember',
        difficulty: 'Easy', explanation: 'The OSI reference model.'
    };
    const context = vm.createContext({
        document: {
            createElement: node,
            createTextNode: text => ({ tag: '#text', textContent: text, children: [] }),
            getElementById: id => id === 'question-approval-list' ? list : message,
            addEventListener() {}
        },
        apiCall: async () => [{ id: 1, action: 'ADD', question,
            proposer: 'Examiner09', submitted_at: '2026-10-19 15:27:48' }],
        CpedleDB: { getQuestions: () => [] },
        console
    });
    vm.runInContext(script, context);
    await vm.runInContext('loadQuestionApprovals()', context);
    const elements = walk(list);
    assert.equal(elements.filter(item => item.tag === 'pre').length, 0);
    assert.ok(elements.some(item => item.textContent === question.q));
    assert.ok(elements.some(item => item.textContent === 'C.'));
    assert.ok(elements.some(item => item.textContent === '✓ Correct answer'));
    assert.ok(elements.some(item => item.textContent === 'Domain: Networking Fundamentals'));
    assert.ok(elements.some(item => item.textContent === 'Explanation: The OSI reference model.'));
    assert.deepEqual(elements.filter(item => item.tag === 'button').map(item => item.textContent),
        ['Approve', 'Reject']);
});
