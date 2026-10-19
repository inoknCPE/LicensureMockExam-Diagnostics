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
    if (activeExam.mode === 'licensure' && activeExam.startedAt) {
        activeExam.remainingSeconds = Math.max(0, activeExam.timeSeconds -
            (Math.floor(Date.now() / 1000) - activeExam.startedAt));
    } else if (!activeExam.remainingSeconds && activeExam.remainingSeconds !== 0) {
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
        elPrev.style.visibility = currentIndex === 0 ? 'hidden' : 'visible';
        elNext.innerText = currentIndex === questions.length - 1 ? 'Submit Exam' : 'Next Question';
        
        elFlag.className = `flag-btn ${currentQ.flagged ? 'active' : ''}`;
        elFlag.innerHTML = currentQ.flagged ? '🚩 Flagged' : '🏳️️ Flag for Review';

        updatePalette();
    }

    let submitting = false;
    let exitDialog = null;
    let tabWarningDialog = null;
    let examTabWasHidden = false;
    if (activeExam.mode === 'licensure') {
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                examTabWasHidden = true;
                return;
            }
            if (!examTabWasHidden) return;
            examTabWasHidden = false;
            if (submitting || tabWarningDialog || !CpedleDB.getActiveExam() ||
                (activeExam.startedAt && Date.now() / 1000 - activeExam.startedAt >= activeExam.timeSeconds)) return;

            const dialog = document.createElement('dialog');
            tabWarningDialog = dialog;
            dialog.className = 'logout-dialog';
            dialog.setAttribute('aria-labelledby', 'tab-warning-title');
            dialog.setAttribute('aria-describedby', 'tab-warning-note');
            dialog.innerHTML = `
                <div class="logout-dialog__card">
                    <p id="tab-warning-title"><strong>Tab-switching warning</strong></p>
                    <p id="tab-warning-note">You left the exam tab or window. In a real licensure exam, tab switching is strictly not allowed.</p>
                    <p><strong>Galatians 6:7–8</strong> – <em>"Do not be deceived: God cannot be mocked. A man reaps what he sows."</em></p>
                    <button type="button" class="logout-dialog__cancel">Continue Exam</button>
                </div>`;
            dialog.addEventListener('close', () => {
                dialog.remove();
                tabWarningDialog = null;
            }, { once: true });
            document.body.appendChild(dialog);
            dialog.showModal();
            const continueButton = dialog.querySelector('button');
            continueButton.addEventListener('click', () => dialog.close());
            continueButton.focus();
        });
    }
    document.getElementById('exit-exam')?.addEventListener('click', () => {
        if (submitting || exitDialog) return;
        const dialog = document.createElement('dialog');
        exitDialog = dialog;
        dialog.className = 'logout-dialog';
        dialog.setAttribute('aria-labelledby', 'exit-exam-title');
        dialog.innerHTML = `
            <form method="dialog" class="logout-dialog__card">
                <svg class="logout-dialog__icon" viewBox="0 0 80 80" fill="none" aria-hidden="true">
                    <path d="M13 15h31a4 4 0 0 1 4 4v42a4 4 0 0 1-4 4H13a4 4 0 0 1-4-4V19a4 4 0 0 1 4-4Z" stroke="currentColor" stroke-width="2.5"/>
                    <path d="m16 19 28 7v37l-28-7V19Z" fill="#FFBFC2" stroke="currentColor" stroke-width="2.5"/>
                    <path d="M45 40h26m-9-9 9 9-9 9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <p id="exit-exam-title">Are you sure you want to exit?<br>Your answers and score will not be recorded.</p>
                <button type="submit" value="cancel" class="logout-dialog__cancel">No, Continue Exam</button>
                <button type="submit" value="confirm" class="logout-dialog__confirm">Yes, Exit Without Saving</button>
            </form>`;
        dialog.addEventListener('close', () => {
            const confirmed = dialog.returnValue === 'confirm';
            dialog.remove();
            exitDialog = null;
            if (!confirmed || submitting) return;
            clearInterval(timerInterval);
            CpedleDB.discardActiveExam();
            window.location.href = activeExam.mode === 'licensure' ? 'mock-exam.html'
                : isGuest ? 'subjects.html' : 'generator.html';
        }, { once: true });
        document.body.appendChild(dialog);
        dialog.showModal();
        dialog.querySelector('.logout-dialog__cancel').focus();
    });
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
        activeExam.remainingSeconds = activeExam.mode === 'licensure' && activeExam.startedAt
            ? Math.max(0, activeExam.timeSeconds - (Math.floor(Date.now() / 1000) - activeExam.startedAt))
            : activeExam.remainingSeconds - 1;
        CpedleDB.saveActiveExamState(activeExam);

        if (activeExam.remainingSeconds <= 0) {
            clearInterval(timerInterval);
            if (exitDialog) exitDialog.close('cancel');
            if (tabWarningDialog) tabWarningDialog.close();
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
