const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'js', 'data.js'), 'utf8');
const storage = new Map();
const session = new Map();
const context = vm.createContext({
    localStorage: {
        getItem: key => storage.has(key) ? storage.get(key) : null,
        setItem: (key, value) => storage.set(key, value),
        removeItem: key => storage.delete(key)
    },
    sessionStorage: {
        getItem: key => session.has(key) ? session.get(key) : null,
        setItem: (key, value) => session.set(key, value),
        removeItem: key => session.delete(key)
    },
    fetch: () => new Promise(() => {}),
    document: { addEventListener() {} },
    window: { location: { href: '' } },
    console
});
vm.runInContext(source, context);
vm.runInContext(`bankCache = [{
    id: 'test-network', q: 'Example question', opts: ['A', 'B', 'C', 'D'],
    domain: 'Networking Fundamentals', cognitive: 'Remember', difficulty: 'Easy'
}]`, context);

test('all six disciplines have the five agreed domains', () => {
    const disciplines = vm.runInContext('DISCIPLINES', context);
    assert.deepEqual(Object.keys(disciplines), [
        'Network Engineer',
        'Systems Operations Engineer',
        'Computer Systems Architect',
        'Software Developer',
        'Algorithm Engineer',
        'Digital Design Engineer'
    ]);
    assert.equal(Object.values(disciplines).flat().length, 30);
    assert.ok(Object.values(disciplines).every(domains => domains.length === 5));
    assert.equal(new Set(Object.values(disciplines).flat()).size, 30);
});

test('cognitive levels, difficulties, and question metadata use the new taxonomy', () => {
    const levels = Array.from(vm.runInContext('COGNITIVE_LEVELS', context));
    const difficulties = Array.from(vm.runInContext('DIFFICULTY_LEVELS', context));
    assert.deepEqual(levels, ['Remember', 'Understand', 'Apply', 'Analyze']);
    assert.deepEqual(difficulties, ['Easy', 'Medium', 'Hard']);
    const disciplines = vm.runInContext('DISCIPLINES', context);
    const domains = Object.values(disciplines).flat();
    const questions = vm.runInContext('CpedleDB.getQuestions()', context);
    assert.ok(questions.every(q =>
        domains.includes(q.domain) && levels.includes(q.cognitive) && difficulties.includes(q.difficulty)));
});

test('discipline exams only use their own questions and do not repeat to fill the count', () => {
    const exam = vm.runInContext(
        "CpedleDB.generateExam({ domain: 'Network Engineer', count: 10 })", context);
    assert.ok(exam.questions.length > 0);
    assert.ok(exam.questions.every(q => q.domain === 'Networking Fundamentals'));
    assert.equal(new Set(exam.questions.map(q => q.id)).size, exam.questions.length);
    assert.match(exam.title, /Network Engineer/);
});

test('no frontend page still mentions Civil Engineering', () => {
    for (const file of fs.readdirSync(root).filter(name => name.endsWith('.html'))) {
        const html = fs.readFileSync(path.join(root, file), 'utf8');
        assert.doesNotMatch(html, /civil engineering|CELE|NSCP|geotechnical|hydraulics|surveying/i, file);
    }
});

test('inline page scripts remain valid JavaScript', () => {
    for (const file of fs.readdirSync(root).filter(name => name.endsWith('.html'))) {
        const html = fs.readFileSync(path.join(root, file), 'utf8');
        for (const match of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)) {
            assert.doesNotThrow(() => new vm.Script(match[1], { filename: file }), file);
        }
    }
});

test('local HTML links point to existing pages', () => {
    for (const file of fs.readdirSync(root).filter(name => name.endsWith('.html'))) {
        const html = fs.readFileSync(path.join(root, file), 'utf8');
        for (const [, target] of html.matchAll(/href=["']([^"']+\.html)(?:#[^"']*)?["']/g)) {
            assert.ok(fs.existsSync(path.join(root, target)), `${file} links to missing ${target}`);
        }
    }
});

test('public JavaScript does not include seeded answer keys', () => {
    assert.doesNotMatch(source, /DEFAULT_TEST_BANK|\bans:\s*[0-3]\b/);
});
