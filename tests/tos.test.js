const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'js', 'data.js'), 'utf8');
const session = new Map();
const context = vm.createContext({
    sessionStorage: {
        getItem: key => session.get(key) || null,
        setItem: (key, value) => session.set(key, value),
        removeItem: key => session.delete(key)
    },
    fetch: () => new Promise(() => {}),
    document: { addEventListener() {} },
    window: { location: { href: '' } },
    console
});
vm.runInContext(source, context);
const disciplines = vm.runInContext('DISCIPLINES', context);
const levels = ['Remember', 'Understand', 'Apply', 'Analyze'];
const difficulties = ['Easy', 'Medium', 'Hard'];
const bank = [];
for (const domains of Object.values(disciplines)) {
    for (const domain of domains) {
        for (const cognitive of levels) {
            for (const difficulty of difficulties) {
                for (let copy = 0; copy < 4; copy++) {
                    bank.push({ id: `Q${bank.length}`, q: 'Example', opts: [],
                        domain, cognitive, difficulty });
                }
            }
        }
    }
}
context.testBank = bank;
vm.runInContext("bankCache = testBank; sessionUser = { role: 'STUDENT', discipline: 'Network Engineer' }", context);

function planFor(domain, count, easyPct = 30, medPct = 50, hardPct = 20) {
    return vm.runInContext(`CpedleDB.getTosPlan(${JSON.stringify({
        domain, count, easyPct, medPct, hardPct
    })})`, context);
}

function examFor(domain, count, easyPct = 30, medPct = 50, hardPct = 20) {
    return vm.runInContext(`CpedleDB.generateExam(${JSON.stringify({
        domain, count, easyPct, medPct, hardPct, mode: 'mock'
    })})`, context);
}

test('every approved domain and cognitive blueprint totals 100%', () => {
    const blueprints = vm.runInContext('TOS_BLUEPRINT', context);
    for (const [discipline, config] of Object.entries(blueprints)) {
        assert.equal(config.domains.length, disciplines[discipline].length);
        assert.equal(config.domains.reduce((sum, value) => sum + value, 0), 100);
        assert.equal(config.cognitive.length, 4);
        assert.equal(config.cognitive.reduce((sum, value) => sum + value, 0), 100);
    }
});

test('20-item Network Engineer blueprint has exact whole-question margins', () => {
    const plan = planFor('Network Engineer', 20, 60, 30, 10);
    assert.deepEqual(Object.values(plan.domains), [3, 4, 5, 5, 3]);
    assert.deepEqual(Object.values(plan.cognitive), [3, 4, 7, 6]);
    assert.deepEqual(Object.values(plan.difficulty), [12, 6, 2]);
});

test('student mock meets domain, cognitive, and difficulty quotas together', () => {
    for (const [domain, count] of [['Network Engineer', 20],
        ['Networking Fundamentals', 23]]) {
        const exam = examFor(domain, count);
        assert.equal(exam.questions.length, count);
        assert.equal(new Set(exam.questions.map(item => item.id)).size, count);
        const actualDomains = {};
        const actualCognitive = {};
        const actualDifficulty = {};
        for (const item of exam.questions) {
            const discipline = Object.keys(disciplines).find(name =>
                disciplines[name].includes(item.domain));
            actualDomains[item.domain] = (actualDomains[item.domain] || 0) + 1;
            const cognitiveKey = `${discipline}|${item.cognitive}`;
            actualCognitive[cognitiveKey] = (actualCognitive[cognitiveKey] || 0) + 1;
            actualDifficulty[item.difficulty] = (actualDifficulty[item.difficulty] || 0) + 1;
        }
        for (const [axis, actual] of [['domains', actualDomains],
            ['cognitive', actualCognitive], ['difficulty', actualDifficulty]]) {
            for (const [key, target] of Object.entries(exam.tos[axis])) {
                assert.equal(actual[key] || 0, target, `${domain}: ${axis} ${key}`);
            }
        }
    }
});

test('student mock scopes are limited to the profile discipline', () => {
    const scopes = Array.from(vm.runInContext('studentExamScopes()', context));
    assert.deepEqual(scopes, ['Network Engineer', ...disciplines['Network Engineer']]);
    assert.throws(() => examFor('All', 20), /only create exams in your Network Engineer discipline/);
    assert.throws(() => examFor('Software Developer', 20), /only create exams in your Network Engineer discipline/);
    assert.throws(() => planFor('Operating System Fundamentals', 20), /only create exams in your Network Engineer discipline/);
    vm.runInContext("sessionUser = { role: 'STUDENT', discipline: 'Software Developer' }", context);
    assert.equal(examFor('Software Developer', 20).questions.length, 20);
    vm.runInContext("sessionUser = { role: 'STUDENT', discipline: 'Network Engineer' }", context);
});

test('mock generation refuses shortages instead of silently substituting items', () => {
    assert.throws(() => examFor('Network Security', 20, 0, 0, 100),
        /cannot meet these cognitive-level and difficulty quotas|cannot assemble this exact/);
    assert.throws(() => examFor('Network Engineer', 10), /more than 10 questions/);
    assert.throws(() => planFor('Network Engineer', 20, 50, 50, 50), /total 100%/);
});

test('architect students cannot start drills or reopen another discipline exam', () => {
    vm.runInContext("sessionUser = { role: 'STUDENT', discipline: 'Computer Systems Architect' }", context);
    try {
        assert.throws(() => examFor('Networking Fundamentals', 20), /only create exams/);
        assert.throws(() => vm.runInContext("CpedleDB.generateExam({ domain: 'Computer Systems Architect', mode: 'practice' })", context), /Practice drills are for guests/);
        const exam = examFor('Computer Systems Architect', 20);
        assert.ok(exam.questions.every(q => disciplines['Computer Systems Architect'].includes(q.domain)));
        assert.equal(vm.runInContext('CpedleDB.getActiveExam().totalItems', context), 20);
        session.set('cpedle_active_exam', JSON.stringify({ mode: 'mock', questions: [{ domain: 'Networking Fundamentals' }] }));
        assert.equal(vm.runInContext('CpedleDB.getActiveExam()', context), null);
        session.set('cpedle_active_exam', JSON.stringify({ mode: 'practice', questions: [{ domain: 'Memory Hierarchy and Cache' }] }));
        assert.equal(vm.runInContext('CpedleDB.getActiveExam()', context), null);
    } finally {
        vm.runInContext("sessionUser = { role: 'STUDENT', discipline: 'Network Engineer' }", context);
    }
});

test('practice generator offers checkboxes only for the architect profile domains', async () => {
    const handlers = [];
    const all = { checked: false, handlers: {}, addEventListener(event, handler) { this.handlers[event] = handler; } };
    const list = { children: [], replaceChildren() { this.children = []; },
        appendChild(item) { this.children.push(item); }, handlers: {},
        addEventListener(event, handler) { this.handlers[event] = handler; } };
    const doc = {
        addEventListener(event, handler) { if (event === 'DOMContentLoaded') handlers.push(handler); },
        getElementById(id) { return id === 'gen-all-domains' ? all :
            id === 'gen-domains-list' ? list : { addEventListener() {} }; },
        querySelectorAll(selector) {
            const boxes = list.children.map(label => label.children[0]);
            return selector.endsWith(':checked') ? boxes.filter(box => box.checked) : boxes;
        },
        createElement() { return { children: [], append(...items) { this.children.push(...items); } }; },
        createTextNode(value) { return { text: value }; }
    };
    const pageContext = vm.createContext({
        document: doc, window: { location: { search: '?domain=Networking%20Fundamentals' } },
        DISCIPLINES: disciplines, URLSearchParams,
        CpedleDB: { ready: Promise.resolve(), getCurrentUser: () => ({ role: 'STUDENT', discipline: 'Computer Systems Architect' }) }
    });
    const html = fs.readFileSync(path.join(__dirname, '..', 'generator.html'), 'utf8');
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
    vm.runInContext(scripts.at(-1)[1], pageContext);
    vm.runInContext('updateTosPreview = () => {}', pageContext);
    await handlers[0]();
    const boxes = list.children.map(label => label.children[0]);
    assert.deepEqual(boxes.map(box => box.value), Array.from(disciplines['Computer Systems Architect']));
    assert.ok(boxes.every(box => box.checked));
    assert.equal(all.checked, true);
    all.checked = false;
    all.handlers.change({ target: all });
    assert.ok(boxes.every(box => !box.checked));
    boxes[0].checked = true;
    boxes[2].checked = true;
    list.handlers.change();
    assert.equal(all.checked, false);
    assert.deepEqual(Array.from(vm.runInContext('selectedPracticeDomains()', pageContext)),
        [boxes[0].value, boxes[2].value]);
    boxes.forEach(box => { box.checked = true; });
    list.handlers.change();
    assert.equal(all.checked, true);
});

test('student practice can combine selected domains but cannot use another discipline', () => {
    const chosen = ['Networking Fundamentals', 'Network Security'];
    const exam = vm.runInContext(`CpedleDB.generateExam(${JSON.stringify({
        count: 12, timeMinutes: 20, domains: chosen,
        easyPct: 30, medPct: 50, hardPct: 20, mode: 'student_practice'
    })})`, context);
    assert.equal(exam.mode, 'student_practice');
    assert.equal(exam.questions.length, 12);
    assert.deepEqual(chosen.map(name => exam.questions.filter(q => q.domain === name).length), [6, 6]);
    assert.ok(exam.questions.every(q => chosen.includes(q.domain)));
    assert.throws(() => vm.runInContext(`CpedleDB.generateExam(${JSON.stringify({
        count: 12, timeMinutes: 20, domains: ['Networking Fundamentals', 'Memory Management'],
        mode: 'student_practice'
    })})`, context), /Choose one or more domains/);
    assert.throws(() => vm.runInContext(`CpedleDB.generateExam(${JSON.stringify({
        count: 1, timeMinutes: 20, domains: chosen, mode: 'student_practice'
    })})`, context), /every selected domain is represented/);
});

test('mixed-format questions use exactly one stable answer format per attempt', () => {
    const mixedBank = bank.map(q => ({ ...q, questionType: 'both', opts: ['A', 'B', 'C', 'D'] }));
    context.mixedBank = mixedBank;
    vm.runInContext('bankCache = mixedBank', context);
    try {
        const exam = vm.runInContext(`CpedleDB.generateExam({
            count: 12, timeMinutes: 20, domains: ['Networking Fundamentals'],
            mode: 'student_practice'
        })`, context);
        assert.ok(exam.questions.every(q => ['multiple_choice', 'identification'].includes(q.questionType)));
        assert.deepEqual(Array.from(vm.runInContext('CpedleDB.getActiveExam().questions.map(q => q.questionType)', context)),
            Array.from(exam.questions, q => q.questionType));
        // A pre-update attempt is converted once and saved, not rerolled on navigation.
        session.set('cpedle_active_exam', JSON.stringify({ mode: 'student_practice',
            selectedDomains: ['Networking Fundamentals'],
            questions: [{ domain: 'Networking Fundamentals', questionType: 'both', opts: ['A', 'B'] }] }));
        const converted = vm.runInContext('CpedleDB.getActiveExam().questions[0].questionType', context);
        assert.ok(['multiple_choice', 'identification'].includes(converted));
        assert.equal(vm.runInContext('CpedleDB.getActiveExam().questions[0].questionType', context), converted);
        assert.equal(vm.runInContext("chooseQuestionFormat({ questionType: 'both', opts: ['A'], userAns: 0 }).questionType", context),
            'multiple_choice');
        assert.equal(vm.runInContext("chooseQuestionFormat({ questionType: 'both', opts: ['A'], userAns: 'written' }).questionType", context),
            'identification');
        vm.runInContext('CpedleDB.discardActiveExam()', context);
        assert.equal(session.has('cpedle_active_exam'), false);
    } finally {
        vm.runInContext('bankCache = testBank', context);
    }
});
