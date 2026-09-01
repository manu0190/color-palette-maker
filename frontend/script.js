(() => {
    "use strict";

    // ============================================================
    // ELEMENTS
    // ============================================================

    const $ = (selector) => document.querySelector(selector);

    const nav = $(".nav");
    const jsonDrop = $("#jsonDrop");
    const imageDrop = $("#imageDrop");

    const jsonFile = $("#jsonFile");
    const imageFile = $("#imageFile");

    const jsonStatus = $("#jsonStatus");
    const imageStatus = $("#imageStatus");

    const processing = $("#processing");
    const status = $("#status");
    const processBar = $("#processBar");

    const result = $("#result");
    const palettePreview = $("#palettePreview");

    const referenceResult = $("#referenceResult");
    const referenceResultImage = $("#referenceResultImage");

    const imagePreview = $("#imagePreview");
    const referenceImage = $("#referenceImage");
    const clearImage = $("#clearImage");

    const download = $("#download");
    const newButton = $("#new");


    // ============================================================
    // STATE
    // ============================================================

    let paletteUrl = null;
    let referenceUrl = null;
    let currentType = null;


    // ============================================================
    // HEADER BLUR SCROLL LISTENER
    // ============================================================

    function updateNavScroll() {
        if (!nav) return;
        if (window.scrollY > 20) {
            nav.classList.add("scrolled");
        } else {
            nav.classList.remove("scrolled");
        }
    }

    window.addEventListener("scroll", updateNavScroll, { passive: true });
    updateNavScroll();


    // ============================================================
    // FILE SIZE
    // ============================================================

    function formatBytes(bytes) {
        if (bytes < 1024 * 1024) {
            return Math.max(1, Math.round(bytes / 1024)) + " KB";
        }
        return (bytes / (1024 * 1024)).toFixed(1) + " MB";
    }


    // ============================================================
    // STATUS
    // ============================================================

    function setStatus(element, text, active = false) {
        if (!element) return;

        element.innerHTML = "";

        const dot = document.createElement("span");
        dot.className = "status-dot";

        const label = document.createElement("span");
        label.textContent = text;

        element.appendChild(dot);
        element.appendChild(label);

        element.classList.toggle("active", active);
    }


    // ============================================================
    // CLEAR RESULT
    // ============================================================

    function clearResult() {
        if (paletteUrl) {
            URL.revokeObjectURL(paletteUrl);
            paletteUrl = null;
        }

        if (palettePreview) {
            palettePreview.removeAttribute("src");
        }

        if (referenceResultImage) {
            referenceResultImage.removeAttribute("src");
        }

        if (referenceResult) {
            referenceResult.hidden = true;
        }

        if (result) {
            result.hidden = true;
        }

        if (processing) {
            processing.classList.remove("running", "complete");
        }

        if (status) {
            status.textContent = "READY";
        }

        if (processBar) {
            processBar.style.width = "0";
        }
    }


    // ============================================================
    // REFERENCE IMAGE PREVIEW
    // ============================================================

    function showReferenceImage(file) {
        if (!file || !file.type.startsWith("image/")) return;

        if (referenceUrl) {
            URL.revokeObjectURL(referenceUrl);
        }

        referenceUrl = URL.createObjectURL(file);
        referenceImage.src = referenceUrl;
        imagePreview.hidden = false;
        imageDrop.classList.add("has-image");

        setStatus(
            imageStatus,
            `${file.name} · ${formatBytes(file.size)}`,
            true
        );
    }


    // ============================================================
    // CLEAR REFERENCE IMAGE
    // ============================================================

    function clearReferenceImage() {
        if (referenceUrl) {
            URL.revokeObjectURL(referenceUrl);
            referenceUrl = null;
        }

        referenceImage.removeAttribute("src");
        imagePreview.hidden = true;
        imageDrop.classList.remove("has-image");

        if (imageFile) {
            imageFile.value = "";
        }

        setStatus(
            imageStatus,
            "Drop an image or click to browse"
        );
    }


    // ============================================================
    // SHOW PALETTE
    // ============================================================

    function showPalette(blob, type, sourceImage = null) {
        if (!blob.type.startsWith("image/")) {
            throw new Error("The server did not return a palette PNG.");
        }

        if (paletteUrl) {
            URL.revokeObjectURL(paletteUrl);
        }

        paletteUrl = URL.createObjectURL(blob);
        palettePreview.src = paletteUrl;

        if (type === "image" && sourceImage) {
            referenceResultImage.src = URL.createObjectURL(sourceImage);
            referenceResult.hidden = false;
        } else {
            referenceResult.hidden = true;
        }

        result.hidden = false;
        result.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
    }


    // ============================================================
    // PROCESS FILE
    // ============================================================

    async function processFile(file, endpoint, type, statusElement) {
        if (!file) return;

        clearResult();
        currentType = type;

        processing.classList.add("running");
        status.textContent = "PROCESSING";

        setStatus(statusElement, "Creating palette…", true);

        try {
            const form = new FormData();
            form.append("file", file);

            if (endpoint === "/extract-from-image") {
                form.append("n_segments", "100");
                form.append("target_palette_size", "12");
            }

            const response = await fetch(endpoint, {
                method: "POST",
                body: form
            });

            if (!response.ok) {
                let message = `Server error (${response.status})`;
                try {
                    const errorData = await response.json();
                    if (errorData.detail) message = errorData.detail;
                } catch {
                    // Response was not JSON
                }
                throw new Error(message);
            }

            const blob = await response.blob();
            showPalette(blob, type, type === "image" ? file : null);

            processing.classList.remove("running");
            processing.classList.add("complete");
            status.textContent = "PALETTE READY";

            setStatus(
                statusElement,
                type === "image" ? "Palette extracted successfully" : "Palette sheet generated successfully",
                true
            );

        } catch (error) {
            console.error("Color Foundry error:", error);

            processing.classList.remove("running");
            if (processBar) processBar.style.width = "0";
            status.textContent = "ERROR";

            setStatus(statusElement, error.message || "Something went wrong.");
        }
    }


    // ============================================================
    // VALIDATIONS
    // ============================================================

    function isJson(file) {
        if (!file) return false;
        return file.type === "application/json" || file.name.toLowerCase().endsWith(".json");
    }

    function isImage(file) {
        if (!file) return false;
        const extension = file.name.toLowerCase().split(".").pop();
        return ["jpg", "jpeg", "png", "webp", "avif"].includes(extension);
    }


    // ============================================================
    // HANDLERS
    // ============================================================

    function handleJson(file) {
        if (!isJson(file)) {
            setStatus(jsonStatus, "Please choose a JSON file.");
            return;
        }

        setStatus(jsonStatus, `${file.name} · ${formatBytes(file.size)}`, true);
        processFile(file, "/generate", "json", jsonStatus);
    }

    function handleImage(file) {
        if (!isImage(file)) {
            setStatus(imageStatus, "Please choose JPG, PNG, WEBP or AVIF.");
            return;
        }

        showReferenceImage(file);
        processFile(file, "/extract-from-image", "image", imageStatus);
    }


    // ============================================================
    // DROP ZONE SETUP
    // ============================================================

    function setupDropZone(zone, input, handler) {
        if (!zone || !input) return;

        zone.addEventListener("click", (event) => {
            if (event.target.closest("#clearImage") || event.target.closest(".preview-clear")) {
                return;
            }
            input.click();
        });

        zone.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                input.click();
            }
        });

        ["dragenter", "dragover"].forEach((eventName) => {
            zone.addEventListener(eventName, (event) => {
                event.preventDefault();
                zone.classList.add("drag");
            });
        });

        ["dragleave", "drop"].forEach((eventName) => {
            zone.addEventListener(eventName, (event) => {
                event.preventDefault();
                zone.classList.remove("drag");
            });
        });

        zone.addEventListener("drop", (event) => {
            const file = event.dataTransfer.files[0];
            if (file) handler(file);
        });

        input.addEventListener("change", () => {
            if (input.files && input.files[0]) {
                handler(input.files[0]);
            }
        });
    }

    setupDropZone(jsonDrop, jsonFile, handleJson);
    setupDropZone(imageDrop, imageFile, handleImage);


    // ============================================================
    // CLEAR IMAGE BUTTON
    // ============================================================

    if (clearImage) {
        clearImage.addEventListener("click", (event) => {
            event.preventDefault();
            event.stopPropagation();
            clearReferenceImage();
        });
    }


    // ============================================================
    // ACTIONS & CONTROLS
    // ============================================================

    if (download) {
        download.addEventListener("click", () => {
            if (!paletteUrl) return;

            const link = document.createElement("a");
            link.href = paletteUrl;
            link.download = "color-foundry-palette.png";
            document.body.appendChild(link);
            link.click();
            link.remove();
        });
    }

    if (newButton) {
        newButton.addEventListener("click", () => {
            clearResult();
            clearReferenceImage();
            if (jsonFile) jsonFile.value = "";
            setStatus(jsonStatus, "Drop JSON or click to browse");

            window.scrollTo({
                top: 0,
                behavior: "smooth"
            });
        });
    }


    // ============================================================
    // PROGRESSIVE SCROLL REVEAL (INTERSECTION OBSERVER)
    // ============================================================

    const revealElements = document.querySelectorAll(".reveal");

    if ("IntersectionObserver" in window) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add("visible");
                    // Unobserve to keep element smoothly visible once triggered
                    observer.unobserve(entry.target);
                }
            });
        }, {
            threshold: 0.12,
            rootMargin: "0px 0px -40px 0px"
        });

        revealElements.forEach((el) => observer.observe(el));
    } else {
        revealElements.forEach((el) => el.classList.add("visible"));
    }


    // ============================================================
    // CURSOR PARALLAX
    // ============================================================

    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        let targetX = 0;
        let targetY = 0;
        let currentX = 0;
        let currentY = 0;

        window.addEventListener("pointermove", (event) => {
            targetX = (event.clientX / window.innerWidth - 0.5) * 2;
            targetY = (event.clientY / window.innerHeight - 0.5) * 2;
        }, { passive: true });

        function animateBackground() {
            currentX += (targetX - currentX) * 0.05;
            currentY += (targetY - currentY) * 0.05;

            const leftArt = document.querySelector(".hero-art-left");
            const rightArt = document.querySelector(".hero-art-right");
            const one = $(".orb-one");
            const two = $(".orb-two");
            const three = $(".orb-three");

            if (leftArt) leftArt.style.transform = `rotate(-4deg) translate(${currentX * 18}px, ${currentY * 12}px)`;
            if (rightArt) rightArt.style.transform = `rotate(5deg) translate(${currentX * -16}px, ${currentY * -10}px)`;
            if (one) one.style.transform = `translate(${currentX * 30}px, ${currentY * 24}px)`;
            if (two) two.style.transform = `translate(${currentX * -22}px, ${currentY * -18}px)`;
            if (three) three.style.transform = `translate(${currentX * 16}px, ${currentY * 20}px)`;

            requestAnimationFrame(animateBackground);
        }

        animateBackground();
    }
})();