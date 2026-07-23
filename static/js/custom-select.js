/*
 * Progressive-enhancement custom dropdown.
 *
 * Wraps every `<select data-custom-select>` with a styled combobox button +
 * listbox, but leaves the original <select> in the DOM (visually hidden,
 * not display:none) as the actual source of truth. Selecting a custom
 * option sets `select.value` and dispatches a real `change` event, so any
 * existing code wired to the native select (server-side GET-query forms,
 * client-side `change` listeners) keeps working with zero changes.
 */
(function () {
  function buildCustomSelect(select) {
    if (select.dataset.customSelectInit) return;
    select.dataset.customSelectInit = '1';

    const wrapper = document.createElement('div');
    wrapper.className = 'custom-select' +
      (select.disabled ? ' is-disabled' : '') +
      (select.hasAttribute('data-custom-select-compact') ? ' custom-select--compact' : '');

    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.className = 'custom-select-trigger';
    trigger.setAttribute('role', 'combobox');
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.disabled = select.disabled;

    const triggerLabel = document.createElement('span');
    triggerLabel.className = 'custom-select-label';
    trigger.appendChild(triggerLabel);

    const chevron = document.createElement('i');
    chevron.setAttribute('data-lucide', 'chevron-down');
    chevron.className = 'custom-select-chevron';
    trigger.appendChild(chevron);

    const panel = document.createElement('ul');
    panel.className = 'custom-select-panel';
    panel.setAttribute('role', 'listbox');
    panel.hidden = true;

    const listId = 'cs-' + Math.random().toString(36).slice(2, 9);
    panel.id = listId;
    trigger.setAttribute('aria-controls', listId);

    const options = Array.from(select.options);
    let activeIndex = Math.max(0, options.findIndex((o) => o.value === select.value));

    function renderOptions() {
      panel.innerHTML = '';
      options.forEach((opt, i) => {
        const li = document.createElement('li');
        li.setAttribute('role', 'option');
        li.id = listId + '-opt-' + i;
        li.className = 'custom-select-option';
        li.textContent = opt.textContent;
        li.setAttribute('aria-selected', opt.value === select.value ? 'true' : 'false');
        if (opt.value === select.value) li.classList.add('is-selected');
        if (i === activeIndex) li.classList.add('is-active');
        li.addEventListener('click', () => selectOption(i));
        panel.appendChild(li);
      });
    }

    function updateLabel() {
      const current = options.find((o) => o.value === select.value) || options[0];
      triggerLabel.textContent = current ? current.textContent.trim() : '';
    }

    function selectOption(i) {
      activeIndex = i;
      const opt = options[i];
      if (opt && select.value !== opt.value) {
        select.value = opt.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
      updateLabel();
      renderOptions();
      closePanel();
      trigger.focus();
    }

    function openPanel() {
      if (select.disabled) return;
      panel.hidden = false;
      trigger.classList.add('is-open');
      trigger.setAttribute('aria-expanded', 'true');
      trigger.setAttribute('aria-activedescendant', listId + '-opt-' + activeIndex);
      document.addEventListener('click', onOutsideClick);
    }

    function closePanel() {
      panel.hidden = true;
      trigger.classList.remove('is-open');
      trigger.setAttribute('aria-expanded', 'false');
      trigger.removeAttribute('aria-activedescendant');
      document.removeEventListener('click', onOutsideClick);
    }

    function togglePanel() {
      if (panel.hidden) openPanel();
      else closePanel();
    }

    function onOutsideClick(e) {
      if (!wrapper.contains(e.target)) closePanel();
    }

    function moveActive(delta) {
      activeIndex = Math.max(0, Math.min(options.length - 1, activeIndex + delta));
      renderOptions();
      trigger.setAttribute('aria-activedescendant', listId + '-opt-' + activeIndex);
      const activeEl = panel.children[activeIndex];
      if (activeEl) activeEl.scrollIntoView({ block: 'nearest' });
    }

    let typeAheadBuffer = '';
    let typeAheadTimer = null;

    trigger.addEventListener('click', togglePanel);

    trigger.addEventListener('keydown', (e) => {
      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault();
          if (panel.hidden) openPanel();
          else moveActive(1);
          break;
        case 'ArrowUp':
          e.preventDefault();
          if (panel.hidden) openPanel();
          else moveActive(-1);
          break;
        case 'Home':
          if (!panel.hidden) { e.preventDefault(); activeIndex = 0; renderOptions(); }
          break;
        case 'End':
          if (!panel.hidden) { e.preventDefault(); activeIndex = options.length - 1; renderOptions(); }
          break;
        case 'Enter':
        case ' ':
          e.preventDefault();
          if (panel.hidden) openPanel();
          else selectOption(activeIndex);
          break;
        case 'Escape':
          if (!panel.hidden) { e.preventDefault(); closePanel(); }
          break;
        case 'Tab':
          closePanel();
          break;
        default:
          if (e.key.length === 1 && /\S/.test(e.key)) {
            typeAheadBuffer += e.key.toLowerCase();
            clearTimeout(typeAheadTimer);
            typeAheadTimer = setTimeout(() => { typeAheadBuffer = ''; }, 500);
            const match = options.findIndex((o) => o.textContent.trim().toLowerCase().startsWith(typeAheadBuffer));
            if (match >= 0) selectOption(match);
          }
      }
    });

    // Keep the native select visually hidden but present and focusable-free -
    // it stays the real form field (name/value/required all still apply),
    // this is a pure visual + interaction layer on top of it.
    select.style.position = 'absolute';
    select.style.opacity = '0';
    select.style.pointerEvents = 'none';
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');

    select.addEventListener('change', () => {
      const i = options.findIndex((o) => o.value === select.value);
      if (i >= 0) activeIndex = i;
      updateLabel();
      renderOptions();
    });

    select.parentNode.insertBefore(wrapper, select);
    wrapper.appendChild(select);
    wrapper.appendChild(trigger);
    wrapper.appendChild(panel);

    updateLabel();
    renderOptions();
  }

  function init() {
    document.querySelectorAll('select[data-custom-select]').forEach(buildCustomSelect);
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
