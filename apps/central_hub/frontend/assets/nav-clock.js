(function () {
  const timeEl = document.getElementById("nav-time");
  const dateEl = document.getElementById("nav-date");
  if (!timeEl || !dateEl) return;

  function updateClock() {
    const now = new Date();
    timeEl.textContent = now.toLocaleTimeString("en-GB", { hour12: false });
    dateEl.textContent = now.toLocaleDateString("en-GB");
  }

  updateClock();
  setInterval(updateClock, 1000);
})();

