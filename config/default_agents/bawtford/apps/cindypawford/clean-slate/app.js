document.addEventListener('DOMContentLoaded', async () => {
  const eraBadge = document.getElementById('era-badge');
  try {
    const res = await fetch('era-info.json');
    if (res.ok) {
      const data = await res.json();
      if (data.era && data.week) {
        eraBadge.textContent = `Era ${data.era} • Week ${data.week}`;
      } else {
        eraBadge.textContent = `Era Active`;
      }
    } else {
      eraBadge.textContent = `Era Active`;
    }
  } catch (err) {
    eraBadge.textContent = `Era Active`;
  }
});
