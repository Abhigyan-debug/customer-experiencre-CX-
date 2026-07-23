/*
 * animateStat(el, newValue, opts) - the single place every KPI card value
 * update goes through, so "cards animate on change" is implemented once and
 * reused everywhere instead of each page hand-rolling its own transition.
 *
 * Numeric values get a short eased count-up/down tween. Non-numeric values
 * (e.g. a "Top Emotion" label swap) get a brief fade/pulse instead, since
 * there's nothing sensible to interpolate between two strings.
 */
(function () {
  const activeTweens = new WeakMap();

  function parseNumeric(text) {
    if (text == null) return null;
    const match = String(text).replace(/,/g, '').match(/-?\d+(\.\d+)?/);
    return match ? parseFloat(match[0]) : null;
  }

  function easeOutCubic(t) {
    return 1 - Math.pow(1 - t, 3);
  }

  function animateStat(el, newValue, opts) {
    opts = opts || {};
    const duration = opts.duration || 550;
    const decimals = opts.decimals || 0;
    const prefix = opts.prefix || '';
    const suffix = opts.suffix || '';

    const targetNum = typeof newValue === 'number' ? newValue : parseNumeric(newValue);
    const currentNum = parseNumeric(el.textContent);

    // Cancel any tween already running on this element before starting a new one
    const existing = activeTweens.get(el);
    if (existing) cancelAnimationFrame(existing);

    if (targetNum === null) {
      // Genuinely non-numeric (e.g. a "Top Emotion" label) - fade/pulse swap.
      el.textContent = prefix + newValue + suffix;
      el.classList.add('loaded');
      el.classList.remove('stat-pulse');
      // Force reflow so re-adding the class retriggers the animation
      void el.offsetWidth;
      el.classList.add('stat-pulse');
      return;
    }

    if (currentNum === null) {
      // First paint (no previous numeric value to tween from) - still
      // respect decimals/prefix/suffix formatting, just skip the tween.
      el.textContent = prefix + targetNum.toFixed(decimals) + suffix;
      el.classList.add('loaded');
      return;
    }

    if (currentNum === targetNum) {
      el.textContent = prefix + targetNum.toFixed(decimals) + suffix;
      el.classList.add('loaded');
      return;
    }

    const start = performance.now();
    const from = currentNum;
    const to = targetNum;

    function tick(now) {
      const t = Math.min(1, (now - start) / duration);
      const eased = easeOutCubic(t);
      const value = from + (to - from) * eased;
      el.textContent = prefix + value.toFixed(decimals) + suffix;
      if (t < 1) {
        activeTweens.set(el, requestAnimationFrame(tick));
      } else {
        el.textContent = prefix + to.toFixed(decimals) + suffix;
        el.classList.add('loaded');
        activeTweens.delete(el);
      }
    }

    activeTweens.set(el, requestAnimationFrame(tick));
  }

  window.animateStat = animateStat;
})();
