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
        "CpedleDB.generateExam({ domain: 'Network Engineer', count: 10, mode: 'practice' })", context);
    assert.ok(exam.questions.length > 0);
    assert.ok(exam.questions.every(q => q.domain === 'Networking Fundamentals'));
    assert.equal(new Set(exam.questions.map(q => q.id)).size, exam.questions.length);
    assert.match(exam.title, /Network Engineer/);
});

test('guest exams are practice-only and capped at ten questions', () => {
    assert.throws(() => vm.runInContext("CpedleDB.generateExam({ mode: 'mock' })", context),
        /Guests can only take practice drills/);
    const exam = vm.runInContext("CpedleDB.generateExam({ count: 50, mode: 'practice' })", context);
    assert.equal(exam.mode, 'practice');
    assert.ok(exam.questions.length <= 10);
    assert.match(exam.title, /Practice Drill/);
    for (const file of ['index.html', 'subjects.html']) {
        const html = fs.readFileSync(path.join(root, file), 'utf8');
        for (const match of html.matchAll(/<button[^>]*onclick="startMock\('[^']+'\)"[^>]*>/g)) {
            assert.match(match[0], /data-student-only hidden/, `${file} hides mock exams from guests`);
        }
    }
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

test('every admin page shows the same navigation tabs', () => {
    const pages = [
        'admin-dashboard.html', 'test-bank.html', 'admin-generator.html',
        'admin-requests.html', 'admin-accounts.html', 'admin-question-approvals.html'
    ];
    const expected = [
        'admin-dashboard.html', 'test-bank.html', 'admin-generator.html',
        'admin-requests.html', 'admin-accounts.html', 'admin-question-approvals.html'
    ];
    for (const file of pages) {
        const html = fs.readFileSync(path.join(root, file), 'utf8');
        const nav = html.match(/<div class="nav__options" id="admin-nav-bar">([\s\S]*?)<\/div>/);
        assert.ok(nav, `${file} has an admin navigation bar`);
        const links = Array.from(nav[1].matchAll(/<a\b[^>]*href="([^"]+)"/g), match => match[1]);
        assert.deepEqual(links, expected, `${file} should show every admin tab in order`);
    }
});

test('guest pages keep the same tabs and highlight their current page', () => {
    const pages = ['index.html', 'subjects.html', 'faq.html', 'signup.html', 'login.html'];
    const expected = [
        'index.html#how-it-works', 'subjects.html', 'faq.html',
        'signup.html', 'login.html'
    ];
    for (const file of pages) {
        const html = fs.readFileSync(path.join(root, file), 'utf8');
        const nav = html.match(/<div class="nav__options"[^>]*>([\s\S]*?)<\/div>/);
        assert.ok(nav, `${file} has a navigation bar`);
        const links = Array.from(nav[1].matchAll(/<a\b[^>]*href="([^"]+)"/g), match => match[1]);
        assert.deepEqual(links, expected, `${file} should keep all guest tabs in order`);
        const active = Array.from(nav[1].matchAll(/<a\b[^>]*href="([^"]+)"[^>]*aria-current="page"/g), match => match[1]);
        assert.deepEqual(active, [expected[pages.indexOf(file)]], `${file} should highlight its own tab`);
    }
    const home = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
    assert.match(home, /id="how-it-works"/);
});

test('public navigation reflects the actual server session', () => {
    const nav = { innerHTML: 'guest tabs' };
    context.navUnderTest = nav;
    vm.runInContext('renderSessionNavigation(navUnderTest)', context);
    assert.equal(nav.innerHTML, 'guest tabs');
    vm.runInContext("sessionUser = { role: 'STUDENT' }", context);
    vm.runInContext('renderSessionNavigation(navUnderTest)', context);
    assert.match(nav.innerHTML, /MOCK EXAMS/);
    assert.match(nav.innerHTML, /LOGOUT/);
    vm.runInContext("sessionUser = { role: 'GUEST', name: 'Guest Reviewee' }", context);
});

test('student pages highlight their own tab and navbar hover stays aligned', () => {
    const pages = [
        ['examinee-dashboard.html', 'examinee-dashboard.html'],
        ['generator.html', 'generator.html'],
        ['exam-history.html', 'exam-history.html']
    ];
    for (const [file, target] of pages) {
        const html = fs.readFileSync(path.join(root, file), 'utf8');
        assert.match(html, new RegExp(`href="${target}" aria-current="page"`), file);
    }
    const css = fs.readFileSync(path.join(root, 'css', 'styles.css'), 'utf8');
    assert.match(css, /\.nav__options :is\(a, button\):is\(:hover, :focus-visible, :active\)/);
    assert.doesNotMatch(css, /translate:\s*0 calc\(var\(--lerp/);
});

test('public JavaScript does not include seeded answer keys', () => {
    assert.doesNotMatch(source, /DEFAULT_TEST_BANK|\bans:\s*[0-3]\b/);
});
