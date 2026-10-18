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
vm.runInContext("bankCache = testBank; sessionUser = { role: 'STUDENT' }", context);

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
        ['Networking Fundamentals', 23], ['All', 60]]) {
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

test('mock generation refuses shortages instead of silently substituting items', () => {
    assert.throws(() => examFor('Network Security', 20, 0, 0, 100),
        /cannot meet these cognitive-level and difficulty quotas|cannot assemble this exact/);
    assert.throws(() => examFor('Network Engineer', 10), /more than 10 questions/);
    assert.throws(() => planFor('Network Engineer', 20, 50, 50, 50), /total 100%/);
});
