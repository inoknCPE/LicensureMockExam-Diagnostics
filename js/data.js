/** Computer Engineering frontend state; account and exam data come from the server. */

const STORAGE_KEYS = {
    ACTIVE_EXAM: 'cpedle_active_exam',
    GUEST_RESULT: 'cpedle_guest_result'
};

// Deficiency Rating Config
const PROFICIENCY_CONFIG = {
    DEFICIENT_MAX: 59,       // 0% - 59%  -> Deficient
    SATISFACTORY_MAX: 74,    // 60% - 74% -> Satisfactory
    PROFICIENT_MIN: 75       // 75% - 100%-> Proficient
};

// Computer Engineering taxonomy supplied by the project team.
const DISCIPLINES = {
    "Network Engineer": [
        "Networking Fundamentals",
        "Data Communications and Network Protocols",
        "Routing and Switching",
        "Network Security",
        "Wireless and Network Technologies"
    ],
    "Systems Operations Engineer": [
        "Operating System Fundamentals",
        "Process and Thread Management",
        "Memory Management",
        "File Systems and Storage",
        "I/O and System Management"
    ],
    "Computer Systems Architect": [
        "Computer Organization and Architecture Fundamentals",
        "CPU and Instruction Set Architecture",
        "Memory Hierarchy and Cache",
        "I/O and Peripheral Organization",
        "Computer Arithmetic and Performance"
    ],
    "Software Developer": [
        "Software Engineering Fundamentals",
        "Software Development Life Cycle",
        "Requirements Analysis and Specification",
        "Software Design and Architecture",
        "Software Testing and Maintenance"
    ],
    "Algorithm Engineer": [
        "Algorithm Analysis and Complexity",
        "Linear Data Structures",
        "Non-Linear Data Structures",
        "Sorting and Searching Algorithms",
        "Algorithm Design Techniques"
    ],
    "Digital Design Engineer": [
        "Boolean Algebra and Logic Gates",
        "Combinational Logic Circuits",
        "Sequential Logic Circuits",
        "Switching Theory and Logic Minimization",
        "Digital System Design"
    ]
};
const COGNITIVE_LEVELS = ["Remember", "Understand", "Apply", "Analyze"];
const DIFFICULTY_LEVELS = ["Easy", "Medium", "Hard"];

function populateTaxonomySelects() {
    document.querySelectorAll('select[data-taxonomy="domains"]').forEach(select => {
        const selected = select.value || select.dataset.selected || "";
        const first = select.querySelector('option[value="All"]');
        select.replaceChildren();
        if (first) select.appendChild(first);
        Object.entries(DISCIPLINES).forEach(([discipline, domains]) => {
            const group = document.createElement("optgroup");
            group.label = discipline;
            const disciplineOption = document.createElement("option");
            disciplineOption.value = discipline;
            disciplineOption.textContent = `All ${discipline} domains`;
            if (select.dataset.includeDisciplines === "true") group.appendChild(disciplineOption);
            domains.forEach(domain => {
                const option = document.createElement("option");
                option.value = domain;
                option.textContent = domain;
                group.appendChild(option);
            });
            select.appendChild(group);
        });
        if (selected && [...select.options].some(option => option.value === selected)) {
            select.value = selected;
        }
    });
}
document.addEventListener("DOMContentLoaded", populateTaxonomySelects);

let sessionUser = { role: 'GUEST', name: 'Guest Reviewee' };
let csrfToken = null;
let bankCache = [];
let requestCache = [];
let historyCache = [];

async function apiCall(path, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    if (csrfToken && options.method && options.method !== 'GET') {
        headers['X-CSRF-Token'] = csrfToken;
    }
    const response = await fetch('/api' + path, {
        credentials: 'same-origin',
        ...options,
        headers
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = body.detail;
        throw new Error(typeof detail === 'string' ? detail : 'Request failed. Please try again.');
    }
    return body;
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]
    );
}

// Public pages show the guest menu only when there is no authenticated session.
function renderSessionNavigation(navBar, activePage = '') {
    if (!navBar || sessionUser.role === 'GUEST') return;
    const menus = {
        ADMIN: [
            ['admin-dashboard.html', 'OVERVIEW'], ['test-bank.html', 'TEST BANK'],
            ['admin-generator.html', 'GENERATOR'], ['admin-requests.html', 'REQUESTS'],
            ['admin-accounts.html', 'ACCOUNTS'],
            ['admin-question-approvals.html', 'QUESTION APPROVALS']
        ],
        EXAMINER: [
            ['examiner-dashboard.html', 'DASHBOARD'], ['test-bank.html', 'TEST BANK'],
            ['profile.html', 'PROFILE']
        ],
        STUDENT: [
            ['examinee-dashboard.html', 'DASHBOARD'], ['subjects.html', 'MOCK EXAMS'],
            ['generator.html', 'GENERATOR'], ['exam-history.html', 'HISTORY']
        ]
    };
    const links = menus[sessionUser.role] || [];
    if (sessionUser.role === 'ADMIN') navBar.id = 'admin-nav-bar';
    navBar.innerHTML = links.map(([href, label]) =>
        `<a class="link" href="${href}"${href === activePage ? ' aria-current="page"' : ''}>${label}</a>`
    ).join('') + '<button class="link" onclick="CpedleDB.logout()">LOGOUT</button>';
}

function confirmLogout() {
    return new Promise(resolve => {
        const dialog = document.createElement('dialog');
        dialog.className = 'logout-dialog';
        dialog.setAttribute('aria-labelledby', 'logout-dialog-title');
        dialog.innerHTML = `
            <form method="dialog" class="logout-dialog__card">
                <svg class="logout-dialog__icon" viewBox="0 0 80 80" fill="none" aria-hidden="true">
                    <path d="M13 15h31a4 4 0 0 1 4 4v42a4 4 0 0 1-4 4H13a4 4 0 0 1-4-4V19a4 4 0 0 1 4-4Z" stroke="currentColor" stroke-width="2.5"/>
                    <path d="m16 19 28 7v37l-28-7V19Z" fill="#FFBFC2" stroke="currentColor" stroke-width="2.5"/>
                    <path d="M45 40h26m-9-9 9 9-9 9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <p id="logout-dialog-title">Oh no! You're leaving...<br>Are you sure?</p>
                <button type="submit" value="cancel" class="logout-dialog__cancel">No, Cancel</button>
                <button type="submit" value="confirm" class="logout-dialog__confirm">Yes, Log Me Out</button>
            </form>`;
        dialog.addEventListener('close', () => {
            resolve(dialog.returnValue === 'confirm');
            dialog.remove();
        }, { once: true });
        document.body.appendChild(dialog);
        dialog.showModal();
        dialog.querySelector('.logout-dialog__cancel').focus();
    });
}

async function refreshBootstrap() {
    const state = await apiCall('/bootstrap');
    sessionUser = state.user || { role: 'GUEST', name: 'Guest Reviewee' };
    csrfToken = state.csrf || null;
    bankCache = state.questions || [];
    requestCache = state.requests || [];
    historyCache = state.history || [];
    return state;
}

// Data and role decisions come from the localhost server, not localStorage.
const CpedleDB = {
    ready: null,
    getCurrentUser() { return sessionUser; },
    async login(identifier, password) {
        try {
            const result = await apiCall('/auth/login', {
                method: 'POST', body: JSON.stringify({ identifier, password })
            });
            await refreshBootstrap();
            return { success: true, user: result.user };
        } catch (error) {
            return { success: false, message: error.message,
                     code: /locked/i.test(error.message) ? 'account_locked' : null };
        }
    },
    async register(username, email, password, confirmPassword) {
        try {
            const result = await apiCall('/auth/register', {
                method: 'POST',
                body: JSON.stringify({
                    username, email, password, confirm_password: confirmPassword
                })
            });
            await refreshBootstrap();
            return { success: true, user: result.user };
        } catch (error) {
            return { success: false, message: error.message };
        }
    },
    async requestPasswordReset(identifier, password, confirmPassword) {
        return apiCall('/auth/reset-request', {
            method: 'POST',
            body: JSON.stringify({ identifier, password, confirm_password: confirmPassword })
        });
    },
    async saveProfile(name, discipline) {
        const result = await apiCall('/profile', {
            method: 'PUT', body: JSON.stringify({ name, discipline })
        });
        sessionUser = result.user;
        return result.user;
    },
    async changeOwnEmail(email, currentPassword) {
        const result = await apiCall('/profile/email', {
            method: 'PUT', body: JSON.stringify({ email, current_password: currentPassword })
        });
        sessionUser = result.user;
        return result.user;
    },
    async logout() {
        if (!await confirmLogout()) return;
        await this.ready;
        try {
            await apiCall('/auth/logout', { method: 'POST' });
            sessionStorage.removeItem(STORAGE_KEYS.ACTIVE_EXAM);
            sessionStorage.removeItem(STORAGE_KEYS.GUEST_RESULT);
            window.location.href = 'index.html';
        } catch (error) {
            alert('Could not log out. Please try again: ' + error.message);
        }
    },
    getQuestions() { return bankCache; },
    async saveQuestion(qData) {
        const exists = qData.id && bankCache.some(q => q.id === qData.id);
        const result = await apiCall(exists ? '/questions/' + encodeURIComponent(qData.id) : '/questions', {
            method: exists ? 'PUT' : 'POST', body: JSON.stringify(qData)
        });
        await refreshBootstrap();
        return result;
    },
    async deleteQuestion(id) {
        await apiCall('/questions/' + encodeURIComponent(id), { method: 'DELETE' });
        await refreshBootstrap();
    },
    async bulkImport(items) {
        const result = await apiCall('/questions/import', {
            method: 'POST', body: JSON.stringify(items)
        });
        await refreshBootstrap();
        return result;
    },
    getRequests() { return requestCache; },
    async submitRequest(req) {
        const result = await apiCall('/requests', {
            method: 'POST',
            body: JSON.stringify({
                title: req.title, domain: req.domain,
                difficulty: req.difficulty, notes: req.notes || ''
            })
        });
        await refreshBootstrap();
        return result;
    },
    async updateRequestStatus(id, status, adminComment = '') {
        await apiCall('/admin/requests/' + id, {
            method: 'PATCH', body: JSON.stringify({ status, admin_comment: adminComment })
        });
        await refreshBootstrap();
    },

    // Exam Engine & Generator
    generateExam({ count = 10, timeMinutes = 60, domain = 'All', easyPct = 30, medPct = 50, hardPct = 20, mode = 'mock' }) {
        if (sessionUser.role === 'GUEST') {
            if (mode !== 'practice') throw new Error('Guests can only take practice drills.');
            count = Math.min(count, 10);
        }
        const bank = this.getQuestions();
        const disciplineDomains = DISCIPLINES[domain];
        const pool = domain === 'All' ? [...bank] : bank.filter(q =>
            q.domain === domain || (disciplineDomains && disciplineDomains.includes(q.domain))
        );

        const targetEasy = Math.round((easyPct / 100) * count);
        const targetMed = Math.round((medPct / 100) * count);
        const targetHard = count - targetEasy - targetMed;

        const easyPool = pool.filter(q => q.difficulty.toLowerCase() === 'easy');
        const medPool = pool.filter(q => q.difficulty.toLowerCase() === 'medium');
        const hardPool = pool.filter(q => q.difficulty.toLowerCase() === 'hard');

        const shuffle = arr => [...arr].sort(() => 0.5 - Math.random());

        let selected = [];
        selected.push(...shuffle(easyPool).slice(0, targetEasy));
        selected.push(...shuffle(medPool).slice(0, targetMed));
        selected.push(...shuffle(hardPool).slice(0, targetHard));

        // If not enough matched by difficulty, fill remaining from overall pool
        if (selected.length < count) {
            const remaining = pool.filter(p => !selected.some(s => s.id === p.id));
            selected.push(...shuffle(remaining).slice(0, count - selected.length));
        }

        const examPayload = {
            id: 'EXAM-' + Date.now(),
            mode,
            title: mode === 'practice'
                ? (domain === 'All' ? 'Computer Engineering Practice Drill' : `${domain} Practice Drill`)
                : (domain === 'All' ? 'Computer Engineering Comprehensive Simulation' : `${domain} Targeted Mock`),
            totalItems: selected.length,
            timeSeconds: timeMinutes * 60,
            questions: selected.map(q => ({
                id: q.id,
                q: q.q,
                opts: q.opts,
                ansKey: q.ans,
                userAns: null,
                flagged: false,
                domain: q.domain,
                difficulty: q.difficulty,
                explanation: q.explanation || ''
            }))
        };

        sessionStorage.setItem(STORAGE_KEYS.ACTIVE_EXAM, JSON.stringify(examPayload));
        return examPayload;
    },

    getActiveExam() {
        const e = sessionStorage.getItem(STORAGE_KEYS.ACTIVE_EXAM);
        return e ? JSON.parse(e) : null;
    },

    saveActiveExamState(examData) {
        sessionStorage.setItem(STORAGE_KEYS.ACTIVE_EXAM, JSON.stringify(examData));
    },

    async finalizeExam() {
        const exam = this.getActiveExam();
        if (!exam || !exam.questions.length) return null;
        const persist = sessionUser.role === 'STUDENT' && exam.mode !== 'practice';
        const result = await apiCall(persist ? '/exams/submit' : '/exams/practice-score', {
            method: 'POST',
            body: JSON.stringify({
                title: exam.title,
                answers: exam.questions.map(q => ({ id: q.id, userAns: q.userAns }))
            })
        });
        if (persist) {
            await refreshBootstrap();
            sessionStorage.removeItem(STORAGE_KEYS.GUEST_RESULT);
        } else {
            result.date = new Date().toISOString().replace('T', ' ').substring(0, 16);
            // Anonymous practice: temporary tab result only, never a user or database row.
            sessionStorage.setItem(STORAGE_KEYS.GUEST_RESULT, JSON.stringify(result));
        }
        return result;
    },

    getExamHistory() {
        if (sessionUser.role === 'GUEST' || sessionUser.role === 'EXAMINER') {
            const item = sessionStorage.getItem(STORAGE_KEYS.GUEST_RESULT);
            return item ? [JSON.parse(item)] : [];
        }
        return historyCache;
    },
    getLatestResult() {
        const temporary = sessionStorage.getItem(STORAGE_KEYS.GUEST_RESULT);
        return temporary ? JSON.parse(temporary) : historyCache[0] || null;
    }
};

// Server-side page and API checks are authoritative; this only improves navigation.
async function enforceRoleGuard(allowedRoles = ['GUEST', 'STUDENT', 'EXAMINER', 'ADMIN']) {
    await CpedleDB.ready;
    const user = CpedleDB.getCurrentUser();
    if (!allowedRoles.includes(user.role)) {
        if (user.role === 'GUEST') {
            window.location.href = 'login.html';
        } else {
            window.location.href = 'index.html';
        }
    }
}

CpedleDB.ready = refreshBootstrap().catch(error => {
    console.error('Could not connect to the localhost backend:', error);
    return null;
});
