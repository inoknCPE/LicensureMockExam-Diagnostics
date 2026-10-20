const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const script = file => [...read(file).matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];

test('admin account page separates students and approved examiners without role editing', async () => {
    const html = read('admin-accounts.html');
    assert.match(html, /Registered Students/);
    assert.match(html, /Registered Examiners/);
    assert.doesNotMatch(html, /updateRole|\/admin\/users\/\$\{userId\}\/role/);
    const nodes = new Map();
    const node = id => {
        if (!nodes.has(id)) nodes.set(id, { innerHTML: '' });
        return nodes.get(id);
    };
    const context = vm.createContext({
        document: { addEventListener() {}, getElementById: node },
        escapeHtml: value => String(value ?? ''),
        apiCall: async path => {
            if (path === '/admin/users') return [
                { id: 2, role: 'STUDENT', name: 'Student Name', username: 'student01', email: 's@example.com', is_locked: 0 },
                { id: 3, role: 'EXAMINER', name: 'Examiner Name', username: 'examiner01', email: 'e@example.com',
                    professional_title: 'Licensed Teacher', license_number: 'PRC-12345', examiner_status: 'approved', is_locked: 1 }
            ];
            return [];
        }
    });
    vm.runInContext(script('admin-accounts.html'), context);
    await vm.runInContext('loadAccountsData()', context);
    assert.match(node('students-tbody').innerHTML, /Student Name/);
    assert.doesNotMatch(node('students-tbody').innerHTML, /Examiner Name/);
    assert.match(node('examiners-tbody').innerHTML, /Licensed Teacher/);
    assert.match(node('examiners-tbody').innerHTML, /PRC-12345/);
    assert.match(node('students-tbody').innerHTML, /lockUser\(2\)/);
    assert.match(node('examiners-tbody').innerHTML, /unlockUser\(3\)/);
});

for (const user of [
    { role: 'EXAMINER', name: 'Examiner Name', email: 'e@example.com', professionalTitle: 'Licensed Teacher', licenseNumber: 'PRC-12345' },
    { role: 'STUDENT', name: 'Student Name', email: 's@example.com', discipline: 'Network Engineer' }
]) {
    test(`${user.role} profile displays registered details as read-only`, async () => {
        let ready;
        const nodes = new Map();
        const node = id => {
            if (!nodes.has(id)) nodes.set(id, { value: '', hidden: true, required: false,
                appendChild() {}, addEventListener() {} });
            return nodes.get(id);
        };
        const context = vm.createContext({
            document: { addEventListener(event, callback) { if (event === 'DOMContentLoaded') ready = callback; },
                getElementById: node, createElement() { return {}; } },
            enforceRoleGuard: async () => {}, renderSessionNavigation() {},
            setupPasswordForm: () => ({ refresh() {} }),
            CpedleDB: { getCurrentUser: () => user },
            DISCIPLINES: { 'Network Engineer': [] }
        });
        vm.runInContext(script('profile.html'), context);
        await ready();
        assert.equal(node('prof-email').value, user.email);
        if (user.role === 'EXAMINER') {
            assert.equal(node('prof-title').value, user.professionalTitle);
            assert.equal(node('prof-license').value, user.licenseNumber);
            assert.equal(node('examiner-title-field').hidden, false);
        } else {
            assert.equal(node('prof-discipline-display').value, user.discipline);
            assert.equal(node('student-discipline-field').hidden, false);
        }
    });
}
