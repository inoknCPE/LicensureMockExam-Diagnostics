/* ==========================================================================
   cpedle Data & Authentication State Management
   ========================================================================== */

const DISCIPLINES = {
    'Network Engineer': ['Networking Fundamentals', 'Network Security and Administration', 'Distributed Systems and Cloud Computing'],
    'Embedded Systems Engineer': ['Embedded Systems and IoT', 'Computer Architecture and Organization', 'Sequential Logic Circuits'],
    'Systems Software Engineer': ['Operating Systems Principles', 'Process and Thread Management', 'System Software and Compilers'],
    'Cybersecurity Specialist': ['Network Security and Administration', 'Information Security and Cryptography', 'Networking Fundamentals'],
    'Algorithm Engineer': ['Sorting and Searching Algorithms', 'Linear Data Structures', 'Non-Linear Data Structures', 'Algorithm Analysis and Complexity', 'Algorithm Design Techniques'],
    'Digital Design Engineer': ['Boolean Algebra and Logic Gates', 'Combinational Logic Circuits', 'Sequential Logic Circuits', 'Switching Theory and Logic Minimization', 'Digital System Design']
};

let historyCache = JSON.parse(localStorage.getItem('cpedle_history') || '[]');

const DEFAULT_QUESTIONS = [
    {
        id: 'CPE-ALG-001',
        q: 'What is the worst-case complexity of binary search on a sorted array?',
        opts: ['O(1)', 'O(log n)', 'O(n)', 'O(n log n)'],
        ans: 1,
        difficulty: 'Medium',
        cognitive: 'Analyze',
        domain: 'Sorting and Searching Algorithms',
        explanation: 'Binary search repeatedly divides the search interval in half, leading to logarithmic complexity O(log n).'
    },
    {
        id: 'CPE-ARCH-001',
        q: 'A cache hit takes 2 ns, a miss takes 42 ns, and the hit rate is 90%. What is the average access time?',
        opts: ['2.0 ns', '6.0 ns', '4.2 ns', '44.0 ns'],
        ans: 1,
        difficulty: 'Medium',
        cognitive: 'Apply',
        domain: 'Memory Hierarchy and Cache',
        explanation: 'Average Access Time = Hit Time + (Miss Rate * Miss Penalty) = 2 + (0.10 * 40) = 6.0 ns.'
    },
    {
        id: 'CPE-DIG-001',
        q: 'Which circuit stores one bit of state?',
        opts: ['Multiplexer', 'Decoder', 'Flip-flop', 'Comparator'],
        ans: 2,
        difficulty: 'Easy',
        cognitive: 'Remember',
        domain: 'Sequential Logic Circuits',
        explanation: 'A flip-flop is a bistable multivibrator used as a 1-bit state storage element.'
    },
    {
        id: 'CPE-NET-001',
        q: 'Which OSI layer is primarily responsible for routing packets between networks?',
        opts: ['Data Link Layer', 'Transport Layer', 'Network Layer', 'Session Layer'],
        ans: 2,
        difficulty: 'Easy',
        cognitive: 'Remember',
        domain: 'Networking Fundamentals',
        explanation: 'The Network Layer (Layer 3) handles packet addressing and routing across network boundaries.'
    },
    {
        id: 'CPE-OPS-001',
        q: 'What can occur when two threads update shared data without synchronization?',
        opts: ['Race condition', 'Page fault', 'Priority inversion', 'Belady\'s anomaly'],
        ans: 0,
        difficulty: 'Easy',
        cognitive: 'Understand',
        domain: 'Process and Thread Management',
        explanation: 'Concurrent unsynchronized access to shared data leads to non-deterministic race conditions.'
    },
    {
        id: 'CPE-SW-001',
        q: 'Which test checks how several integrated modules work together?',
        opts: ['Unit test', 'Integration test', 'Regression test', 'Smoke test'],
        ans: 1,
        difficulty: 'Easy',
        cognitive: 'Understand',
        domain: 'Software Testing and Maintenance',
        explanation: 'Integration testing verifies interactions between combined program modules.'
    }
];

class CpedleDB {
    static getQuestions() {
        const stored = localStorage.getItem('cpedle_questions');
        if (!stored) {
            localStorage.setItem('cpedle_questions', JSON.stringify(DEFAULT_QUESTIONS));
            return DEFAULT_QUESTIONS;
        }
        return JSON.parse(stored);
    }

    static async saveQuestion(question) {
        const questions = this.getQuestions();
        if (!question.id) {
            question.id = 'CPE-CUSTOM-' + String(Date.now()).slice(-4);
            questions.push(question);
        } else {
            const idx = questions.findIndex(q => q.id === question.id);
            if (idx !== -1) questions[idx] = question;
            else questions.push(question);
        }
        localStorage.setItem('cpedle_questions', JSON.stringify(questions));
        
        // Sync with backend if API endpoint available
        try {
            await apiCall('/admin/questions', {
                method: 'POST',
                body: JSON.stringify(question)
            });
        } catch (e) {
            console.log('Saved to local storage (Backend sync offline)');
        }
        return question;
    }

    static async deleteQuestion(id) {
        let questions = this.getQuestions();
        questions = questions.filter(q => q.id !== id);
        localStorage.setItem('cpedle_questions', JSON.stringify(questions));

        try {
            await apiCall(`/admin/questions/${id}`, { method: 'DELETE' });
        } catch (e) {
            console.log('Deleted locally (Backend sync offline)');
        }
    }

    static async bulkImport(newQuestions) {
        const questions = this.getQuestions();
        let addedCount = 0;

        newQuestions.forEach(q => {
            if (!q.id) q.id = 'CPE-IMP-' + String(Math.floor(Math.random() * 10000));
            const existingIdx = questions.findIndex(x => x.id === q.id);
            if (existingIdx !== -1) {
                questions[existingIdx] = q;
            } else {
                questions.push(q);
                addedCount++;
            }
        });

        localStorage.setItem('cpedle_questions', JSON.stringify(questions));
        return addedCount;
    }

    static getCurrentUser() {
        const userStr = localStorage.getItem('cpedle_current_user');
        if (!userStr) {
            return { id: 'guest', username: 'Guest', role: 'GUEST' };
        }
        return JSON.parse(userStr);
    }

    static setCurrentUser(user) {
        localStorage.setItem('cpedle_current_user', JSON.stringify(user));
    }

    static async registerUser(userData) {
        try {
            const res = await apiCall('/auth/register', {
                method: 'POST',
                body: JSON.stringify(userData)
            });
            this.setCurrentUser(res.user || { ...userData, role: 'STUDENT' });
            return res;
        } catch (err) {
            // Fallback local registration
            const user = { ...userData, id: 'user-' + Date.now(), role: 'STUDENT' };
            this.setCurrentUser(user);
            return { user };
        }
    }

    static logout() {
        localStorage.removeItem('cpedle_current_user');
        window.location.href = 'login.html';
    }

    static getRequests() {
        return JSON.parse(localStorage.getItem('cpedle_requests') || '[]');
    }

    static async updateRequestStatus(id, status, comment = '') {
        const requests = this.getRequests();
        const req = requests.find(r => r.id === id);
        if (req) {
            req.status = status;
            req.comment = comment;
            localStorage.setItem('cpedle_requests', JSON.stringify(requests));
        }

        try {
            await apiCall(`/admin/requests/${id}`, {
                method: 'PATCH',
                body: JSON.stringify({ status, comment })
            });
        } catch (e) {
            console.log('Updated request locally');
        }
    }

    static generateExam(config) {
        const questions = this.getQuestions();
        let pool = questions;

        if (config.domain && config.domain !== 'All') {
            const disciplineDomains = DISCIPLINES[config.domain];
            pool = questions.filter(q => 
                q.domain === config.domain || (disciplineDomains && disciplineDomains.includes(q.domain))
            );
        }

        if (pool.length === 0) pool = questions;

        // Shuffle questions
        const shuffled = [...pool].sort(() => 0.5 - Math.random());
        const selected = shuffled.slice(0, config.count || 10);

        const examSession = {
            config,
            questions: selected,
            startTime: Date.now(),
            timeMinutes: config.timeMinutes || 60
        };

        localStorage.setItem('cpedle_active_exam', JSON.stringify(examSession));
        return examSession;
    }
}

/* API HELPER FOR FASTAPI BACKEND */
async function apiCall(endpoint, options = {}) {
    const baseUrl = 'http://127.0.0.1:8000/api';
    const defaultHeaders = { 'Content-Type': 'application/json' };

    const token = localStorage.getItem('cpedle_token');
    if (token) {
        defaultHeaders['Authorization'] = `Bearer ${token}`;
    }

    const config = {
        ...options,
        headers: {
            ...defaultHeaders,
            ...options.headers
        }
    };

    const response = await fetch(`${baseUrl}${endpoint}`, config);
    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
    }
    return response.json();
}

/* ROLE GUARD UTILITY */
async function enforceRoleGuard(allowedRoles = []) {
    const user = CpedleDB.getCurrentUser();
    if (!allowedRoles.includes(user.role)) {
        if (user.role === 'GUEST') {
            window.location.href = 'login.html';
        } else {
            alert('Access denied: Unauthorized role.');
            window.location.href = 'index.html';
        }
    }
}

/* HTML ESCAPING UTILITY */
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

/* FRONTEND FEATURE REDIRECT FOR CUSTOM GENERATOR */
function handleCustomGeneratorAccess() {
    const user = CpedleDB.getCurrentUser();
    if (!user || user.role === 'GUEST') {
        // Direct frontend redirect to signup page with parameter
        window.location.href = 'signup.html?feature=generator';
        return;
    }
    window.location.href = 'admin-generator.html';
}