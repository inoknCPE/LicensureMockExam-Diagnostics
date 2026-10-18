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

// Draft TOS approved for this project. Domain weights follow DISCIPLINES order.
// The student chooses the item count and difficulty profile; these content and
// cognitive weights remain fixed until the project team revises the blueprint.
const TOS_BLUEPRINT = {
    "Network Engineer": { domains: [15, 20, 25, 25, 15], cognitive: [15, 20, 35, 30] },
    "Systems Operations Engineer": { domains: [15, 25, 25, 20, 15], cognitive: [15, 25, 35, 25] },
    "Computer Systems Architect": { domains: [20, 25, 25, 15, 15], cognitive: [15, 25, 30, 30] },
    "Software Developer": { domains: [15, 20, 20, 25, 20], cognitive: [15, 25, 35, 25] },
    "Algorithm Engineer": { domains: [20, 15, 20, 20, 25], cognitive: [15, 20, 35, 30] },
    "Digital Design Engineer": { domains: [15, 25, 25, 20, 15], cognitive: [20, 20, 35, 25] }
};
const DOMAIN_DISCIPLINE = Object.fromEntries(Object.entries(DISCIPLINES)
    .flatMap(([discipline, domains]) => domains.map(domain => [domain, discipline])));

// Largest-remainder allocation keeps every margin an integer and the total exact.
function allocateTosCounts(labels, weights, count) {
    const weightTotal = weights.reduce((sum, weight) => sum + weight, 0);
    if (!weightTotal || weights.some(weight => !Number.isFinite(weight) || weight < 0)) {
        throw new Error('Invalid TOS weights.');
    }
    const rows = labels.map((label, index) => {
        const exact = count * weights[index] / weightTotal;
        return { label, index, amount: Math.floor(exact), remainder: exact - Math.floor(exact) };
    });
    let left = count - rows.reduce((sum, row) => sum + row.amount, 0);
    for (const row of [...rows].sort((a, b) => b.remainder - a.remainder || a.index - b.index)) {
        if (left-- <= 0) break;
        row.amount++;
    }
    return Object.fromEntries(rows.map(row => [row.label, row.amount]));
}

function buildTosPlan({ count, domain, easyPct, medPct, hardPct }) {
    if (!Number.isInteger(count) || count < 1 || count > 200) {
        throw new Error('Choose a whole-number question count between 1 and 200.');
    }
    const difficultyWeights = [easyPct, medPct, hardPct];
    if (difficultyWeights.some(value => !Number.isFinite(value) || value < 0 || value > 100) ||
        difficultyWeights.reduce((sum, value) => sum + value, 0) !== 100) {
        throw new Error('Difficulty percentages must total 100%.');
    }
    const selectedDiscipline = DISCIPLINES[domain] ? domain : DOMAIN_DISCIPLINE[domain];
    if (domain !== 'All' && !selectedDiscipline) throw new Error('Select a valid discipline or domain.');
    const disciplines = domain === 'All' ? Object.keys(DISCIPLINES) : [selectedDiscipline];
    const disciplineCounts = allocateTosCounts(disciplines, disciplines.map(() => 1), count);
    const domainCounts = {};
    const cognitiveCounts = {};
    for (const discipline of disciplines) {
        const blueprint = TOS_BLUEPRINT[discipline];
        const disciplineCount = disciplineCounts[discipline];
        Object.assign(domainCounts, domain === 'All' || domain === discipline
            ? allocateTosCounts(DISCIPLINES[discipline], blueprint.domains, disciplineCount)
            : { [domain]: disciplineCount });
        const levelCounts = allocateTosCounts(COGNITIVE_LEVELS, blueprint.cognitive, disciplineCount);
        for (const level of COGNITIVE_LEVELS) {
            cognitiveCounts[`${discipline}|${level}`] = levelCounts[level];
        }
    }
    return {
        count, scope: domain, disciplines: disciplineCounts,
        domains: domainCounts, cognitive: cognitiveCounts,
        difficulty: allocateTosCounts(DIFFICULTY_LEVELS, difficultyWeights, count)
    };
}

// Standard bipartite max flow allocates integer quotas without sampling bias.
// It returns null when the available edges cannot satisfy both margins.
function allocateTosFlow(leftDemand, rightDemand, capacity, randomize = false) {
    const left = Object.keys(leftDemand).filter(key => leftDemand[key] > 0);
    const right = Object.keys(rightDemand).filter(key => rightDemand[key] > 0);
    const sink = left.length + right.length + 1;
    const graph = Array.from({ length: sink + 1 }, () => []);
    const tracked = [];
    const addEdge = (from, to, amount) => {
        const forward = { to, remaining: amount, reverse: graph[to].length };
        const backward = { to: from, remaining: 0, reverse: graph[from].length };
        graph[from].push(forward);
        graph[to].push(backward);
        return forward;
    };
    left.forEach((key, index) => addEdge(0, index + 1, leftDemand[key]));
    left.forEach((key, leftIndex) => {
        const neighbors = randomize ? [...right].sort(() => Math.random() - 0.5) : right;
        for (const rightKey of neighbors) {
            const available = capacity(key, rightKey);
            if (!available) continue;
            const rightIndex = right.indexOf(rightKey);
            const edge = addEdge(leftIndex + 1, left.length + rightIndex + 1, available);
            tracked.push({ left: key, right: rightKey, capacity: available, edge });
        }
    });
    right.forEach((key, index) => addEdge(left.length + index + 1, sink, rightDemand[key]));

    const total = left.reduce((sum, key) => sum + leftDemand[key], 0);
    let sent = 0;
    while (sent < total) {
        const parent = Array(graph.length).fill(null);
        const queue = [0];
        parent[0] = [-1, -1];
        for (let head = 0; head < queue.length && !parent[sink]; head++) {
            const from = queue[head];
            graph[from].forEach((edge, edgeIndex) => {
                if (edge.remaining > 0 && !parent[edge.to]) {
                    parent[edge.to] = [from, edgeIndex];
                    queue.push(edge.to);
                }
            });
        }
        if (!parent[sink]) return null;
        let amount = Infinity;
        for (let at = sink; at !== 0; at = parent[at][0]) {
            const [from, edgeIndex] = parent[at];
            amount = Math.min(amount, graph[from][edgeIndex].remaining);
        }
        for (let at = sink; at !== 0; at = parent[at][0]) {
            const [from, edgeIndex] = parent[at];
            const edge = graph[from][edgeIndex];
            edge.remaining -= amount;
            graph[at][edge.reverse].remaining += amount;
        }
        sent += amount;
    }
    return tracked.map(item => ({ left: item.left, right: item.right,
        count: item.capacity - item.edge.remaining })).filter(item => item.count > 0);
}

// First allocate cognitive × difficulty quotas, then place those cells across
// the weighted domains. Both stages respect real question-bank capacities.
function selectTosQuestions(pool, plan) {
    const groups = new Map();
    const separator = '\u001f';
    for (const question of pool) {
        const discipline = DOMAIN_DISCIPLINE[question.domain];
        if (!discipline || !COGNITIVE_LEVELS.includes(question.cognitive) ||
            !DIFFICULTY_LEVELS.includes(question.difficulty)) continue;
        const cognitive = `${discipline}|${question.cognitive}`;
        const key = [question.domain, cognitive, question.difficulty].join(separator);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(question);
    }
    const cognitiveDifficultyCapacity = (cognitive, difficulty) =>
        [...groups.entries()].reduce((sum, [key, questions]) => {
            const [, cellCognitive, cellDifficulty] = key.split(separator);
            return sum + (cellCognitive === cognitive && cellDifficulty === difficulty ? questions.length : 0);
        }, 0);
    const shuffle = items => [...items].sort(() => Math.random() - 0.5);
    for (let attempt = 0; attempt < 40; attempt++) {
        const cognitiveDifficulty = allocateTosFlow(plan.cognitive, plan.difficulty,
            cognitiveDifficultyCapacity, attempt > 0);
        if (!cognitiveDifficulty) {
            throw new Error('The bank cannot meet these cognitive-level and difficulty quotas together. Choose another difficulty profile or have an examiner add appropriately tagged questions.');
        }
        const cellDemand = Object.fromEntries(cognitiveDifficulty.map(item =>
            [[item.left, item.right].join(separator), item.count]));
        const assignments = allocateTosFlow(cellDemand, plan.domains, (cell, domain) => {
            const [cognitive, difficulty] = cell.split(separator);
            return (groups.get([domain, cognitive, difficulty].join(separator)) || []).length;
        }, attempt > 0);
        if (!assignments) continue;
        const selected = shuffle(assignments.flatMap(item => {
            const [cognitive, difficulty] = item.left.split(separator);
            return shuffle(groups.get([item.right, cognitive, difficulty].join(separator))).slice(0, item.count);
        }));
        if (selected.length === plan.count) return selected;
    }
    throw new Error('The bank cannot assemble this exact domain, cognitive-level, and difficulty mix. Try another count, scope, or difficulty profile.');
}

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
    getTosPlan(options) { return buildTosPlan(options); },
    generateExam({ count = 10, timeMinutes = 60, domain = 'All', easyPct = 30, medPct = 50, hardPct = 20, mode = 'mock', preview = false }) {
        if (preview && sessionUser.role !== 'ADMIN') {
            throw new Error('Only administrators can preview an exam set.');
        }
        if (!preview && (sessionUser.role === 'ADMIN' || sessionUser.role === 'EXAMINER')) {
            throw new Error('This role cannot take exams.');
        }
        if (sessionUser.role === 'GUEST') {
            if (mode !== 'practice') throw new Error('Guests can only take practice drills.');
            count = Math.min(count, 10);
        }
        const bank = this.getQuestions();
        const disciplineDomains = DISCIPLINES[domain];
        const pool = domain === 'All' ? [...bank] : bank.filter(q =>
            q.domain === domain || (disciplineDomains && disciplineDomains.includes(q.domain))
        );

        // Full TOS applies to student mock exams. Short practice drills and the
        // administrator's temporary difficulty preview keep their own flows.
        const tos = !preview && mode === 'mock' && sessionUser.role === 'STUDENT'
            ? buildTosPlan({ count, domain, easyPct, medPct, hardPct }) : null;
        if (tos && count <= 10) {
            throw new Error('Choose more than 10 questions for a mock exam. Use a practice drill for 10 or fewer.');
        }
        if (tos && pool.length < count) {
            throw new Error(`Only ${pool.length} questions are available for this scope; ${count} were requested.`);
        }

        const targetEasy = Math.round((easyPct / 100) * count);
        const targetMed = Math.round((medPct / 100) * count);
        const targetHard = count - targetEasy - targetMed;

        const easyPool = pool.filter(q => q.difficulty.toLowerCase() === 'easy');
        const medPool = pool.filter(q => q.difficulty.toLowerCase() === 'medium');
        const hardPool = pool.filter(q => q.difficulty.toLowerCase() === 'hard');

        if (preview && (pool.length < count || easyPool.length < targetEasy ||
            medPool.length < targetMed || hardPool.length < targetHard)) {
            throw new Error('The bank does not have enough questions for this exact difficulty profile.');
        }

        const shuffle = arr => [...arr].sort(() => 0.5 - Math.random());

        let selected;
        if (tos) {
            selected = selectTosQuestions(pool, tos);
        } else {
            selected = [];
            selected.push(...shuffle(easyPool).slice(0, targetEasy));
            selected.push(...shuffle(medPool).slice(0, targetMed));
            selected.push(...shuffle(hardPool).slice(0, targetHard));

            // Practice and preview retain the existing best-effort behavior.
            if (selected.length < count) {
                const remaining = pool.filter(p => !selected.some(s => s.id === p.id));
                selected.push(...shuffle(remaining).slice(0, count - selected.length));
            }
        }

        const examPayload = {
            id: 'EXAM-' + Date.now(),
            mode,
            tos,
            title: mode === 'practice'
                ? (domain === 'All' ? 'Computer Engineering Practice Drill' : `${domain} Practice Drill`)
                : mode === 'remediation' ? `${domain} Remediation Drill`
                : (domain === 'All' ? 'Computer Engineering Comprehensive Simulation' : `${domain} Targeted Mock`),
            totalItems: selected.length,
            timeSeconds: timeMinutes * 60,
            questions: selected.map(q => ({
                id: q.id,
                q: q.q,
                opts: q.opts,
                questionType: q.questionType || 'multiple_choice',
                imageUrl: q.imageUrl || null,
                optionImages: q.optionImages || [],
                userAns: null,
                flagged: false,
                domain: q.domain,
                cognitive: q.cognitive,
                difficulty: q.difficulty,
                explanation: q.explanation || ''
            }))
        };

        if (!preview) sessionStorage.setItem(STORAGE_KEYS.ACTIVE_EXAM, JSON.stringify(examPayload));
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
