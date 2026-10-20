const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'data.js'), 'utf8');

function createContext() {
    let dialog;
    const calls = [];
    const storage = new Map();
    const document = {
        addEventListener() {},
        body: { appendChild(element) { dialog = element; } },
        createElement() {
            const listeners = {};
            return {
                returnValue: '',
                setAttribute() {},
                addEventListener(name, callback) { listeners[name] = callback; },
                remove() {},
                showModal() {},
                querySelector() { return { focus() {} }; },
                closeWith(value) { this.returnValue = value; listeners.close(); }
            };
        }
    };
    const context = vm.createContext({
        document,
        window: { location: { href: 'admin-dashboard.html' } },
        sessionStorage: {
            getItem: key => storage.get(key) ?? null,
            setItem: (key, value) => storage.set(key, value),
            removeItem: key => storage.delete(key)
        },
        fetch: url => {
            calls.push(url);
            return Promise.resolve({ ok: true, json: async () => ({}) });
        },
        console,
        alert() {}
    });
    vm.runInContext(source, context);
    return { context, calls, getDialog: () => dialog };
}

test('canceling logout does not call the server or navigate', async () => {
    const { context, calls, getDialog } = createContext();
    const action = vm.runInContext('CpedleDB.logout()', context);
    getDialog().closeWith('cancel');
    await action;
    assert.equal(calls.filter(url => url.endsWith('/auth/logout')).length, 0);
    assert.equal(context.window.location.href, 'admin-dashboard.html');
});

test('confirming logout calls the server and returns to the home page', async () => {
    const { context, calls, getDialog } = createContext();
    const action = vm.runInContext('CpedleDB.logout()', context);
    getDialog().closeWith('confirm');
    await action;
    assert.equal(calls.filter(url => url.endsWith('/auth/logout')).length, 1);
    assert.equal(context.window.location.href, 'index.html');
});
