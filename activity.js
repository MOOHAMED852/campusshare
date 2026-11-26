(() => {
  let intervalId = null;
  let started = false;
  let accountCheckInFlight = false;

  async function sendActivityPing() {
    if (!started || document.visibilityState !== "visible") return;
    try {
      const response = await fetch("/api/student/activity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
        credentials: "same-origin",
      });
      if (response.status === 401) {
        stop();
        return;
      }
      if (!response.ok) throw new Error(`Le serveur a répondu ${response.status}.`);
    } catch (error) {
      console.warn("Impossible d’enregistrer l’activité étudiante.", error);
    }
  }

  function start() {
    if (started) return;
    started = true;
    sendActivityPing();
    intervalId = window.setInterval(sendActivityPing, 60000);
  }

  function stop() {
    started = false;
    if (intervalId !== null) window.clearInterval(intervalId);
    intervalId = null;
  }

  async function checkAccount() {
    if (accountCheckInFlight || started) return;
    accountCheckInFlight = true;
    try {
      const response = await fetch("/api/student/account", { credentials: "same-origin" });
      if (!response.ok) throw new Error(`Le serveur a répondu ${response.status}.`);
      const account = await response.json();
      if (account.authenticated) start();
    } catch (error) {
      console.warn("Impossible de vérifier la session étudiante pour le suivi d’activité.", error);
    } finally {
      accountCheckInFlight = false;
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (started) sendActivityPing();
    else checkAccount();
  });

  window.mabiblioStudentActivity = { start, stop };
  checkAccount();
})();
