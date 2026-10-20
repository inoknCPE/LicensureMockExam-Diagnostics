const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'test-bank.html'), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];

function page(role = 'EXAMINER') {
    const elements = new Map();
    const node = id => {
        if (!elements.has(id)) elements.set(id, {
            value: '', innerHTML: '', disabled: false, opened: false,
            reset() {}, showModal() { this.opened = true; },
            close() { this.opened = false; }, addEventListener() {}
        });
        return elements.get(id);
    };
    for (const id of ['filter-domain', 'filter-diff', 'filter-cog']) node(id).value = 'All';
    const items = [
        { id: 'CPE-1', source: 'local', q: 'Local question', opts: ['A', 'B', 'C', 'D'],
            ans: 1, domain: 'Networking Fundamentals', cognitive: 'Remember', difficulty: 'Easy' },
        { id: 'QB-1', source: 'imported', q: 'Imported question', opts: ['A', 'B'],
            ans: 0, domain: 'Networking Fundamentals', cognitive: 'Remember', difficulty: 'Easy' }
    ];
    const calls = [];
    const context = vm.createContext({
        document: { getElementById: node, addEventListener() {} },
        CpedleDB: {
            getCurrentUser: () => ({ role }), getQuestions: () => items,
            saveQuestion: async data => { calls.push(['save', data]); return { pending: role === 'EXAMINER' }; },
            deleteQuestion: async id => { calls.push(['delete', id]); return { pending: role === 'EXAMINER' }; },
            bulkImport: async data => { calls.push(['import', data]); return { pending: data.length }; }
        },
        escapeHtml: value => String(value ?? ''),
        confirmActionDialog: async () => true, alert: () => {}, console
    });
    vm.runInContext(script, context);
    return { context, node, calls };
}

test('test bank offers edit and delete controls for local and imported QB items', () => {
    const { context, node } = page();
    vm.runInContext('renderTable()', context);
    const rows = node('bank-table-body').innerHTML;
    assert.match(rows, /data-action="edit" data-id="CPE-1"/);
    assert.match(rows, /data-action="delete" data-id="CPE-1"/);
    assert.match(rows, /data-action="edit" data-id="QB-1"/);
    assert.match(rows, /data-action="delete" data-id="QB-1"/);
    vm.runInContext("openItemModal('CPE-1')", context);
    assert.equal(node('item-modal').opened, true);
    assert.equal(node('item-q').value, 'Local question');
    vm.runInContext("openItemModal('QB-1')", context);
    assert.equal(node('item-q').value, 'Imported question');
    assert.equal(node('item-choice-count').value, '2');
});

test('examiner add, edit, delete, and bulk import invoke approval-aware APIs', async () => {
    const { context, node, calls } = page();
    node('item-q').value = 'New question';
    [0, 1, 2, 3].forEach(index => { node(`item-opt${index}`).value = `Option ${index}`; });
    node('item-ans').value = '1';
    node('item-diff').value = 'Easy';
    node('item-cog').value = 'Remember';
    node('item-domain').value = 'Networking Fundamentals';
    await vm.runInContext('saveItem({ preventDefault() {} })', context);
    assert.equal(calls[0][0], 'save');
    assert.equal(calls[0][1].id, null);
    node('item-id').value = 'CPE-1';
    await vm.runInContext('saveItem({ preventDefault() {} })', context);
    assert.equal(calls[1][1].id, 'CPE-1');
    await vm.runInContext("deleteItem('CPE-1')", context);
    assert.deepEqual(calls[2], ['delete', 'CPE-1']);
    context.importEvent = { target: { files: [{ text: async () => '[{"q":"Imported"}]' }], value: 'items.json' } };
    await vm.runInContext('handleBulkImport(importEvent)', context);
    assert.equal(calls[3][0], 'import');
    assert.equal(calls[3][1][0].q, 'Imported');
});
