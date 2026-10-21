document.addEventListener('DOMContentLoaded', () => {
    const footer = document.querySelector('footer.footer');
    if (!footer || footer.querySelector('.legal-footer-links')) return;

    const links = document.createElement('nav');
    links.className = 'legal-footer-links';
    links.setAttribute('aria-label', 'Legal information');
    links.innerHTML = '<a href="terms.html">Terms and Conditions</a>' +
        '<a href="privacy.html">Privacy Notice</a>';
    const footerBottom = footer.querySelector('.footer-bottom');
    if (footerBottom) footer.insertBefore(links, footerBottom);
    else footer.appendChild(links);
});
