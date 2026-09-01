const dropZone = document.getElementById("dropZone");

const fileInput = document.getElementById("fileInput");

const chooseButton =
    document.getElementById("chooseButton");

const fileName =
    document.getElementById("fileName");

const result =
    document.getElementById("result");

const palette =
    document.getElementById("palette");

const paletteName =
    document.getElementById("paletteName");

const colorCount =
    document.getElementById("colorCount");

const downloadButton =
    document.getElementById("downloadButton");


// -----------------------------------
// Store generated PNG
// -----------------------------------

let generatedPNG = null;


// -----------------------------------
// Choose file
// -----------------------------------

chooseButton.addEventListener(
    "click",
    () => {
        fileInput.click();
    }
);


fileInput.addEventListener(
    "change",
    () => {

        const file = fileInput.files[0];

        if (file) {
            processFile(file);
        }

    }
);


// -----------------------------------
// Drag & Drop
// -----------------------------------

dropZone.addEventListener(
    "dragover",
    (event) => {

        event.preventDefault();

        dropZone.classList.add("dragging");

    }
);


dropZone.addEventListener(
    "dragleave",
    () => {

        dropZone.classList.remove("dragging");

    }
);


dropZone.addEventListener(
    "drop",
    (event) => {

        event.preventDefault();

        dropZone.classList.remove("dragging");

        const file =
            event.dataTransfer.files[0];

        if (file) {
            processFile(file);
        }

    }
);


// -----------------------------------
// Send JSON to FastAPI
// -----------------------------------

async function processFile(file) {

    if (!file.name.toLowerCase().endsWith(".json")) {

        alert("Please choose a JSON file.");

        return;

    }


    fileName.textContent =
        `Selected: ${file.name}`;


    // Show loading
    statusText("Generating palette...");


    // Create form data
    const formData = new FormData();

    formData.append(
        "file",
        file
    );


    try {

        const response =
            await fetch(
                "/generate",
                {
                    method: "POST",
                    body: formData
                }
            );


        if (!response.ok) {

            throw new Error(
                "Server could not generate the palette."
            );

        }


        // Get PNG
        generatedPNG =
            await response.blob();


        // Show preview
        showPNGPreview(
            generatedPNG
        );


        statusText(
            "✓ Palette generated!"
        );


    }

    catch (error) {

        console.error(error);

        statusText(
            "Something went wrong."
        );


        alert(
            "Could not connect to the Python server."
        );

    }

}


// -----------------------------------
// Show PNG preview
// -----------------------------------

function showPNGPreview(blob) {

    const imageURL =
        URL.createObjectURL(blob);


    palette.innerHTML = "";


    const image =
        document.createElement("img");


    image.src = imageURL;

    image.style.width = "100%";

    image.style.display = "block";

    image.style.borderRadius = "14px";


    palette.appendChild(image);


    paletteName.textContent =
        "Generated Palette";


    colorCount.textContent =
        "PNG ready";


    result.hidden = false;

}


// -----------------------------------
// Download PNG
// -----------------------------------

downloadButton.addEventListener(
    "click",
    () => {

        if (!generatedPNG) {

            alert(
                "Generate a palette first."
            );

            return;

        }


        const url =
            URL.createObjectURL(
                generatedPNG
            );


        const link =
            document.createElement("a");


        link.href = url;

        link.download =
            "palette.png";


        document.body.appendChild(link);

        link.click();

        link.remove();


        URL.revokeObjectURL(url);


        downloadButton.textContent =
            "✓ Downloaded!";


        setTimeout(
            () => {

                downloadButton.textContent =
                    "Download PNG";

            },
            2000
        );

    }
);


// -----------------------------------
// Status helper
// -----------------------------------

function statusText(message) {

    fileName.textContent =
        message;

}