// Cockpits Thema, nicht das des Betriebssystems.
//
// Diese Seite bringt kein PatternFly mit, muss aber neben cockpit-ros2-
// diagnostics stehen können -- und das folgt Cockpit: die Shell legt ihre
// Wahl unter `shell:style` in den localStorage und setzt an jedem Rahmen
// `pf-v6-theme-dark` am <html>. Nur "auto" fragt zusätzlich das System.
//
// Ein reines `@media (prefers-color-scheme: dark)` reicht deshalb NICHT: wer
// in Cockpit hell wählt, während das System dunkel steht, bekäme eine dunkle
// Seite zwischen lauter hellen. Genau so stand es hier bis 2026-08-24.
//
// Klassisches Skript im <head>, kein Modul: Module sind deferred und würden
// erst nach dem ersten Bild laufen -- die Seite blitzte dann hell auf. Und
// kein Inline-Skript, das verbietet die CSP der Seite (default-src 'self').
//
// Die Rahmen liegen auf demselben Ursprung wie die Shell, deshalb sieht diese
// Seite denselben localStorage. Steht dort nichts (Vorschau ohne Cockpit),
// bleibt "auto" -- und damit das Verhalten von früher.
(function () {
    "use strict";

    // Der localStorage kann werfen (Vorschau von file://, gesperrte Cookies).
    // Ohne den Fang stuerbe dieses Skript im <head>, und die Seite haette gar
    // kein Thema -- fuer eine Einstellung ist das der falsche Preis.
    function stored() {
        try {
            return localStorage.getItem("shell:style");
        } catch (ex) {
            return null;
        }
    }

    function apply(style) {
        var chosen = style || stored() || "auto";
        var dark = chosen === "dark" ||
                   (chosen === "auto" && window.matchMedia &&
                    window.matchMedia("(prefers-color-scheme: dark)").matches);
        document.documentElement.classList.toggle("pf-v6-theme-dark", dark);
    }

    // Umschalten in einem anderen Rahmen: der localStorage meldet sich.
    window.addEventListener("storage", function (event) {
        if (event.key === "shell:style")
            apply();
    });

    // Umschalten in der Shell selbst: die feuert zusätzlich dieses Ereignis,
    // weil `storage` im auslösenden Dokument nicht fällt.
    window.addEventListener("cockpit-style", function (event) {
        apply(event.detail && event.detail.style);
    });

    if (window.matchMedia) {
        window.matchMedia("(prefers-color-scheme: dark)")
              .addEventListener("change", function () { apply(); });
    }

    apply();
}());
