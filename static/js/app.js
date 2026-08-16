"use strict";

/** Return the shared full-page loading overlay. */
function getPageLoader() {
    return document.querySelector("[data-page-loader]");
}

/** Show navigation feedback immediately while the next response is pending. */
function showPageLoader() {
    const loader = getPageLoader();
    if (!loader) {
        return;
    }

    loader.hidden = false;
    loader.setAttribute("aria-hidden", "false");
    document.body.classList.add("is-page-loading");
}

/** Reset the loader, including when a page is restored from browser history. */
function hidePageLoader() {
    const loader = getPageLoader();
    if (!loader) {
        return;
    }

    loader.hidden = true;
    loader.setAttribute("aria-hidden", "true");
    document.body.classList.remove("is-page-loading");
}

/** Add global loading feedback to internal links and form submissions. */
function setupPageLoadingIndicator() {
    if (!getPageLoader()) {
        return;
    }

    hidePageLoader();

    document.addEventListener("click", (event) => {
        if (
            event.defaultPrevented ||
            event.button !== 0 ||
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey
        ) {
            return;
        }

        const link = event.target.closest("a[href]");
        if (
            !link ||
            link.hasAttribute("download") ||
            (link.target && link.target !== "_self")
        ) {
            return;
        }

        const target = new URL(link.href, window.location.href);
        if (
            target.origin !== window.location.origin ||
            !["http:", "https:"].includes(target.protocol)
        ) {
            return;
        }

        const isSameDocumentHash =
            target.pathname === window.location.pathname &&
            target.search === window.location.search &&
            Boolean(target.hash);
        if (isSameDocumentHash) {
            return;
        }

        showPageLoader();
    });

    document.addEventListener("submit", (event) => {
        if (event.defaultPrevented) {
            return;
        }

        const form = event.target;
        if (form.target && form.target !== "_self") {
            return;
        }

        showPageLoader();
    });

    window.addEventListener("beforeunload", showPageLoader);
    window.addEventListener("pageshow", hidePageLoader);
}

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
        window.setTimeout(() => {
            showPageLoader();
            window.setTimeout(() => window.location.assign(targetUrl), 50);
        }, delay);
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

setupPageLoadingIndicator();
registerServiceWorker();
setupSplashRedirect();
document.addEventListener("DOMContentLoaded", () => {
    setupPasswordToggles();
    setupDocumentTypeSwitch();
});
