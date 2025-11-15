/* ==========================================================
   Failover-Pi Dashboard - JS
   ========================================================== */

console.log("Failover-Pi Dashboard static JS loaded ✔️");

// Réduire / ouvrir la zone des logs
function toggleLogs() {
    const logbox = document.getElementById("logbox");
    if (!logbox) return;

    if (logbox.style.display === "none") {
        logbox.style.display = "block";
    } else {
        logbox.style.display = "none";
    }
}

// Copier tous les logs dans le presse-papier
function copyLogs() {
    const logbox = document.getElementById("logbox");
    if (!logbox) return;

    const text = logbox.innerText || logbox.textContent || "";

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text)
            .then(() => {
                alert("Logs copiés dans le presse-papier ✅");
            })
            .catch(() => {
                alert("Impossible de copier automatiquement. Sélectionne et copie manuellement.");
            });
    } else {
        alert("Copie auto non supportée. Sélectionne les logs et utilise Ctrl+C.");
    }
}

// Auto-scroll en bas des logs au chargement de la page
document.addEventListener("DOMContentLoaded", () => {
    const logbox = document.getElementById("logbox");
    if (logbox) {
        logbox.scrollTop = logbox.scrollHeight;
    }
});
