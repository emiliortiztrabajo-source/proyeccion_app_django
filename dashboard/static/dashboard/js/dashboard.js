function fmtMoneyAr(value) {
  const number = Number(value || 0);
  return number.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

function calcAdelanto(ratePct) {
  const amount = Number(document.getElementById('adelantoPago')?.value || 0);
  const days = Number(document.getElementById('adelantoDias')?.value || 0);
  const mode = document.getElementById('adelantoModo')?.value || 'Compuesto (capitaliza)';
  const rate = Number(ratePct || 0) / 100;

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
  const ratePct = Number(button?.dataset?.rate || 0);
  calcAdelanto(ratePct);
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
