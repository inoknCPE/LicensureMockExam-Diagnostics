// Client-side feedback mirrors the server rules; the server remains authoritative.
const PASSWORD_RULES = [
    ['8–30 characters', value => value.length >= 8 && value.length <= 30],
    ['At least one letter (A–Z or a–z)', value => /[A-Za-z]/.test(value)],
    ['At least one uppercase letter', value => /[A-Z]/.test(value)],
    ['At least one number', value => /[0-9]/.test(value)],
    ['At least one special character', value =>
        [...value].some(char => "!@#$%^&*()_+-=[]{};:'\"\\|,.<>/?`~".includes(char))]
];

function setupPasswordForm({
    passwordId, confirmId, usernameId, emailId, showId, buttonId, requiredCheckboxIds = []
}) {
    const password = document.getElementById(passwordId);
    const confirm = document.getElementById(confirmId);
    const username = usernameId ? document.getElementById(usernameId) : null;
    const email = emailId ? document.getElementById(emailId) : null;
    const show = document.getElementById(showId);
    const button = document.getElementById(buttonId);
    const requiredCheckboxes = requiredCheckboxIds.map(id => document.getElementById(id));
    const tooltip = password.closest('.form-group').querySelector('.password-tooltip');

    function refresh() {
        const value = password.value;
        const rules = PASSWORD_RULES.map(([label, check]) => ({ label, passed: check(value) }));
        tooltip.replaceChildren();
        rules.forEach(rule => {
            const line = document.createElement('span');
            line.className = rule.passed ? 'rule-met' : 'rule-unmet';
            line.textContent = (rule.passed ? '✓ ' : '✕ ') + rule.label;
            tooltip.appendChild(line);
        });
        const validUser = !username || /^[A-Za-z0-9_]{8,30}$/.test(username.value.trim());
        const validEmail = !email || email.validity.valid && !!email.value.trim();
        button.disabled = !(rules.every(rule => rule.passed) &&
            confirm.value === value && !!confirm.value && validUser && validEmail &&
            requiredCheckboxes.every(checkbox => checkbox?.checked));
    }
    [password, confirm, username, email].filter(Boolean).forEach(field =>
        field.addEventListener('input', refresh));
    requiredCheckboxes.filter(Boolean).forEach(checkbox =>
        checkbox.addEventListener('change', refresh));
    show.addEventListener('change', () => {
        password.type = show.checked ? 'text' : 'password';
        confirm.type = show.checked ? 'text' : 'password';
    });
    refresh();
    return { refresh };
}
