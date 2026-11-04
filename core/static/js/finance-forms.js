(() => {
  const kind = document.querySelector('main select[name="kind"]');
  if (!kind) return;
  const targets = {
    discount: ['invoice', 'amount'], bursary: ['invoice', 'amount'],
    opening_debit: ['learner', 'amount'], opening_credit: ['learner', 'amount'],
    payment_reversal: ['payment'], invoice_reversal: ['invoice'],
    adjustment_reversal: ['adjustment']
  };
  const update = () => {
    for (const name of ['learner', 'invoice', 'payment', 'adjustment', 'amount']) {
      const field = kind.form.elements[name];
      const needed = (targets[kind.value] || []).includes(name);
      field.disabled = !needed;
      field.required = needed;
      field.closest('div').hidden = !needed;
      if (!needed) field.value = '';
    }
  };
  kind.addEventListener('change', update);
  update();
})();
