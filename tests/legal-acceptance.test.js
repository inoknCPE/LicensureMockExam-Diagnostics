const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '..');

test('signup requires legal acceptance for either account type', () => {
    const html = fs.readFileSync(path.join(root, 'pages', 'signup.html'), 'utf8');
    assert.match(html, /id="legal-accept" required/);
    assert.match(html, /href="terms\.html"/);
    assert.match(html, /href="privacy\.html"/);
    assert.match(html, /requiredCheckboxIds: \['legal-accept'\]/);
    assert.match(html, /legalAccepted, legalAccepted/);
});

test('registration APIs receive explicit Terms acceptance and Privacy acknowledgement', async () => {
    const calls = [];
    const context = vm.createContext({
        document: { addEventListener() {} },
        console,
        sessionStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
        fetch: async (url, options = {}) => {
            calls.push({ url, options });
            const body = url === '/api/bootstrap'
                ? { user: { role: 'GUEST' }, questions: [], history: [] }
                : { message: 'Registration accepted' };
            return { ok: true, json: async () => body };
        }
    });
    vm.runInContext(fs.readFileSync(path.join(root, 'js', 'data.js'), 'utf8'), context);
    await vm.runInContext('CpedleDB.ready', context);
    await vm.runInContext(
        "CpedleDB.register('student123', 'student@example.com', 'Valid@123', 'Valid@123', true, true)",
        context
    );
    const registration = calls.find(call => call.url === '/api/auth/register');
    assert.deepEqual(JSON.parse(registration.options.body), {
        username: 'student123',
        email: 'student@example.com',
        password: 'Valid@123',
        confirm_password: 'Valid@123',
        accept_terms: true,
        acknowledge_privacy: true
    });
});

test('every page loads the shared footer links and exam setup pages link both notices', () => {
    const pages = fs.readdirSync(path.join(root, 'pages')).filter(name => name.endsWith('.html'));
    for (const page of pages) {
        const html = fs.readFileSync(path.join(root, 'pages', page), 'utf8');
        assert.match(html, /js\/legal-links\.js/, `${page} should load legal footer links`);
    }
    for (const page of ['generator.html', 'mock-exam.html', 'remediation.html', 'exam.html']) {
        const html = fs.readFileSync(path.join(root, 'pages', page), 'utf8');
        assert.match(html, /href="terms\.html"/, `${page} should link Terms`);
        assert.match(html, /href="privacy\.html"/, `${page} should link Privacy`);
    }
    const styles = fs.readFileSync(path.join(root, 'css', 'styles.css'), 'utf8');
    assert.match(styles, /#student-nav-bar :is\(a, button\)[\s\S]*?white-space:\s*nowrap/);
});
