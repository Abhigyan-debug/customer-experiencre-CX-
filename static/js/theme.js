/*
 * Theme toggle: persists dark/light choice to localStorage and flips
 * data-theme on <html>. The actual before-paint theme application happens
 * in a tiny inline bootstrap script in <head> (see base.html/login.html/
 * register.html/error.html) - this file only owns the toggle button and
 * broadcasting the change to anything that needs to react to it (the
 * Three.js background, Chart.js instances).
 */
(function () {
  const STORAGE_KEY = 'pulsecx-theme';

  function currentTheme() {
    return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem(STORAGE_KEY, theme); } catch (e) {}
    document.dispatchEvent(new CustomEvent('theme-changed', { detail: { theme } }));
    updateToggleIcons(theme);
  }

  function updateToggleIcons(theme) {
    document.querySelectorAll('[data-theme-toggle]').forEach((btn) => {
      btn.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
      const icon = btn.querySelector('[data-lucide]');
      if (icon) {
        icon.setAttribute('data-lucide', theme === 'dark' ? 'sun' : 'moon');
        if (typeof lucide !== 'undefined') lucide.createIcons();
      }
    });
  }

  function chartTextColor() {
    return getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || '#8B9BB4';
  }
  window.pulsecxChartTextColor = chartTextColor;

  // Re-theme every live Chart.js instance on the page in one place, instead
  // of each template wiring up its own theme-change handler - Chart.js
  // tracks all instances on `Chart.instances`, so this "just works" for
  // whatever charts a given page happens to have.
  function retintCharts() {
    if (typeof Chart === 'undefined') return;
    const color = chartTextColor();
    Chart.defaults.color = color;
    Object.values(Chart.instances || {}).forEach((chart) => {
      if (chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
        chart.options.plugins.legend.labels.color = color;
      }
      if (chart.options.scales) {
        Object.values(chart.options.scales).forEach((scale) => {
          if (scale.ticks) scale.ticks.color = color;
        });
      }
      chart.update();
    });
  }

  function init() {
    updateToggleIcons(currentTheme());
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-theme-toggle]');
      if (!btn) return;
      setTheme(currentTheme() === 'dark' ? 'light' : 'dark');
    });
    document.addEventListener('theme-changed', retintCharts);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
