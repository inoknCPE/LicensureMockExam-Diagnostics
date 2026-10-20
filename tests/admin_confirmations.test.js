const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const dataSource = fs.readFileSync(path.join(root, 'js', 'data.js'), 'utf8');

function pageScript(file) {
    const html = fs.readFileSync(path.join(root, 'pages', file), 'utf8');
    return [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
}

test('admin action dialog matches the logout style and defaults to Cancel', async () => {
    let dialog;
    const document = {
        addEventListener() {},
        body: { appendChild(element) { dialog = element; } },
        createElement() {
            const listeners = {};
            const controls = new Map();
            return {
                returnValue: '', setAttribute() {}, remove() {}, showModal() {},
                addEventListener(name, handler) { listeners[name] = handler; },
                querySelector(selector) {
                    if (!controls.has(selector)) controls.set(selector, {
                        textContent: '', focused: false, focus() { this.focused = true; }
                    });
                    return controls.get(selector);
                },
                closeWith(value) { this.returnValue = value; listeners.close(); }
            };
        }
    };
    const context = vm.createContext({
        document, fetch: async () => ({ ok: true, json: async () => ({}) }), console,
        sessionStorage: { getItem() { return null; }, removeItem() {}, setItem() {} }
    });
    vm.runInContext(dataSource, context);
    const action = vm.runInContext(`confirmActionDialog({
        message: 'Are you sure you want to approve this examiner registration?',
        confirmLabel: 'Yes, Approve'
    })`, context);
    assert.equal(dialog.className, 'logout-dialog');
    assert.equal(dialog.querySelector('.logout-dialog__cancel').textContent, 'No, Cancel');
    assert.equal(dialog.querySelector('.logout-dialog__cancel').focused, true);
    assert.equal(dialog.querySelector('.logout-dialog__confirm').textContent, 'Yes, Approve');
    dialog.closeWith('cancel');
    assert.equal(await action, false);
});

test('canceling admin decisions never calls the API', async () => {
    for (const [file, action] of [
        ['admin-accounts.html', 'decideExaminer(12, true)'],
        ['admin-question-approvals.html', 'decideQuestion(7, false)']
    ]) {
        let calls = 0;
        const context = vm.createContext({
            document: { addEventListener() {} },
            confirmActionDialog: async () => false,
            requestRejectionReason: async () => null,
            apiCall: async () => { calls++; },
            console
        });
        vm.runInContext(pageScript(file), context);
        await vm.runInContext(action, context);
        assert.equal(calls, 0, file);
    }
});
