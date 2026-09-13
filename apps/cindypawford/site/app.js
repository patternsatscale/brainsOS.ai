/**
 * Cindy Pawford Atelier — Interactive Client Runtime
 */

(function () {
  'use strict';

  const executiveInsights = [
    '"One does not merely fetch the ball; one curates its trajectory through negative space."',
    '"Shedding is not an imperfection. It is the generous distribution of luxury cashmere across your upholstery."',
    '"The mailman believes he arrives on schedule. I believe his perimeter breaches constitute an ongoing hostile takeover attempt."',
    '"My schedule is fully booked: 1:00 PM Strategy, 1:45 PM Truffle Caviar evaluation, 2:00 PM Uncontrollable corridor sprint."',
    '"A true supermodel never chases. Unless someone casually tosses a high-velocity tennis ball near the rose garden."',
    '"True luxury is having someone scratch the exact unreachable quadrant behind your left ear."'
  ];

  const baconAlerts = [
    'Artisanal thick-cut bacon request dispatched to executive kitchen with high priority.',
    'Bacon procurement protocol initiated. Tail wag frequency increased to 450 RPM.',
    'Executive Order 001 signed: Immediate allocation of crispy hardwood-smoked bacon strips.',
    'High-fashion dietary exception granted. Crispy treats incoming.'
  ];

  let insightIndex = 0;
  let baconIndex = 0;

  document.addEventListener('DOMContentLoaded', () => {
    const quoteBtn = document.getElementById('quote-btn');
    const baconBtn = document.getElementById('bacon-btn');
    const insightText = document.querySelector('.insight-text');

    if (quoteBtn && insightText) {
      quoteBtn.addEventListener('click', () => {
        insightIndex = (insightIndex + 1) % executiveInsights.length;
        insightText.textContent = executiveInsights[insightIndex];
        insightText.parentElement.classList.add('pulse');
        setTimeout(() => {
          insightText.parentElement.classList.remove('pulse');
        }, 300);
      });
    }

    if (baconBtn && insightText) {
      baconBtn.addEventListener('click', () => {
        const msg = baconAlerts[baconIndex % baconAlerts.length];
        baconIndex++;
        insightText.textContent = `🥓 ${msg}`;
      });
    }
  });
})();
