// Theme Management
class ThemeManager {
    constructor() {
        this.themeToggle = document.getElementById('theme-toggle');
        this.themeIcon = document.querySelector('.theme-icon');
        this.currentTheme = this.getStoredTheme() || this.getSystemTheme();

        this.init();
    }

    init() {
        this.applyTheme(this.currentTheme);
        this.themeToggle.addEventListener('click', () => this.toggleTheme());

        // Listen for system theme changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            if (this.getStoredTheme() === 'system') {
                this.applyTheme(e.matches ? 'dark' : 'light');
            }
        });
    }

    getSystemTheme() {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    getStoredTheme() {
        return localStorage.getItem('theme');
    }

    toggleTheme() {
        const themes = ['light', 'dark', 'system'];
        const currentIndex = themes.indexOf(this.currentTheme);
        const nextTheme = themes[(currentIndex + 1) % themes.length];

        this.currentTheme = nextTheme;
        localStorage.setItem('theme', nextTheme);

        const actualTheme = nextTheme === 'system' ? this.getSystemTheme() : nextTheme;
        this.applyTheme(actualTheme);
    }

    applyTheme(theme) {
        if (theme === 'dark') {
            document.documentElement.setAttribute('data-theme', 'dark');
            this.themeIcon.textContent = '🌙';
        } else {
            document.documentElement.removeAttribute('data-theme');
            this.themeIcon.textContent = '☀️';
        }

        // Show system indicator
        if (this.currentTheme === 'system') {
            this.themeIcon.textContent = '💻';
        }
    }
}

// Initialize theme on page load
document.addEventListener('DOMContentLoaded', () => {
    new ThemeManager();
});
