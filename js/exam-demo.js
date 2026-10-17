/**
 * cpedle - Comprehensive Computer Engineering Exam Runner
 * Handles timing, autosave, question palette navigation, flagging, and dynamic submission.
 */

document.addEventListener('DOMContentLoaded', async () => {
    await CpedleDB.ready;
    // Ensure active exam session or generate a default one from data layer
    let activeExam = CpedleDB.getActiveExam();
    if (!activeExam || !activeExam.questions || activeExam.questions.length === 0) {
        activeExam = CpedleDB.generateExam({
            count: 10, timeMinutes: 60, domain: 'All',
            mode: CpedleDB.getCurrentUser().role === 'GUEST' ? 'practice' : 'mock'
        });
    }

    const questions = activeExam.questions;
    let currentIndex = 0;

    // DOM Bindings
    const elQuestion = document.getElementById('question-text');
    const elOptions = document.getElementById('options-list');
    const elCounter = document.getElementById('exam-counter');
    const elProgress = document.getElementById('exam-progress');
    const elPrev = document.getElementById('btn-prev');
    const elNext = document.getElementById('btn-next');
    const elFlag = document.getElementById('btn-flag');
    const elTimer = document.getElementById('exam-timer');

    if (!elQuestion || !elOptions) return;
    if (!questions.length) {
        elQuestion.textContent = 'No questions are available yet. Return to the disciplines page.';
        return;
    }

    // Initialize or read existing timer
    if (!activeExam.remainingSeconds && activeExam.remainingSeconds !== 0) {
        activeExam.remainingSeconds = activeExam.timeSeconds || 3600;
    }

    // Insert Question Palette if container doesn't have it
    let elPalette = document.getElementById('exam-palette');
    if (!elPalette) {
        const cardContainer = elQuestion.closest('.card');
        if (cardContainer) {
            const paletteWrap = document.createElement('div');
            paletteWrap.style.margin = '20px 0';
            paletteWrap.style.paddingTop = '15px';
            paletteWrap.style.borderTop = '1px solid var(--border)';
            paletteWrap.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                    <span style="font-size:0.85rem; font-weight:600; color:var(--gray-text);">Question Navigator</span>
                    <span style="font-size:0.75rem; color:var(--gray-text);"><span style="color:var(--teal);">●</span> Answered | <span style="color:var(--coral);">⚑</span> Flagged</span>
                </div>
                <div id="exam-palette" style="display:flex; flex-wrap:wrap; gap:8px;"></div>
            `;
            cardContainer.insertBefore(paletteWrap, cardContainer.querySelector('.exam-controls'));
            elPalette = document.getElementById('exam-palette');
        }
    }

    function updatePalette() {
        if (!elPalette) return;
        elPalette.innerHTML = '';
        questions.forEach((q, idx) => {
            const dot = document.createElement('button');
            dot.type = 'button';
            dot.innerText = idx + 1;
            dot.style.width = '34px';
            dot.style.height = '34px';
            dot.style.borderRadius = '6px';
            dot.style.border = '1px solid var(--border)';
            dot.style.fontSize = '0.85rem';
            dot.style.fontWeight = '600';
            dot.style.cursor = 'pointer';
            dot.style.transition = 'all 0.15s ease';

            if (idx === currentIndex) {
                dot.style.outline = '2px solid var(--navy)';
            }

            if (q.flagged) {
                dot.style.borderColor = 'var(--coral)';
                dot.style.color = 'var(--coral)';
            } else if (q.userAns !== null && q.userAns !== undefined) {
                dot.style.backgroundColor = 'rgba(46, 196, 182, 0.15)';
                dot.style.borderColor = 'var(--teal)';
                dot.style.color = 'var(--teal)';
            } else {
                dot.style.backgroundColor = 'transparent';
                dot.style.color = 'var(--gray-text)';
            }

            dot.addEventListener('click', () => {
                currentIndex = idx;
                renderQuestion();
            });

            elPalette.appendChild(dot);
        });
    }

    function renderQuestion() {
        const currentQ = questions[currentIndex];
        
        elCounter.innerText = `Question ${currentIndex + 1} of ${questions.length} (${currentQ.domain || 'Computer Engineering'})`;
        elProgress.style.width = `${((currentIndex + 1) / questions.length) * 100}%`;
        elQuestion.innerText = currentQ.q;
        elOptions.innerHTML = '';
        
        currentQ.opts.forEach((opt, idx) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `option-btn ${currentQ.userAns === idx ? 'selected' : ''}`;
            btn.innerText = opt;
            btn.onclick = () => {
                currentQ.userAns = idx;
                CpedleDB.saveActiveExamState(activeExam);
                renderQuestion();
            };
            elOptions.appendChild(btn);
        });
        
        elPrev.style.visibility = currentIndex === 0 ? 'hidden' : 'visible';
        elNext.innerText = currentIndex === questions.length - 1 ? 'Submit Exam' : 'Next Question';
        
        elFlag.className = `flag-btn ${currentQ.flagged ? 'active' : ''}`;
        elFlag.innerHTML = currentQ.flagged ? '🚩 Flagged' : '🏳️️ Flag for Review';

        updatePalette();
    }

    let submitting = false;
    async function submitExam(force = false) {
        if (submitting) return;
        const unanswered = questions.filter(q => q.userAns === null || q.userAns === undefined).length;
        if (!force && unanswered > 0) {
            const proceed = confirm(`You have ${unanswered} unanswered question(s). Are you sure you want to finish and submit?`);
            if (!proceed) return;
        }
        
        // Finalize score in storage
        submitting = true;
        try {
            await CpedleDB.finalizeExam();
            window.location.href = 'results.html';
        } catch (error) {
            submitting = false;
            alert(error.message);
        }
    }

    // Control Handlers
    elNext.addEventListener('click', () => {
        if (currentIndex < questions.length - 1) {
            currentIndex++;
            renderQuestion();
        } else {
            submitExam();
        }
    });

    elPrev.addEventListener('click', () => {
        if (currentIndex > 0) {
            currentIndex--;
            renderQuestion();
        }
    });

    elFlag.addEventListener('click', () => {
        questions[currentIndex].flagged = !questions[currentIndex].flagged;
        CpedleDB.saveActiveExamState(activeExam);
        renderQuestion();
    });

    // Keyboard Shortcuts (Alt+N: Next, Alt+P: Prev, Alt+F: Flag)
    document.addEventListener('keydown', (e) => {
        if (e.altKey && e.key.toLowerCase() === 'n') {
            elNext.click();
        } else if (e.altKey && e.key.toLowerCase() === 'p') {
            elPrev.click();
        } else if (e.altKey && e.key.toLowerCase() === 'f') {
            elFlag.click();
        }
    });

    renderQuestion();

    // Timer Loop
    const timerInterval = setInterval(async () => {
        activeExam.remainingSeconds--;
        CpedleDB.saveActiveExamState(activeExam);

        if (activeExam.remainingSeconds <= 0) {
            clearInterval(timerInterval);
            alert('Time has expired! Submitting your answers automatically.');
            await submitExam(true);
            return;
        }

        const h = Math.floor(activeExam.remainingSeconds / 3600).toString().padStart(2, '0');
        const m = Math.floor((activeExam.remainingSeconds % 3600) / 60).toString().padStart(2, '0');
        const s = (activeExam.remainingSeconds % 60).toString().padStart(2, '0');
        
        if (elTimer) {
            elTimer.innerText = `${h}:${m}:${s}`;
            if (activeExam.remainingSeconds < 300) {
                elTimer.style.backgroundColor = 'rgba(255, 107, 107, 0.25)';
                elTimer.style.color = 'var(--coral)';
                elTimer.style.animation = 'pulse 1s infinite alternate';
            }
        }
    }, 1000);
});
