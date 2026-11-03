(() => {
  const form = document.getElementById('attendance-form');
  if (!form || form.dataset.editable !== 'true') return;
  const status = document.getElementById('save-state');
  let dirty = false;
  let sending = false;
  let conflicted = false;
  form.addEventListener('change', () => { dirty = true; status.textContent = 'Unsaved changes.'; });
  form.addEventListener('input', () => { dirty = true; status.textContent = 'Unsaved changes.'; });
  window.addEventListener('beforeunload', event => {
    if (dirty && !sending) { event.preventDefault(); event.returnValue = ''; }
  });
  // Normal browser submission is the fallback. Fetch preserves the form if the network fails.
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (sending) return;
    sending = true;
    const body = new FormData(form);
    body.set('action', event.submitter.value);
    const buttons = [...form.querySelectorAll('button[type="submit"]')];
    buttons.forEach(button => button.disabled = true);
    status.textContent = 'Saving…';
    try {
      const response = await fetch(window.location.href, {method: 'POST', body, credentials: 'same-origin'});
      if (response.redirected) {
        if (new URL(response.url).pathname !== window.location.pathname) {
          throw new Error('Your session changed. Keep these marks, then sign in again in another tab.');
        }
        dirty = false;
        window.location.reload();
        return;
      }
      if (response.status === 200 || response.status === 409) {
        const page = new DOMParser().parseFromString(await response.text(), 'text/html');
        status.textContent = [...page.querySelectorAll('[role="alert"]')].map(node => node.textContent).join(' ') || 'Not saved. Check the form and try again.';
        if (response.status === 409) {
          conflicted = true;
          const reload = document.createElement('a');
          reload.href = window.location.href;
          reload.className = 'btn-secondary mt-3';
          reload.textContent = 'Reload latest register';
          status.after(reload);
        }
        return;
      }
      throw new Error('Save was not confirmed. Keep this page open and check your connection or access.');
    } catch (error) {
      status.textContent = error.message || 'Save was not confirmed. Your marks are still on this page.';
      dirty = true;
    } finally {
      sending = false;
      buttons.forEach(button => button.disabled = conflicted);
    }
  });
})();
