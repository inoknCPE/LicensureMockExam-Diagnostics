const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'data.js'), 'utf8');

test('new test-bank item omits the blank ID so the server can generate one', async () => {
    const calls = [];
    const context = vm.createContext({
        document: { addEventListener() {} },
        sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
        window: { location: { href: '' } },
        fetch: async (url, options) => {
            calls.push({ url, options });
            return { ok: true, json: async () => url.endsWith('/bootstrap')
                ? { user: { role: 'ADMIN' }, questions: [], history: [] }
                : { id: 'CPE-NEW' } };
        },
        console
    });
    vm.runInContext(source, context);
    const result = await vm.runInContext(`CpedleDB.saveQuestion({
        id: '', q: 'What does DNS resolve?', opts: ['Names', 'Voltages', 'Threads', 'Files'],
        ans: 0, domain: 'Networking Fundamentals', cognitive: 'Understand', difficulty: 'Easy'
    })`, context);
    assert.equal(result.id, 'CPE-NEW');
    const added = calls.find(call => call.url === '/api/questions');
    assert.ok(added);
    assert.equal(added.options.method, 'POST');
    assert.equal(JSON.parse(added.options.body).id, null);
});

test('API validation errors name the invalid field', async () => {
    const context = vm.createContext({
        document: { addEventListener() {} },
        fetch: async url => url.endsWith('/bootstrap')
            ? { ok: true, json: async () => ({ user: { role: 'GUEST' }, questions: [], history: [] }) }
            : { ok: false, json: async () => ({ detail: [{ loc: ['body', 'id'],
                msg: 'String should match pattern' }] }) },
        console
    });
    vm.runInContext(source, context);
    await assert.rejects(vm.runInContext("apiCall('/questions', { method: 'POST' })", context),
        /id: String should match pattern/);
});
