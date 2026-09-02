// Cockpit's theme, not the operating system's.
//
// This page brings no PatternFly of its own, but has to be able to stand beside
// cockpit-ros2-diagnostics -- and that one follows Cockpit: the shell puts its
// choice into localStorage under `shell:style` and sets `pf-v6-theme-dark` on
// the <html> of every frame. Only "auto" additionally asks the system.
//
// A plain `@media (prefers-color-scheme: dark)` is therefore NOT enough:
// whoever picks light in Cockpit while the system stands dark would get a dark
// page among nothing but light ones. That is exactly how it stood here until
// 2026-08-24.
//
// A classic script in the <head>, not a module: modules are deferred and would
// run only after the first paint -- the page would then flash bright. And no
// inline script, which the page's CSP forbids (default-src 'self').
//
// The frames sit on the same origin as the shell, which is why this page sees
// the same localStorage. When nothing stands there (a preview without Cockpit),
// "auto" remains.
(function () {
    "use strict";

    // localStorage can throw (a preview from file://, blocked cookies). Without
    // the catch this script would die in the <head>, and the page would have no
    // theme at all -- the wrong price for a setting.
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

    // A switch in another frame: localStorage reports it.
    window.addEventListener("storage", function (event) {
        if (event.key === "shell:style")
            apply();
    });

    // A switch in the shell itself: it additionally fires this event, because
    // `storage` does not fire in the document that triggers it.
    window.addEventListener("cockpit-style", function (event) {
        apply(event.detail && event.detail.style);
    });

    if (window.matchMedia) {
        window.matchMedia("(prefers-color-scheme: dark)")
              .addEventListener("change", function () { apply(); });
    }

    apply();
}());
