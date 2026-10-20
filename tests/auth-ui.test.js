const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'auth-ui.js'), 'utf8');
const context = vm.createContext({});
vm.runInContext(source, context);
const accepts = password => vm.runInContext(
    'PASSWORD_RULES.every(([, check]) => check(' + JSON.stringify(password) + '))',
    context
);

test('password checklist matches the registration rules', () => {
    assert.equal(accepts('Valid@123'), true);
    assert.equal(accepts('lower@123'), false);
    assert.equal(accepts('UPPER123'), false);
    assert.equal(accepts('NoDigits!'), false);
    assert.equal(accepts('Ab@123'), false);
    assert.equal(accepts('LongPassword@123'), false);
});
