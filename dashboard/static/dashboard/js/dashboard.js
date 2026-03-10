function fmtMoneyAr(value) {
  const number = Number(value || 0);
  return number.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDateArFromIso(isoDate) {
  if (!isoDate) return '-';
  const [year, month, day] = String(isoDate).split('-').map(Number);
  if (!year || !month || !day) return String(isoDate);
  return `${String(day).padStart(2, '0')}/${String(month).padStart(2, '0')}/${year}`;
}

function computeAdvanceDays(paymentDateIso) {
  if (!paymentDateIso) return 0;
  const [year, month, day] = String(paymentDateIso).split('-').map(Number);
  if (!year || !month || !day) return 0;

  const paymentDate = new Date(year, month - 1, day);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffMs = paymentDate.getTime() - today.getTime();
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  return Math.max(0, days);
}

const chartRegistry = {};

function renderInteresChart(canvasId, labels, values) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  if (chartRegistry[canvasId]) {
    chartRegistry[canvasId].destroy();
  }
  chartRegistry[canvasId] = new Chart(el, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Interés acumulado del mes',
        data: values,
        borderColor: '#60a5fa',
        backgroundColor: 'rgba(96,165,250,.15)',
        borderWidth: 3,
        pointRadius: 4,
        tension: 0.25,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: { ticks: { color: '#cbd5e1' }, grid: { color: 'rgba(148,163,184,.12)' } },
        y: {
          ticks: {
            color: '#cbd5e1',
            callback: (value) => `$ ${fmtMoneyAr(value)}`,
          },
          grid: { color: 'rgba(148,163,184,.12)' },
        },
      },
    },
  });
}

function calcAdelanto(rateDecimal) {
  const paymentSelect = document.getElementById('adelantoPago');
  const selectedOption = paymentSelect?.selectedOptions?.[0];
  const amount = Number(selectedOption?.dataset?.amount || 0);
  const days = Number(document.getElementById('adelantoDias')?.value || 0);
  const mode = document.getElementById('adelantoModo')?.value || 'Compuesto (capitaliza)';
  const rate = Number(rateDecimal || 0);

  let lostInterest = 0;
  if (days > 0 && amount > 0 && rate > 0) {
    if (mode.startsWith('Simple')) {
      lostInterest = amount * rate * days;
    } else {
      lostInterest = amount * (Math.pow(1 + rate, days) - 1);
    }
  }

  const totalImpact = amount + lostInterest;
  const out = document.getElementById('adelantoResultado');
  if (!out) return;

  out.innerHTML = `
    <div>Monto del pago: <b>$ ${fmtMoneyAr(amount)}</b></div>
    <div>Interés que perdés por adelantar: <b>$ ${fmtMoneyAr(lostInterest)}</b></div>
    <div>Impacto total: <b>$ ${fmtMoneyAr(totalImpact)}</b></div>
  `;
}

function calcAdelantoFromButton(button) {
  const rateDecimal = Number(button?.dataset?.rateDecimal || 0);
  calcAdelanto(rateDecimal);
}

function initAdelantoCalculator(rawRows) {
  const providerEl = document.getElementById('adelantoProveedor');
  const dateEl = document.getElementById('adelantoFechaPago');
  const paymentEl = document.getElementById('adelantoPago');
  const daysEl = document.getElementById('adelantoDias');
  const resultEl = document.getElementById('adelantoResultado');

  if (!providerEl || !dateEl || !paymentEl || !daysEl) return;

  const rows = Array.isArray(rawRows)
    ? rawRows.filter((r) => r && r.provider && r.payment_date && Number(r.amount || 0) !== 0)
    : [];

  if (!rows.length) {
    providerEl.innerHTML = '<option value="">Sin datos</option>';
    dateEl.innerHTML = '<option value="">Sin datos</option>';
    paymentEl.innerHTML = '<option value="">Sin datos</option>';
    daysEl.value = 0;
    if (resultEl) resultEl.innerHTML = '<div>No hay pagos con fecha valida para este mes.</div>';
    return;
  }

  const uniqueSorted = (values) => Array.from(new Set(values)).sort((a, b) => String(a).localeCompare(String(b), 'es'));

  const fillProviders = () => {
    const providers = uniqueSorted(rows.map((r) => r.provider));
    providerEl.innerHTML = '';
    providers.forEach((provider) => {
      const opt = document.createElement('option');
      opt.value = provider;
      opt.textContent = provider;
      providerEl.appendChild(opt);
    });
  };

  const fillDates = () => {
    const provider = providerEl.value;
    const dates = uniqueSorted(rows.filter((r) => r.provider === provider).map((r) => r.payment_date));
    dateEl.innerHTML = '';
    dates.forEach((d) => {
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = fmtDateArFromIso(d);
      dateEl.appendChild(opt);
    });
  };

  const fillPayments = () => {
    const provider = providerEl.value;
    const paymentDate = dateEl.value;
    paymentEl.innerHTML = '';
    rows
      .filter((r) => r.provider === provider && r.payment_date === paymentDate)
      .sort((a, b) => Number(b.amount || 0) - Number(a.amount || 0))
      .forEach((r) => {
        const opt = document.createElement('option');
        opt.value = String(r.id);
        opt.dataset.amount = String(Number(r.amount || 0));
        opt.dataset.paymentDate = r.payment_date;
        opt.textContent = `${r.payment_label || '-'} — $ ${fmtMoneyAr(r.amount)}`;
        paymentEl.appendChild(opt);
      });
  };

  const refreshDefaultDays = () => {
    const selectedOption = paymentEl.selectedOptions?.[0];
    const paymentDateIso = selectedOption?.dataset?.paymentDate || '';
    daysEl.value = computeAdvanceDays(paymentDateIso);
  };

  const rebuildFromProvider = () => {
    fillDates();
    fillPayments();
    refreshDefaultDays();
  };

  const rebuildFromDate = () => {
    fillPayments();
    refreshDefaultDays();
  };

  providerEl.addEventListener('change', rebuildFromProvider);
  dateEl.addEventListener('change', rebuildFromDate);
  paymentEl.addEventListener('change', refreshDefaultDays);

  fillProviders();
  rebuildFromProvider();
}

function calcFCI() {
  const capital = Number(document.getElementById('fciCapital')?.value || 0);
  const days = Number(document.getElementById('fciDias')?.value || 0);
  const ratePct = Number(document.getElementById('fciTasa')?.value || 0);
  const mode = document.getElementById('fciModo')?.value || 'Compuesto (capitaliza)';
  const rate = ratePct / 100;

  const out = document.getElementById('fciResultado');
  if (!out) return;

  if (capital <= 0 || days <= 0 || rate <= 0) {
    out.innerHTML = '<div>Cargá capital, días y una tasa > 0 para ver la proyección.</div>';
    return;
  }

  let interest = 0;
  let total = 0;
  if (mode.startsWith('Simple')) {
    interest = capital * rate * days;
    total = capital + interest;
  } else {
    total = capital * Math.pow(1 + rate, days);
    interest = total - capital;
  }

  out.innerHTML = `
    <div>Capital inicial: <b>$ ${fmtMoneyAr(capital)}</b></div>
    <div>Rendimiento estimado: <b>$ ${fmtMoneyAr(interest)}</b></div>
    <div>Total estimado: <b>$ ${fmtMoneyAr(total)}</b></div>
  `;
}

function initExpensePanelToggle() {
  const toggleButton = document.getElementById('toggleExpensePanel');
  const panelContent = document.getElementById('expensePanelContent');
  if (!toggleButton || !panelContent) return;

  const setExpanded = (expanded) => {
    toggleButton.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    toggleButton.textContent = expanded ? 'Ocultar gastos' : 'Ver gastos';
    panelContent.hidden = !expanded;
  };

  setExpanded(false);

  toggleButton.addEventListener('click', () => {
    const isExpanded = toggleButton.getAttribute('aria-expanded') === 'true';
    setExpanded(!isExpanded);
  });
}

function initCafciPanelToggle() {
  const toggleButton = document.getElementById('toggleCafciPanel');
  const panelContent = document.getElementById('cafciPanelContent');
  if (!toggleButton || !panelContent) return;

  const setExpanded = (expanded) => {
    toggleButton.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    toggleButton.textContent = expanded ? 'Ocultar datos externos' : 'Ver datos externos';
    panelContent.hidden = !expanded;
  };

  setExpanded(true);

  toggleButton.addEventListener('click', () => {
    const isExpanded = toggleButton.getAttribute('aria-expanded') === 'true';
    setExpanded(!isExpanded);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initExpensePanelToggle();
  initCafciPanelToggle();
});
