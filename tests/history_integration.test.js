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
