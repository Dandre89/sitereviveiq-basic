/* SiteRevive IQ — Demo Mode guided tour engine. */
(function () {
    "use strict";

    var STORAGE_KEY = "sriq-tour-active";
    var AUTOPLAY_MS = 5000;

    var TOUR_CONTENT = {
        "core:dashboard": {
            label: "Dashboard",
            steps: [
                { target: null, title: "Welcome to your Dashboard", text: "This is your home base — a live overview of every website tracked in this workspace. Let's walk through what's here." },
                { target: "#tour-stat-websites", title: "Total websites", text: "The number of websites currently being tracked in this workspace." },
                { target: "#tour-stat-scans", title: "Total scans", text: "How many scans have been run across all your websites, ever." },
                { target: "#tour-running-scans", title: "Scans currently running", text: "Any scan actively in progress shows up here in real time, so you know what's happening right now." },
                { target: "#tour-recent-completed", title: "Recent completed scans", text: "The latest scans that finished successfully, most recent first." },
                { target: "#tour-recent-failed", title: "Recent failed scans", text: "Scans that hit an error. Click into one to see what went wrong." },
                { target: "#nav-websites", title: "Head to Websites next", text: "That's where you add new sites and drill into existing ones." }
            ]
        },
        "websites:list": {
            label: "Websites",
            steps: [
                { target: null, title: "Websites", text: "The one site you're tracking on this plan lives here, with its latest scan status and score at a glance." },
                { target: "#tour-add-website", title: "Add a website", text: "Start tracking a site — enter its URL and SiteRevive IQ takes it from there." },
                { target: "#tour-website-filters", title: "Filter & sort", text: "Narrow the list by type or status, or click any column header to sort." },
                { target: "#tour-website-table", title: "Website table", text: "Click into your website to see its full scan history, issues, and reports." }
            ]
        },
        "findings:inbox": {
            label: "Issues",
            steps: [
                { target: null, title: "Issues", text: "Every issue found across your website lands here, ranked by priority so you know what to fix first." },
                { target: "#tour-issue-filters", title: "Filter issues", text: "Filter by category, severity, or status to focus on what matters right now." },
                { target: "#tour-issue-table", title: "Issue table", text: "Priority blends impact and effort. Click any issue for full details and to change its status." }
            ]
        },
        "reports:overview": {
            label: "Reports",
            steps: [
                { target: null, title: "Reports", text: "Every Prospect Audit generated for your website, in one place." },
                { target: "#tour-reports-list", title: "Reports", text: "Generated audit reports for your website. Click one to view, export, or share it with a client." }
            ]
        },
        "workspaces:list": {
            label: "Team",
            steps: [
                { target: null, title: "Team", text: "This plan is single-user, so it's just your own account here — no invites or roles to manage." },
                { target: "#tour-team-table", title: "You", text: "Your account, as the sole member of this workspace." }
            ]
        },
        "core:settings": {
            label: "Settings",
            steps: [
                { target: null, title: "Settings", text: "Appearance, account, workspace, and notification preferences — everything here saves for real." },
                { target: "#tour-settings-appearance", title: "Appearance", text: "Pick a color theme. It applies instantly and is remembered on this device — 7 light, 7 dark." },
                { target: "#tour-settings-account", title: "Account", text: "Update your name, email, or password." },
                { target: "#tour-settings-workspace", title: "Workspace", text: "Set the workspace name." },
                { target: "#tour-settings-notifications", title: "Notifications", text: "Choose which events trigger an in-app and email notification, and set the score-drop threshold." }
            ]
        },
        "websites:detail": {
            label: "Website detail",
            steps: [
                { target: null, title: "Website detail", text: "The busiest page in the app — everything about your website lives here. Let's walk through it." },
                { target: "#tour-website-actions", title: "Quick actions", text: "Jump to reports for this site, edit its details, or trigger a new scan." },
                { target: "#tour-website-scores", title: "At-a-glance metrics", text: "Overall score, last scan status, and pages found — the fastest way to check on a site." },
                { target: "#tour-website-cwv", title: "Core Web Vitals", text: "Field-data speed metrics. This section is a preview until real Core Web Vitals collection is wired up." },
                { target: "#tour-website-issues", title: "Open issues", text: "Every unresolved issue on this site, filterable and sortable." },
                { target: "#tour-website-pages", title: "Pages", text: "Every page from the most recent scan, with status, word count, and crawl depth." },
                { target: "#tour-website-scans", title: "Scan history", text: "Every scan ever run on this site. Click one to see its detailed progress log." }
            ]
        },
        "reports:list": {
            label: "Website reports",
            steps: [
                { target: null, title: "Reports for this website", text: "Generate and manage Prospect Audit reports for this site." },
                { target: "#tour-generate-options", title: "Generate a report", text: "A Prospect Audit — health overview and top opportunities from the latest scan." },
                { target: "#tour-report-filters", title: "Generated reports", text: "Sort past reports, or delete ones you don't need anymore." }
            ]
        }
    };

    var DEFAULT_STEPS = [
        { target: null, title: "Demo mode", text: "There isn't a guided walkthrough for this page yet — check back soon. Try the Dashboard, Websites, Issues, or Reports pages for the full tour." }
    ];

    var state = {
        stepIndex: 0,
        steps: [],
        autoplay: false,
        autoplayTimer: null,
        overlayTimer: null,
        dragOffset: null
    };

    var els = {};

    function q(id) { return document.getElementById(id); }

    function cacheEls() {
        els.svg = q("tour-svg");
        els.line = q("tour-connector-line");
        els.highlight = q("tour-highlight");
        els.win = q("tour-window");
        els.handle = q("tour-window-handle");
        els.title = q("tour-window-title");
        els.closeBtn = q("tour-close-btn");
        els.stepText = q("tour-step-text");
        els.stepCounter = q("tour-step-counter");
        els.prevBtn = q("tour-prev-btn");
        els.playBtn = q("tour-play-btn");
        els.nextBtn = q("tour-next-btn");
        els.nextLabel = q("tour-next-label");
        els.toggleCheckbox = q("tour-toggle-checkbox");
    }

    function currentPageKey() {
        return document.body ? document.body.getAttribute("data-tour-page") : null;
    }

    function getSteps() {
        var key = currentPageKey();
        var entry = key ? TOUR_CONTENT[key] : null;
        return entry ? entry.steps : DEFAULT_STEPS;
    }

    function isActive() {
        return window.localStorage.getItem(STORAGE_KEY) === "1";
    }

    function setActiveFlag(val) {
        try {
            window.localStorage.setItem(STORAGE_KEY, val ? "1" : "0");
        } catch (e) { /* storage unavailable, ignore */ }
    }

    function refreshIcons() {
        if (window.lucide && typeof window.lucide.createIcons === "function") {
            window.lucide.createIcons();
        }
    }

    function stopAutoplay() {
        if (state.autoplayTimer) {
            window.clearInterval(state.autoplayTimer);
            state.autoplayTimer = null;
        }
        state.autoplay = false;
        if (els.playBtn) {
            els.playBtn.setAttribute("aria-label", "Play");
            els.playBtn.innerHTML = '<i data-lucide="play" style="width:15px;height:15px"></i>';
            refreshIcons();
        }
    }

    function startAutoplay() {
        stopAutoplay();
        state.autoplay = true;
        if (els.playBtn) {
            els.playBtn.setAttribute("aria-label", "Pause");
            els.playBtn.innerHTML = '<i data-lucide="pause" style="width:15px;height:15px"></i>';
            refreshIcons();
        }
        state.autoplayTimer = window.setInterval(function () {
            if (state.stepIndex >= state.steps.length - 1) {
                stopAutoplay();
                return;
            }
            goToStep(state.stepIndex + 1);
        }, AUTOPLAY_MS);
    }

    function toggleAutoplay() {
        if (state.autoplay) { stopAutoplay(); } else { startAutoplay(); }
    }

    function clearHighlight() {
        if (els.highlight) { els.highlight.classList.add("hidden"); }
        if (els.line) { els.line.setAttribute("x1", 0); els.line.setAttribute("y1", 0); els.line.setAttribute("x2", 0); els.line.setAttribute("y2", 0); els.line.classList.add("hidden"); }
    }

    function currentTarget() {
        var step = state.steps[state.stepIndex];
        if (!step || !step.target) { return null; }
        return document.querySelector(step.target);
    }

    // Redraws the highlight box + connector line from the target's current
    // on-screen position. Does NOT scroll. Safe to call on every scroll/resize
    // tick — calling scrollIntoView from here would re-trigger the scroll
    // event and loop forever (that was the strobing/forced-recenter bug).
    function updateOverlay() {
        // The scroll/resize listeners that call this are attached once at page load
        // and never removed, so they keep firing on every scroll long after the tour
        // has been closed. Without this guard, scrolling the page post-tour redraws
        // and un-hides the highlight box + connector line at their last position —
        // that's the "box stays stuck after Done" bug.
        if (!isActive()) {
            clearHighlight();
            return;
        }
        var target = currentTarget();
        if (!target || !els.highlight || !els.line || !els.win) {
            clearHighlight();
            return;
        }
        var rect = target.getBoundingClientRect();
        if (rect.bottom < 0 || rect.top > window.innerHeight) {
            // Target scrolled off screen entirely — hide rather than draw a stray box/line.
            clearHighlight();
            return;
        }
        var pad = 8;
        var top = rect.top - pad;
        var left = rect.left - pad;
        var width = rect.width + pad * 2;
        var height = rect.height + pad * 2;

        els.highlight.style.top = top + "px";
        els.highlight.style.left = left + "px";
        els.highlight.style.width = width + "px";
        els.highlight.style.height = height + "px";
        els.highlight.classList.remove("hidden");

        var winRect = els.win.getBoundingClientRect();
        var anchorX = winRect.left < left ? winRect.right : winRect.left;
        var anchorY = winRect.top + winRect.height / 2;
        var targetX = left + width / 2;
        var targetY = top + height / 2;

        els.line.setAttribute("x1", anchorX);
        els.line.setAttribute("y1", anchorY);
        els.line.setAttribute("x2", targetX);
        els.line.setAttribute("y2", targetY);
        els.line.classList.remove("hidden");
    }

    // Called only when a step first renders (goToStep/renderStep): scrolls the
    // target into view once, then draws the overlay. Never call this from a
    // scroll/resize handler — see updateOverlay() above.
    function positionForStep() {
        // Cancel any still-pending draw from a previous step (or from a Next/Done
        // click that fired before the last one's 260ms scroll settled) so it can't
        // fire late and draw over — or after — whatever happens next.
        if (state.overlayTimer) {
            window.clearTimeout(state.overlayTimer);
            state.overlayTimer = null;
        }
        var target = currentTarget();
        if (!target) {
            clearHighlight();
            return;
        }
        target.scrollIntoView({ block: "center", behavior: "smooth" });
        state.overlayTimer = window.setTimeout(function () {
            state.overlayTimer = null;
            updateOverlay();
        }, 260);
    }

    function renderStep() {
        var step = state.steps[state.stepIndex];
        if (!step) { return; }
        var entry = TOUR_CONTENT[currentPageKey()];
        els.title.textContent = (entry ? entry.label : "Guided tour") + (step.title ? " — " + step.title : "");
        els.stepText.textContent = step.text;
        els.stepCounter.textContent = (state.stepIndex + 1) + " / " + state.steps.length;
        els.prevBtn.disabled = state.stepIndex === 0;
        els.nextLabel.textContent = state.stepIndex === state.steps.length - 1 ? "Done" : "Next";
        positionForStep();
    }

    function goToStep(idx) {
        if (idx < 0 || idx >= state.steps.length) { return; }
        state.stepIndex = idx;
        renderStep();
    }

    function handleNext() {
        if (state.stepIndex >= state.steps.length - 1) {
            stop();
            return;
        }
        goToStep(state.stepIndex + 1);
    }

    function handlePrev() {
        goToStep(state.stepIndex - 1);
    }

    function resetWindowPosition() {
        if (!els.win) { return; }
        els.win.style.top = "78px";
        els.win.style.right = "24px";
        els.win.style.left = "";
        els.win.style.bottom = "";
    }

    function start() {
        cacheEls();
        if (!els.win) { return; }
        state.steps = getSteps();
        state.stepIndex = 0;
        setActiveFlag(true);
        if (els.toggleCheckbox) { els.toggleCheckbox.checked = true; }
        resetWindowPosition();
        els.win.classList.remove("hidden");
        renderStep();
        refreshIcons();
    }

    function stop() {
        setActiveFlag(false);
        stopAutoplay();
        if (state.overlayTimer) {
            window.clearTimeout(state.overlayTimer);
            state.overlayTimer = null;
        }
        clearHighlight();
        if (els.win) { els.win.classList.add("hidden"); }
        if (els.toggleCheckbox) { els.toggleCheckbox.checked = false; }
    }

    function toggle() {
        if (isActive()) { stop(); } else { start(); }
    }

    function initDrag() {
        if (!els.handle || !els.win) { return; }
        var dragging = false;
        var startX, startY, startTop, startLeft;

        els.handle.addEventListener("mousedown", function (e) {
            if (e.target.closest && e.target.closest("#tour-close-btn")) { return; }
            dragging = true;
            var rect = els.win.getBoundingClientRect();
            startX = e.clientX;
            startY = e.clientY;
            startTop = rect.top;
            startLeft = rect.left;
            els.win.style.right = "";
            els.win.style.left = startLeft + "px";
            els.win.style.top = startTop + "px";
            e.preventDefault();
        });

        window.addEventListener("mousemove", function (e) {
            if (!dragging) { return; }
            var dx = e.clientX - startX;
            var dy = e.clientY - startY;
            var newTop = Math.max(8, startTop + dy);
            var newLeft = Math.max(8, Math.min(window.innerWidth - 60, startLeft + dx));
            els.win.style.top = newTop + "px";
            els.win.style.left = newLeft + "px";
        });

        window.addEventListener("mouseup", function () {
            if (dragging) {
                dragging = false;
                // Redraw the connector to the (already on-screen) target — dragging
                // the window should never scroll the page.
                updateOverlay();
            }
        });
    }

    function initControls() {
        if (els.closeBtn) { els.closeBtn.addEventListener("click", stop); }
        if (els.nextBtn) { els.nextBtn.addEventListener("click", handleNext); }
        if (els.prevBtn) { els.prevBtn.addEventListener("click", handlePrev); }
        if (els.playBtn) { els.playBtn.addEventListener("click", toggleAutoplay); }
        // Resize/scroll only redraw the overlay from the target's current position —
        // they must never call positionForStep(), which scrolls. Calling scrollIntoView
        // from inside a scroll handler re-triggers that same handler and loops forever
        // (this was the "strobing" / forced-recenter bug).
        window.addEventListener("resize", updateOverlay);
        window.addEventListener("scroll", updateOverlay, true);
    }

    document.addEventListener("DOMContentLoaded", function () {
        cacheEls();
        if (!els.win) { return; }
        initControls();
        initDrag();
    });

    window.SRIQTour = {
        isActive: isActive,
        start: start,
        stop: stop,
        toggle: toggle
    };
})();
