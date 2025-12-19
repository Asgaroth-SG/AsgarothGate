document.addEventListener('DOMContentLoaded', () => {
    const themeToggle = document.getElementById('dark-mode-toggle');
    const themeIcon = document.getElementById('theme-icon');

    let isDarkMode = localStorage.getItem('darkMode') === 'enabled';

    const enableDarkMode = () => {
        document.body.classList.add('dark-mode');
        if (themeIcon) themeIcon.classList.replace('fa-sun', 'fa-moon');
        localStorage.setItem('darkMode', 'enabled');
        isDarkMode = true;
    };

    const disableDarkMode = () => {
        document.body.classList.remove('dark-mode');
        if (themeIcon) themeIcon.classList.replace('fa-moon', 'fa-sun');
        localStorage.setItem('darkMode', 'disabled');
        isDarkMode = false;
    };

    if (isDarkMode) {
        enableDarkMode();
    } else {
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        if (prefersDark && localStorage.getItem('darkMode') === null) enableDarkMode();
    }

    if (themeToggle) {
        themeToggle.addEventListener('click', () => {
            isDarkMode ? disableDarkMode() : enableDarkMode();
        });
    }

    const loadingIndicator = document.getElementById('loading-indicator');
    const hideLoader = () => {
        if (!loadingIndicator) return;
        loadingIndicator.style.opacity = '0';
        setTimeout(() => {
            loadingIndicator.style.display = 'none';
        }, 250);
    };
    window.addEventListener('load', hideLoader);
    setTimeout(hideLoader, 2000);

    const tabsContainer = document.querySelector('.app-tabs');
    if (tabsContainer) {
        const tabButtons = tabsContainer.querySelectorAll('.app-tab-btn');
        const tabPanes = tabsContainer.querySelectorAll('.app-tab-pane');

        tabButtons.forEach(button => {
            button.addEventListener('click', () => {
                const targetId = button.getAttribute('data-target');

                tabButtons.forEach(btn => {
                    btn.classList.remove('active');
                    btn.setAttribute('aria-selected', 'false');
                });
                button.classList.add('active');
                button.setAttribute('aria-selected', 'true');

                tabPanes.forEach(pane => {
                    pane.classList.toggle('active', ('#' + pane.id) === targetId);
                });

                const targetPane = document.querySelector(targetId);
                if (targetPane) parseTwemoji(targetPane);
            });
        });
    }

    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-copy], [data-copy-text]');
        if (!btn) return;

        let text = '';
        const selector = btn.getAttribute('data-copy');
        if (selector) {
            const el = document.querySelector(selector);
            if (el) text = el.value || el.textContent || '';
        } else {
            text = btn.getAttribute('data-copy-text') || '';
        }

        text = (text || '').trim();
        if (!text) return;

        const ok = await copyToClipboard(text);
        if (ok) {
            pulseButton(btn);
            showToast('Скопировано в буфер обмена!');
        } else {
            showToast('Не удалось скопировать. Выделите и скопируйте вручную.', true);
        }
    });

    parseTwemoji(document.body);
});

async function copyToClipboard(text) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            return true;
        }
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.left = '-9999px';
        textarea.style.top = '-9999px';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        const ok = document.execCommand('copy');
        textarea.remove();
        return ok;
    } catch (e) {
        console.error('Copy failed:', e);
        return false;
    }
}

function pulseButton(btn) {
    btn.classList.add('copied');
    setTimeout(() => btn.classList.remove('copied'), 900);
}

function showToast(message, isError = false) {
    let toast = document.querySelector('.toast');
    if (toast) toast.remove();

    toast = document.createElement('div');
    toast.className = 'toast' + (isError ? ' toast-error' : '');
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    toast.textContent = message;

    document.body.appendChild(toast);

    parseTwemoji(toast);

    setTimeout(() => {
        toast.classList.add('show');
    }, 10);

    setTimeout(() => {
        toast.classList.remove('show');
        toast.addEventListener('transitionend', () => toast.remove(), { once: true });
    }, 2200);
}

function parseTwemoji(root) {
    try {
        if (!root || !window.twemoji || typeof window.twemoji.parse !== 'function') return;

        const shouldSkip = (node) => {
            if (!node || !node.parentNode) return false;
            const p = node.parentNode;
            if (!p.tagName) return false;
            const tag = p.tagName.toLowerCase();
            return tag === 'input' || tag === 'textarea' || tag === 'script' || tag === 'style';
        };

	window.twemoji.parse(root, {
		base: 'https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/',
		folder: 'svg',
		ext: '.svg',
		filter: (node, icon) => !shouldSkip(node)
	});
    } catch (e) {
        console.warn('Twemoji parse skipped:', e);
    }
}
