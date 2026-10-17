document.addEventListener('DOMContentLoaded', () => {
    const loader = document.getElementById('cpedle-loader');
    
    // If the loader isn't on this page, stop running the script
    if (!loader) return;

    // Check for reduced motion preference at the OS level
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Remove immediately if already played this session or if reduced motion is enabled
    if (sessionStorage.getItem('loaderShown') === 'true' || prefersReducedMotion) {
        loader.style.display = 'none';
        return;
    }

    // The animation sequence takes 2.5 seconds. 
    // Trigger the exit animation class right after it finishes.
    setTimeout(() => {
        loader.classList.add('exit');
        
        // BULLETPROOF FALLBACK: Wait 800ms for the 0.6s exit animation to finish, 
        // then violently force it to hide and save the session state.
        setTimeout(() => {
            loader.style.display = 'none';
            sessionStorage.setItem('loaderShown', 'true');
        }, 800);
        
    }, 2500);
});