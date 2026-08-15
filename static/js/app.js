"use strict";

/** Register and update the root-scoped PWA worker as early as possible. */
async function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) {
        return;
    }

    const workerUrl = document.body.dataset.serviceWorkerUrl;
    if (!workerUrl) {
        return;
    }

    try {
        const registration = await navigator.serviceWorker.register(workerUrl, {
            scope: "/",
            updateViaCache: "none",
        });
        await registration.update();
    } catch (error) {
        console.warn("Rahjou service worker registration failed.", error);
    }
}

/** Continue from the splash screen after its short presentation delay. */
function setupSplashRedirect() {
    const splash = document.querySelector("[data-splash-redirect-url]");
    if (!splash) {
        return;
    }

    const targetUrl = splash.dataset.splashRedirectUrl;
    const configuredDelay = Number.parseInt(
        splash.dataset.splashRedirectDelay,
        10,
    );
    const delay = Number.isFinite(configuredDelay) ? configuredDelay : 2500;

    if (targetUrl) {
        window.setTimeout(() => window.location.assign(targetUrl), delay);
    }
}

/** Enable the visual password reveal control without submitting the form. */
function setupPasswordToggles() {
    document.querySelectorAll("[data-password-toggle]").forEach((button) => {
        button.addEventListener("click", () => {
            const group = button.closest(".input-group");
            const input = group?.querySelector("input");
            const icon = button.querySelector(".material-symbols-outlined");
            if (!input || !icon) {
                return;
            }

            const shouldReveal = input.type === "password";
            input.type = shouldReveal ? "text" : "password";
            icon.textContent = shouldReveal ? "visibility" : "visibility_off";
            button.setAttribute("aria-pressed", String(shouldReveal));
            button.setAttribute(
                "aria-label",
                shouldReveal ? "پنهان کردن رمز عبور" : "نمایش رمز عبور",
            );
        });
    });
}

/** Keep the factor/prefactor segmented control accessible and visual only. */
function setupDocumentTypeSwitch() {
    const buttons = document.querySelectorAll("[data-document-type]");
    const input = document.querySelector("[data-document-type-input]");
    if (!buttons.length || !input) {
        return;
    }

    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            buttons.forEach((candidate) => {
                const isSelected = candidate === button;
                candidate.classList.toggle("active", isSelected);
                candidate.setAttribute("aria-pressed", String(isSelected));
            });
            input.value = button.dataset.documentType;
        });
    });
}

registerServiceWorker();
setupSplashRedirect();
document.addEventListener("DOMContentLoaded", () => {
    setupPasswordToggles();
    setupDocumentTypeSwitch();
});
