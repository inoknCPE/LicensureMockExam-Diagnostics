const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'profile.html'), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];

test('profile logo points to the dashboard allowed for each role', () => {
    const context = vm.createContext({ document: { addEventListener() {} } });
    vm.runInContext(script, context);
    assert.equal(vm.runInContext("profileHomeForRole('EXAMINER')", context), 'examiner-dashboard.html');
    assert.equal(vm.runInContext("profileHomeForRole('STUDENT')", context), 'examinee-dashboard.html');
    assert.equal(vm.runInContext("profileHomeForRole('ADMIN')", context), 'admin-dashboard.html');
    assert.match(html, /id="profile-logo"/);
});
