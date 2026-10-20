document.addEventListener('DOMContentLoaded', () => {
    const TOGGLE = document.querySelector('.theme-toggle');
    if (!TOGGLE) return;

    // Load initial state from local storage on page load
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'dark') {
        TOGGLE.setAttribute('aria-pressed', 'true');
        document.documentElement.setAttribute('data-theme', 'dark');
    }

    const applyChange = () => {
        // Determine the target state based on current aria-pressed value
        const isDark = TOGGLE.matches('[aria-pressed=true]') ? false : true;

        // Update DOM attributes
        TOGGLE.setAttribute('aria-pressed', isDark);
        document.documentElement.setAttribute('data-theme', isDark ? 'dark' : 'light');

        // Save preference
        localStorage.setItem('theme', isDark ? 'dark' : 'light');
    };

    const flip = () => {
        // Support browsers that don't have View Transitions API yet
        if (!document.startViewTransition) {
            applyChange();
        } else {
            document.startViewTransition(() => applyChange());
        }
    };

    TOGGLE.addEventListener('click', flip);
});