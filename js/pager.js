document.addEventListener('DOMContentLoaded', () => {
    const pager = document.getElementById('pager');
    if (!pager) return;
    document.body.classList.add('pager-page');

    const slides = [...pager.querySelectorAll('.slide')];
    let current = 0;

    function goTo(i) {
        i = Math.max(0, Math.min(slides.length - 1, i));
        slides.forEach((s, idx) => {
            s.classList.toggle('active', idx === i);
            s.classList.toggle('before', idx < i);
        });
        current = i;
        slides[i].scrollTop = 0;
        history.replaceState(null, '', slides[i].id && i > 0 ? '#' + slides[i].id : location.pathname);
    }

    // In-page navigation links (Navbar clicks)
    document.addEventListener('click', e => {
        const a = e.target.closest('a[href^="#"]');
        if (!a) return;
        const targetId = a.getAttribute('href');
        const idx = slides.findIndex(s => '#' + s.id === targetId);
        if (idx > -1) { 
            e.preventDefault(); 
            goTo(idx); 
        }
    });

    // Open on the requested hash page on load
    const start = slides.findIndex(s => '#' + s.id === location.hash);
    goTo(start > -1 ? start : 0);
});