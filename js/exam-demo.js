/**
 * cpedle - Comprehensive Computer Engineering Exam Runner
 * Handles timing, autosave, question palette navigation, flagging, and dynamic submission.
 */

document.addEventListener('DOMContentLoaded', async () => {
    await CpedleDB.ready;
    // An exam must be explicitly created from a drill or generator page.
    let activeExam = CpedleDB.getActiveExam();
    const isGuest = CpedleDB.getCurrentUser().role === 'GUEST';
    if (isGuest && activeExam &&
        (activeExam.mode !== 'practice' || (activeExam.questions || []).length > 10)) {
        activeExam = null;
    }
    if (!activeExam || !activeExam.questions || activeExam.questions.length === 0) {
        window.location.href = isGuest ? 'subjects.html' : 'generator.html';
        return;
    }
    if (isGuest) document.title = 'Practice Drill | cpedle';

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
            } else if (q.userAns !== null && q.userAns !== undefined && q.userAns !== '') {
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

        const oldImage = document.getElementById('question-image');
        if (oldImage) oldImage.remove();
        if (currentQ.imageUrl && currentQ.imageUrl.startsWith('/static/images/')) {
            const img = document.createElement('img');
            img.id = 'question-image';
            img.src = currentQ.imageUrl;
            img.alt = 'Diagram for this question';
            img.style.cssText = 'display:block;max-width:100%;max-height:360px;object-fit:contain;margin:16px 0;';
            elQuestion.insertAdjacentElement('afterend', img);
        }
        
        if (currentQ.questionType === 'identification') {
            const input = document.createElement('input');
            input.type = 'text';
            input.maxLength = 500;
            input.className = 'answer-input';
            input.style.cssText = 'box-sizing:border-box;width:100%;padding:12px 0;border:0;border-radius:0;outline:none;box-shadow:none;appearance:none;background:transparent;color:var(--text);font:inherit;';
            input.placeholder = 'Type your answer';
            input.setAttribute('aria-label', 'Identification answer');
            input.value = typeof currentQ.userAns === 'string' ? currentQ.userAns : '';
            input.addEventListener('input', () => {
                currentQ.userAns = input.value;
                CpedleDB.saveActiveExamState(activeExam);
                updatePalette();
            });
            elOptions.appendChild(input);
        } else currentQ.opts.forEach((opt, idx) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = `option-btn ${currentQ.userAns === idx ? 'selected' : ''}`;
            btn.style.width = '100%';
            btn.textContent = `${String.fromCharCode(65 + idx)}. ${String(opt).replace(/^[A-E][.)]\s*/, '')}`;
            const imageUrl = currentQ.optionImages && currentQ.optionImages[idx];
            if (imageUrl && imageUrl.startsWith('/static/images/')) {
                const image = document.createElement('img');
                image.src = imageUrl;
                image.alt = `Option ${String.fromCharCode(65 + idx)} diagram`;
                image.style.cssText = 'display:block;max-width:100%;max-height:180px;object-fit:contain;margin:8px 0;';
                btn.appendChild(image);
            }
            btn.onclick = () => {
                currentQ.userAns = idx;
                CpedleDB.saveActiveExamState(activeExam);
                renderQuestion();
            };
            elOptions.appendChild(btn);
        });
        if (currentQ.questionType === 'both') {
            const input = document.createElement('input');
            input.type = 'text';
            input.maxLength = 500;
            input.className = 'answer-input';
            input.style.cssText = 'box-sizing:border-box;width:100%;padding:12px 0;border:0;border-radius:0;outline:none;box-shadow:none;appearance:none;background:transparent;color:var(--text);font:inherit;';
            input.placeholder = 'Or type your answer';
            input.setAttribute('aria-label', 'Alternative written answer');
            input.style.marginTop = '12px';
            input.value = typeof currentQ.userAns === 'string' ? currentQ.userAns : '';
            input.addEventListener('input', () => {
                currentQ.userAns = input.value;
                CpedleDB.saveActiveExamState(activeExam);
                elOptions.querySelectorAll('.option-btn').forEach(button => button.classList.remove('selected'));
                updatePalette();
            });
            elOptions.appendChild(input);
        }
        
        elPrev.style.visibility = currentIndex === 0 ? 'hidden' : 'visible';
        elNext.innerText = currentIndex === questions.length - 1 ? 'Submit Exam' : 'Next Question';
        
        elFlag.className = `flag-btn ${currentQ.flagged ? 'active' : ''}`;
        elFlag.innerHTML = currentQ.flagged ? '🚩 Flagged' : '🏳️️ Flag for Review';

        updatePalette();
    }

    let submitting = false;
    async function submitExam(force = false) {
        if (submitting) return;
        const unanswered = questions.filter(q => q.userAns === null || q.userAns === undefined || q.userAns === '').length;
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
